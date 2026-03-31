# tests/helpers/claudecat_implode_test.py
# Tests for libexec/claudecat/claudecat_implode.py
#
# Run with: python3 tests/helpers/claudecat_implode_test.py

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
IMPLODE_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_implode.py')
SETTINGS_REL_PATH = os.path.join('.claude', 'settings.local.json')


def run_setup(db_path, home):
    env = {**os.environ, 'CLAUDECAT_DB_PATH': db_path, 'HOME': home}
    return subprocess.run(['python3', SETUP_SCRIPT], env=env, capture_output=True, text=True)


def run_install_hook(home, settings_path=None):
    env = {**os.environ, 'HOME': home}
    if settings_path:
        env['CLAUDECAT_SETTINGS_PATH'] = settings_path
    return subprocess.run(['python3', INSTALL_HOOK_SCRIPT], env=env, capture_output=True, text=True)


def run_implode(db_path, home, settings_path=None, args=None, stdin_input=None):
    env = {**os.environ, 'CLAUDECAT_DB_PATH': db_path, 'HOME': home}
    if settings_path:
        env['CLAUDECAT_SETTINGS_PATH'] = settings_path
    return subprocess.run(
        ['python3', IMPLODE_SCRIPT] + (args or []),
        env=env,
        input=stdin_input,
        capture_output=True,
        text=True
    )


class TestClaudecatImplode(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.settings_path = os.path.join(self.tmpdir, SETTINGS_REL_PATH)
        self.install_dir = os.path.join(self.tmpdir, 'bin')
        os.makedirs(self.install_dir)
        self.binary = os.path.join(self.install_dir, 'claudecat')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_symlink(self):
        """Create a fake claudecat binary symlink in install_dir."""
        target = os.path.join(self.tmpdir, 'fake_claudecat')
        open(target, 'w').close()
        os.symlink(target, self.binary)

    def test_exits_0_with_message_when_nothing_to_implode(self):
        result = run_implode(self.db_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, f"implode failed: {result.stderr}")
        combined = result.stdout + result.stderr
        self.assertTrue(len(combined.strip()) > 0, "Expected some output when nothing to implode")

    def test_prints_data_dir_when_nothing_to_implode(self):
        result = run_implode(self.db_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0)
        self.assertIn(os.path.dirname(self.db_path), result.stdout)

    def test_yes_flag_removes_hook_db_and_symlink(self):
        run_setup(self.db_path, self.tmpdir)
        run_install_hook(self.tmpdir, settings_path=self.settings_path)
        self._make_symlink()
        self.assertTrue(os.path.exists(self.db_path))
        self.assertTrue(os.path.exists(self.settings_path))
        self.assertTrue(os.path.islink(self.binary))

        result = run_implode(self.db_path, self.tmpdir,
                             settings_path=self.settings_path,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0, f"implode --yes failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path), "Expected DB to be removed")
        self.assertFalse(os.path.islink(self.binary), "Expected symlink to be removed")

    def test_without_yes_reading_n_aborts(self):
        run_setup(self.db_path, self.tmpdir)
        self._make_symlink()

        run_implode(self.db_path, self.tmpdir,
                    args=['--install-dir', self.install_dir],
                    stdin_input='n\n')
        self.assertTrue(os.path.exists(self.db_path), "Expected DB to remain after 'n'")
        self.assertTrue(os.path.islink(self.binary), "Expected symlink to remain after 'n'")

    def test_without_yes_reading_y_proceeds(self):
        run_setup(self.db_path, self.tmpdir)
        self._make_symlink()

        result = run_implode(self.db_path, self.tmpdir,
                             args=['--install-dir', self.install_dir],
                             stdin_input='y\n')
        self.assertEqual(result.returncode, 0, f"implode with 'y' failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path), "Expected DB removed after 'y'")
        self.assertFalse(os.path.islink(self.binary), "Expected symlink removed after 'y'")


    def test_removes_hook_if_present(self):
        run_install_hook(self.tmpdir, settings_path=self.settings_path)
        self.assertTrue(os.path.exists(self.settings_path))

        run_implode(self.db_path, self.tmpdir,
                    settings_path=self.settings_path,
                    args=['--yes', '--install-dir', self.install_dir])

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

        run_implode(self.db_path, self.tmpdir,
                    args=['--yes', '--install-dir', self.install_dir])
        self.assertFalse(os.path.exists(self.db_path), "Expected DB deleted")

    def test_handles_missing_db_gracefully(self):
        run_install_hook(self.tmpdir, settings_path=self.settings_path)
        self.assertFalse(os.path.exists(self.db_path))

        result = run_implode(self.db_path, self.tmpdir,
                             settings_path=self.settings_path,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0,
                         f"implode should succeed without DB: {result.stderr}")

    def test_handles_missing_hook_gracefully(self):
        run_setup(self.db_path, self.tmpdir)
        self.assertFalse(os.path.exists(self.settings_path))

        result = run_implode(self.db_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0,
                         f"implode should succeed without hook: {result.stderr}")
        self.assertFalse(os.path.exists(self.db_path), "Expected DB removed")

    def test_warns_when_binary_is_not_a_symlink(self):
        # Create a regular file (not a symlink) at the binary path
        with open(self.binary, 'w') as f:
            f.write('#!/bin/bash\n')

        result = run_implode(self.db_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn('not a symlink', combined, "Expected warning about non-symlink binary")
        # Should NOT have removed the file
        self.assertTrue(os.path.exists(self.binary), "Regular file should not be removed")

    def test_prints_data_dir_after_successful_implode(self):
        run_setup(self.db_path, self.tmpdir)
        result = run_implode(self.db_path, self.tmpdir,
                             args=['--yes', '--install-dir', self.install_dir])
        self.assertEqual(result.returncode, 0)
        self.assertIn(os.path.dirname(self.db_path), result.stdout,
                      "Expected data directory path in output")

    def test_install_dir_default_used_when_not_specified(self):
        # Verify the script runs without --install-dir and uses the default
        result = run_implode(self.db_path, self.tmpdir, args=['--yes'])
        self.assertEqual(result.returncode, 0, f"implode failed without --install-dir: {result.stderr}")


if __name__ == '__main__':
    unittest.main()
