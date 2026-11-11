# tests/helpers/towit_teardown_test.py
# Tests for libexec/towit/towit_teardown.py
#
# Run with: python3 tests/helpers/towit_teardown_test.py

import unittest
import tempfile
import shutil
import json
import os
import sys
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HELPERS_DIR = os.path.join(PROJECT_ROOT, 'libexec', 'towit')
sys.path.insert(0, HELPERS_DIR)

INSTALL_HOOK_SCRIPT = os.path.join(HELPERS_DIR, 'towit_install_hook.py')
SETUP_SCRIPT = os.path.join(HELPERS_DIR, 'towit_setup.py')
TEARDOWN_SCRIPT = os.path.join(HELPERS_DIR, 'towit_teardown.py')
SETTINGS_REL_PATH = os.path.join('.claude', 'settings.local.json')


def write_config(tmpdir, db_path):
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_setup(db_path, config_path, home):
    env = {**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home}
    return subprocess.run(['python3', SETUP_SCRIPT], env=env, capture_output=True, text=True)


def run_install_hook(home):
    settings_path = os.path.join(home, SETTINGS_REL_PATH)
    env = {**os.environ, 'HOME': home, 'TOWIT_SETTINGS_PATH': settings_path}
    return subprocess.run(['python3', INSTALL_HOOK_SCRIPT], env=env, capture_output=True, text=True)


def run_teardown(db_path, config_path, home, args=None, stdin_input=None):
    settings_path = os.path.join(home, SETTINGS_REL_PATH)
    env = {**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home,
           'TOWIT_SETTINGS_PATH': settings_path}
    return subprocess.run(
        ['python3', TEARDOWN_SCRIPT] + (args or []),
        env=env,
        input=stdin_input,
        capture_output=True,
        text=True
    )


def leave_wal_with_marker(db_path, marker):
    """Create a WAL-mode db whose newest rows live only in catalog-wal, as after a killed ingest."""
    code = (
        "import os, sqlite3, sys\n"
        "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
        "c.execute('PRAGMA journal_mode=WAL')\n"
        "c.execute('PRAGMA wal_autocheckpoint=0')\n"
        "c.execute('CREATE TABLE IF NOT EXISTS leftover (t TEXT)')\n"
        "c.execute('INSERT INTO leftover VALUES (?)', (sys.argv[2],))\n"
        "os._exit(0)\n"
    )
    subprocess.run(['python3', '-c', code, db_path, marker], check=True)


def dir_contains(directory, needle):
    needle = needle.lower().encode()
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, 'rb') as fh:
                if needle in fh.read().lower():
                    return True
    return False


class TestTowitTeardown(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.settings_path = os.path.join(self.tmpdir, SETTINGS_REL_PATH)
        self.config_path = write_config(self.tmpdir, self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exits_0_with_message_when_nothing_to_tear_down(self):
        self.assertFalse(os.path.exists(self.db_path))
        self.assertFalse(os.path.exists(self.settings_path))
        result = run_teardown(self.db_path, self.config_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0, f"teardown failed: {result.stderr}")
        combined = result.stdout + result.stderr
        self.assertTrue(len(combined.strip()) > 0,
                        "Expected some output message when nothing to tear down")

    def test_yes_flag_skips_prompt_and_removes_hook_and_db(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        run_install_hook(self.tmpdir)
        self.assertTrue(os.path.exists(self.db_path))
        self.assertTrue(os.path.exists(self.settings_path))

        result = run_teardown(self.db_path, self.config_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0, f"teardown --yes failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path),
                         "Expected DB to be removed after teardown --yes")

    def test_without_yes_reading_n_aborts(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        run_install_hook(self.tmpdir)

        result = run_teardown(self.db_path, self.config_path, self.tmpdir, stdin_input='n\n')
        # Should exit 0 or non-zero but not remove files
        self.assertTrue(os.path.exists(self.db_path),
                        "Expected DB to remain when user answered 'n'")

    def test_without_yes_reading_y_proceeds(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        run_install_hook(self.tmpdir)

        result = run_teardown(self.db_path, self.config_path, self.tmpdir, stdin_input='y\n')
        self.assertEqual(result.returncode, 0, f"teardown with 'y' input failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path),
                         "Expected DB to be removed when user answered 'y'")

    def test_removes_hook_if_present(self):
        other = {"type": "command", "command": "echo other-tool"}
        seeded = {"hooks": {ev: [{"matcher": m, "hooks": [other]}]
                            for ev, m in (("Stop", ""), ("SessionEnd", ""),
                                          ("SessionStart", "startup"))}}
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        with open(self.settings_path, 'w') as f:
            json.dump(seeded, f)
        run_install_hook(self.tmpdir)
        with open(self.settings_path) as f:
            installed = json.dumps(json.load(f))
        self.assertEqual(installed.count('towit_hook.py'), 3)

        run_teardown(self.db_path, self.config_path, self.tmpdir, args=['--yes'])

        with open(self.settings_path) as f:
            data = json.load(f)
        self.assertNotIn('towit_hook.py', json.dumps(data))
        for event in ('Stop', 'SessionEnd', 'SessionStart'):
            cmds = [h['command'] for e in data['hooks'][event] for h in e['hooks']]
            self.assertEqual(cmds, ['echo other-tool'], event)

    def test_deletes_db_file_if_present(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        self.assertTrue(os.path.exists(self.db_path))

        run_teardown(self.db_path, self.config_path, self.tmpdir, args=['--yes'])
        self.assertFalse(os.path.exists(self.db_path),
                         "Expected DB file to be deleted after teardown")

    def test_handles_missing_db_gracefully(self):
        # Only hook is present, no DB
        run_install_hook(self.tmpdir)
        self.assertFalse(os.path.exists(self.db_path))

        result = run_teardown(self.db_path, self.config_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0,
                         f"teardown should succeed even without DB: {result.stderr}")

    def test_handles_missing_hook_gracefully(self):
        # Only DB is present, no hook
        run_setup(self.db_path, self.config_path, self.tmpdir)
        self.assertFalse(os.path.exists(self.settings_path))

        result = run_teardown(self.db_path, self.config_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0,
                         f"teardown should succeed even without hook: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path),
                         "Expected DB to be removed even when hook was absent")

    def test_leftover_wal_and_shm_are_removed_with_the_database(self):
        marker = 'zq' + 'marker' + 'wal7'
        leave_wal_with_marker(self.db_path, marker)
        self.assertTrue(os.path.exists(self.db_path + '-wal'), 'precondition: leftover WAL')
        self.assertTrue(dir_contains(self.tmpdir, marker))

        result = run_teardown(self.db_path, self.config_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0, result.stderr)
        for suffix in ('', '-wal', '-shm', '-journal'):
            self.assertFalse(os.path.exists(self.db_path + suffix), suffix or 'db')
        self.assertFalse(dir_contains(self.tmpdir, marker))


class TestTowitTeardownOrphanedSidecars(unittest.TestCase):
    SUFFIXES = ('-wal', '-shm', '-journal')

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = os.path.join(self.tmpdir, 'catalog.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        for suffix in self.SUFFIXES:
            with open(self.db_path + suffix, 'w') as fh:
                fh.write('leftover')

    def test_lists_sidecars_and_removes_them_with_yes(self):
        result = run_teardown(self.db_path, self.config_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Nothing to tear down', result.stdout)
        for suffix in self.SUFFIXES:
            self.assertIn(self.db_path + suffix, result.stdout)
            self.assertFalse(os.path.exists(self.db_path + suffix),
                             f'{suffix} sidecar left behind')
        self.assertFalse(os.path.exists(self.db_path))

    def test_declining_prompt_keeps_sidecars(self):
        result = run_teardown(self.db_path, self.config_path, self.tmpdir, stdin_input='n\n')
        self.assertNotIn('Nothing to tear down', result.stdout)
        for suffix in self.SUFFIXES:
            self.assertTrue(os.path.exists(self.db_path + suffix))


if __name__ == '__main__':
    unittest.main()
