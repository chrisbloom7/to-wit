# tests/helpers/towit_implode_test.py
# Tests for libexec/towit/towit_implode.py
#
# Run with: python3 tests/helpers/towit_implode_test.py

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
IMPLODE_SCRIPT = os.path.join(HELPERS_DIR, 'towit_implode.py')
SETTINGS_REL_PATH = os.path.join('.claude', 'settings.local.json')


def write_config(tmpdir, db_path):
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_setup(db_path, config_path, home):
    env = {**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home}
    return subprocess.run(['python3', SETUP_SCRIPT], env=env, capture_output=True, text=True)


def run_install_hook(home, settings_path=None):
    env = {**os.environ, 'HOME': home}
    if settings_path:
        env['TOWIT_SETTINGS_PATH'] = settings_path
    return subprocess.run(['python3', INSTALL_HOOK_SCRIPT], env=env, capture_output=True, text=True)


def run_implode(db_path, config_path, home, settings_path=None, args=None, stdin_input=None):
    env = {**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home}
    if settings_path:
        env['TOWIT_SETTINGS_PATH'] = settings_path
    return subprocess.run(
        ['python3', IMPLODE_SCRIPT] + (args or []),
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


class TestTowitImplode(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.settings_path = os.path.join(self.tmpdir, SETTINGS_REL_PATH)
        self.install_dir = os.path.join(self.tmpdir, 'bin')
        os.makedirs(self.install_dir)
        self.binary = os.path.join(self.install_dir, 'towit')
        self.config_path = write_config(self.tmpdir, self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_symlink(self):
        """Create a fake towit binary symlink in install_dir."""
        target = os.path.join(self.tmpdir, 'fake_towit')
        open(target, 'w').close()
        os.symlink(target, self.binary)

    def test_default_install_dir_is_user_local_bin(self):
        import towit_implode
        self.assertEqual(towit_implode.DEFAULT_INSTALL_DIR,
                         os.path.expanduser('~/.local/bin'))

    def test_exits_0_with_message_when_nothing_to_implode(self):
        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, f"implode failed: {result.stderr}")
        combined = result.stdout + result.stderr
        self.assertTrue(len(combined.strip()) > 0, "Expected some output when nothing to implode")

    def test_prints_data_dir_when_nothing_to_implode(self):
        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0)
        self.assertIn(os.path.dirname(self.db_path), result.stdout)

    def test_yes_flag_removes_hook_db_and_symlink(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        run_install_hook(self.tmpdir, settings_path=self.settings_path)
        self._make_symlink()
        self.assertTrue(os.path.exists(self.db_path))
        self.assertTrue(os.path.exists(self.settings_path))
        self.assertTrue(os.path.islink(self.binary))

        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             settings_path=self.settings_path,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, f"implode --yes failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path), "Expected DB to be removed")
        self.assertFalse(os.path.islink(self.binary), "Expected symlink to be removed")

    def test_without_yes_reading_n_aborts(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        self._make_symlink()

        run_implode(self.db_path, self.config_path, self.tmpdir,
                    args=['--install-dir', self.install_dir],
                    stdin_input='n\n')
        self.assertTrue(os.path.exists(self.db_path), "Expected DB to remain after 'n'")
        self.assertTrue(os.path.islink(self.binary), "Expected symlink to remain after 'n'")

    def test_without_yes_reading_y_proceeds(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        self._make_symlink()

        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--install-dir', self.install_dir],
                             stdin_input='y\n')
        self.assertEqual(result.returncode, 0, f"implode with 'y' failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path), "Expected DB removed after 'y'")
        self.assertFalse(os.path.islink(self.binary), "Expected symlink removed after 'y'")


    def test_removes_hook_if_present(self):
        other = {"type": "command", "command": "echo other-tool"}
        seeded = {"hooks": {ev: [{"matcher": m, "hooks": [other]}]
                            for ev, m in (("Stop", ""), ("SessionEnd", ""),
                                          ("SessionStart", "startup"))}}
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        with open(self.settings_path, 'w') as f:
            json.dump(seeded, f)
        run_install_hook(self.tmpdir, settings_path=self.settings_path)
        with open(self.settings_path) as f:
            installed = json.dumps(json.load(f))
        self.assertEqual(installed.count('towit_hook.py'), 3)

        run_implode(self.db_path, self.config_path, self.tmpdir,
                    settings_path=self.settings_path,
                    args=['--yes', '--install-dir', self.install_dir])

        with open(self.settings_path) as f:
            data = json.load(f)
        self.assertNotIn('towit_hook.py', json.dumps(data))
        for event in ('Stop', 'SessionEnd', 'SessionStart'):
            cmds = [h['command'] for e in data['hooks'][event] for h in e['hooks']]
            self.assertEqual(cmds, ['echo other-tool'], event)

    def test_deletes_db_file_if_present(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        self.assertTrue(os.path.exists(self.db_path))

        run_implode(self.db_path, self.config_path, self.tmpdir,
                    args=['--yes', '--install-dir', self.install_dir])
        self.assertFalse(os.path.exists(self.db_path), "Expected DB deleted")

    def test_handles_missing_db_gracefully(self):
        run_install_hook(self.tmpdir, settings_path=self.settings_path)
        self.assertFalse(os.path.exists(self.db_path))

        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             settings_path=self.settings_path,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0,
                         f"implode should succeed without DB: {result.stderr}")

    def test_handles_missing_hook_gracefully(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        self.assertFalse(os.path.exists(self.settings_path))

        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0,
                         f"implode should succeed without hook: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path), "Expected DB removed")

    def test_warns_when_binary_is_not_a_symlink(self):
        # Create a regular file (not a symlink) at the binary path
        with open(self.binary, 'w') as f:
            f.write('#!/bin/bash\n')

        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn('not a symlink', combined, "Expected warning about non-symlink binary")
        # Should NOT have removed the file
        self.assertTrue(os.path.exists(self.binary), "Regular file should not be removed")

    def test_prints_data_dir_after_successful_implode(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0)
        self.assertIn(os.path.dirname(self.db_path), result.stdout,
                      "Expected data directory path in output")

    def test_install_dir_default_used_when_not_specified(self):
        # Verify the script runs without --install-dir and uses the default
        result = run_implode(self.db_path, self.config_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0, f"implode failed without --install-dir: {result.stderr}")

    def test_leftover_wal_and_shm_are_removed_with_the_database(self):
        marker = 'zq' + 'marker' + 'wal7'
        leave_wal_with_marker(self.db_path, marker)
        self.assertTrue(os.path.exists(self.db_path + '-wal'), 'precondition: leftover WAL')
        self.assertTrue(dir_contains(self.tmpdir, marker))

        result = run_implode(self.db_path, self.config_path, self.tmpdir, args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, result.stderr)
        for suffix in ('', '-wal', '-shm', '-journal'):
            self.assertFalse(os.path.exists(self.db_path + suffix), suffix or 'db')
        self.assertFalse(dir_contains(self.tmpdir, marker))


class TestIsHomebrewInstall(unittest.TestCase):
    def test_cellar_path_is_homebrew(self):
        from towit_implode import is_homebrew_install
        self.assertTrue(is_homebrew_install(
            '/opt/homebrew/Cellar/towit/0.9.2/libexec/towit/towit_implode.py'))

    def test_clone_path_is_not_homebrew(self):
        from towit_implode import is_homebrew_install
        self.assertFalse(is_homebrew_install('/Users/me/src/to-wit/libexec/towit/towit_implode.py'))

    def test_opt_path_is_not_homebrew(self):
        from towit_implode import is_homebrew_install
        self.assertFalse(is_homebrew_install(
            '/opt/homebrew/opt/towit/libexec/towit/towit_implode.py'))

    def test_cellar_must_be_a_whole_path_component(self):
        from towit_implode import is_homebrew_install
        self.assertFalse(is_homebrew_install('/src/MyCellar/towit/libexec/towit_implode.py'))
        self.assertFalse(is_homebrew_install('/src/Cellar-notes/towit/libexec/towit_implode.py'))


class TestImplodeUnderHomebrew(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'data', 'test.db')
        os.makedirs(os.path.dirname(self.db_path))
        self.settings_path = os.path.join(self.tmpdir, SETTINGS_REL_PATH)
        self.config_path = write_config(self.tmpdir, self.db_path)
        self.install_dir = os.path.join(self.tmpdir, 'bin')
        os.makedirs(self.install_dir)
        libexec = os.path.join(self.tmpdir, 'Cellar', 'towit', '0.9.2', 'libexec', 'towit')
        shutil.copytree(HELPERS_DIR, libexec, ignore=shutil.ignore_patterns('__pycache__'))
        self.cellar_implode = os.path.join(libexec, 'towit_implode.py')
        self.cellar_install_hook = os.path.join(libexec, 'towit_install_hook.py')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _env(self):
        return {**os.environ, 'TOWIT_CONFIG_PATH': self.config_path, 'HOME': self.tmpdir,
                'TOWIT_SETTINGS_PATH': self.settings_path}

    def _run_implode(self, args=None):
        return subprocess.run(['python3', self.cellar_implode, '--yes'] + (args or []),
                              env=self._env(), capture_output=True, text=True)

    def test_removes_hooks_and_db_and_prints_brew_uninstall_hint(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        subprocess.run(['python3', self.cellar_install_hook], env=self._env(),
                       capture_output=True, text=True, check=True)
        self.assertTrue(os.path.exists(self.db_path))
        with open(self.settings_path) as f:
            self.assertIn('towit_hook.py', f.read())

        result = self._run_implode(['--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(self.db_path), 'Expected DB removed')
        with open(self.settings_path) as f:
            self.assertNotIn('towit_hook.py', f.read())
        self.assertIn('brew uninstall towit', result.stdout)
        self.assertNotIn('Nothing to remove', result.stdout)

    def test_skips_binary_symlink_lookup(self):
        run_setup(self.db_path, self.config_path, self.tmpdir)
        target = os.path.join(self.tmpdir, 'fake_towit')
        open(target, 'w').close()
        binary = os.path.join(self.install_dir, 'towit')
        os.symlink(target, binary)

        result = self._run_implode(['--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.islink(binary), 'Homebrew-managed symlink must be left alone')
        self.assertFalse(os.path.exists(self.db_path))
        self.assertIn('brew uninstall towit', result.stdout)

    def test_nothing_to_remove_still_exits_0_and_prints_hint(self):
        result = self._run_implode(['--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('brew uninstall towit', result.stdout)

    def test_clone_install_does_not_print_brew_hint(self):
        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('brew uninstall', result.stdout)


class TestImplodeOrphanedSidecars(unittest.TestCase):
    SUFFIXES = ('-wal', '-shm', '-journal')

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = os.path.join(self.tmpdir, 'catalog.db')
        self.install_dir = os.path.join(self.tmpdir, 'bin')
        os.makedirs(self.install_dir)
        self.config_path = write_config(self.tmpdir, self.db_path)
        for suffix in self.SUFFIXES:
            with open(self.db_path + suffix, 'w') as fh:
                fh.write('leftover')

    def test_lists_sidecars_and_removes_them_with_yes(self):
        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Nothing to remove', result.stdout)
        will_remove = result.stdout.split('The following will be removed:')[-1]
        for suffix in self.SUFFIXES:
            self.assertIn(self.db_path + suffix, will_remove)
            self.assertFalse(os.path.exists(self.db_path + suffix),
                             f'{suffix} sidecar left behind')
        self.assertFalse(os.path.exists(self.db_path))

    def test_declining_prompt_keeps_sidecars(self):
        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--install-dir', self.install_dir], stdin_input='n\n')
        self.assertNotIn('Nothing to remove', result.stdout)
        for suffix in self.SUFFIXES:
            self.assertTrue(os.path.exists(self.db_path + suffix))

    def test_sidecars_only_reports_leftover_files_not_database_deleted(self):
        self.assertFalse(os.path.exists(self.db_path))
        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Leftover database files deleted', result.stdout)
        self.assertNotIn('Database deleted', result.stdout)

    def test_existing_database_still_reports_database_deleted(self):
        for suffix in self.SUFFIXES:
            os.remove(self.db_path + suffix)
        run_setup(self.db_path, self.config_path, self.tmpdir)
        self.assertTrue(os.path.exists(self.db_path))
        result = run_implode(self.db_path, self.config_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'Database deleted: {self.db_path}', result.stdout)
        self.assertNotIn('Leftover database files deleted', result.stdout)
        self.assertFalse(os.path.exists(self.db_path))


if __name__ == '__main__':
    unittest.main()
