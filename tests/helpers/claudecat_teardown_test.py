# tests/helpers/claudecat_teardown_test.py
# Tests for libexec/claudecat/claudecat_teardown.py
#
# Run with: python3 tests/helpers/claudecat_teardown_test.py

import unittest
import tempfile
import shutil
import json
import os
import sys
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HELPERS_DIR = os.path.join(PROJECT_ROOT, 'libexec', 'claudecat')
sys.path.insert(0, HELPERS_DIR)

INSTALL_HOOK_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_install_hook.py')
SETUP_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_setup.py')
TEARDOWN_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_teardown.py')
SETTINGS_REL_PATH = os.path.join('.claude', 'settings.local.json')


def run_setup(db_path, home):
    env = {**os.environ, 'CLAUDECAT_DB_PATH': db_path, 'HOME': home}
    return subprocess.run(['python3', SETUP_SCRIPT], env=env, capture_output=True, text=True)


def run_install_hook(home):
    env = {**os.environ, 'HOME': home}
    return subprocess.run(['python3', INSTALL_HOOK_SCRIPT], env=env, capture_output=True, text=True)


def run_teardown(db_path, home, args=None, stdin_input=None):
    env = {**os.environ, 'CLAUDECAT_DB_PATH': db_path, 'HOME': home}
    return subprocess.run(
        ['python3', TEARDOWN_SCRIPT] + (args or []),
        env=env,
        input=stdin_input,
        capture_output=True,
        text=True
    )


class TestClaudecatTeardown(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.settings_path = os.path.join(self.tmpdir, SETTINGS_REL_PATH)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exits_0_with_message_when_nothing_to_tear_down(self):
        self.assertFalse(os.path.exists(self.db_path))
        self.assertFalse(os.path.exists(self.settings_path))
        result = run_teardown(self.db_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0, f"teardown failed: {result.stderr}")
        combined = result.stdout + result.stderr
        self.assertTrue(len(combined.strip()) > 0,
                        "Expected some output message when nothing to tear down")

    def test_yes_flag_skips_prompt_and_removes_hook_and_db(self):
        run_setup(self.db_path, self.tmpdir)
        run_install_hook(self.tmpdir)
        self.assertTrue(os.path.exists(self.db_path))
        self.assertTrue(os.path.exists(self.settings_path))

        result = run_teardown(self.db_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0, f"teardown --yes failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path),
                         "Expected DB to be removed after teardown --yes")

    def test_without_yes_reading_n_aborts(self):
        run_setup(self.db_path, self.tmpdir)
        run_install_hook(self.tmpdir)

        result = run_teardown(self.db_path, self.tmpdir, stdin_input='n\n')
        # Should exit 0 or non-zero but not remove files
        self.assertTrue(os.path.exists(self.db_path),
                        "Expected DB to remain when user answered 'n'")

    def test_without_yes_reading_y_proceeds(self):
        run_setup(self.db_path, self.tmpdir)
        run_install_hook(self.tmpdir)

        result = run_teardown(self.db_path, self.tmpdir, stdin_input='y\n')
        self.assertEqual(result.returncode, 0, f"teardown with 'y' input failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path),
                         "Expected DB to be removed when user answered 'y'")

    def test_removes_hook_if_present(self):
        run_install_hook(self.tmpdir)
        self.assertTrue(os.path.exists(self.settings_path))

        run_teardown(self.db_path, self.tmpdir, args=['--yes'])

        if os.path.exists(self.settings_path):
            with open(self.settings_path) as f:
                data = json.load(f)
            stop_hooks = data.get('hooks', {}).get('Stop', [])
            all_commands = []
            for entry in stop_hooks:
                if isinstance(entry, dict):
                    if 'command' in entry:
                        all_commands.append(entry['command'])
                    for nested in entry.get('hooks', []):
                        if isinstance(nested, dict) and 'command' in nested:
                            all_commands.append(nested['command'])
            self.assertFalse(
                any('claudecat_hook.py' in cmd for cmd in all_commands),
                f"Expected claudecat hook removed, but found: {all_commands}"
            )

    def test_deletes_db_file_if_present(self):
        run_setup(self.db_path, self.tmpdir)
        self.assertTrue(os.path.exists(self.db_path))

        run_teardown(self.db_path, self.tmpdir, args=['--yes'])
        self.assertFalse(os.path.exists(self.db_path),
                         "Expected DB file to be deleted after teardown")

    def test_handles_missing_db_gracefully(self):
        # Only hook is present, no DB
        run_install_hook(self.tmpdir)
        self.assertFalse(os.path.exists(self.db_path))

        result = run_teardown(self.db_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0,
                         f"teardown should succeed even without DB: {result.stderr}")

    def test_handles_missing_hook_gracefully(self):
        # Only DB is present, no hook
        run_setup(self.db_path, self.tmpdir)
        self.assertFalse(os.path.exists(self.settings_path))

        result = run_teardown(self.db_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0,
                         f"teardown should succeed even without hook: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path),
                         "Expected DB to be removed even when hook was absent")


if __name__ == '__main__':
    unittest.main()
