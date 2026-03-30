# Tests for libexec/claudecat/claudecat_install_hook.py
#
# Run with: python3 tests/helpers/claudecat_install_hook_test.py

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


def run_install_hook(settings_path):
    """Run claudecat_install_hook.py with an isolated settings path."""
    env = {**os.environ, 'CLAUDECAT_SETTINGS_PATH': settings_path}
    return subprocess.run(
        ['python3', INSTALL_HOOK_SCRIPT],
        env=env, capture_output=True, text=True
    )


class TestClaudecatInstallHook(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.local.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_settings(self):
        with open(self.settings_path) as f:
            return json.load(f)

    def _claudecat_hooks(self, data):
        """Return list of claudecat hook command strings from settings data."""
        hooks = []
        for entry in data.get('hooks', {}).get('Stop', []):
            for hook in entry.get('hooks', []):
                if 'claudecat_hook.py' in hook.get('command', ''):
                    hooks.append(hook['command'])
        return hooks

    def test_creates_settings_file_if_not_exists(self):
        self.assertFalse(os.path.exists(self.settings_path))
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, f"install-hook failed: {result.stderr}")
        self.assertTrue(os.path.exists(self.settings_path),
                        f"Expected settings file at {self.settings_path}")

    def test_adds_hook_entry_to_existing_settings_preserving_other_keys(self):
        settings = {"permissions": {"allow": ["Bash(git status)"]}}
        with open(self.settings_path, 'w') as f:
            json.dump(settings, f)

        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, f"install-hook failed: {result.stderr}")

        data = self._read_settings()
        self.assertIn('hooks', data, "Expected 'hooks' key after install")
        self.assertIn('permissions', data, "Expected 'permissions' key to be preserved")

    def test_idempotent_running_twice_prints_already_installed(self):
        run_install_hook(self.settings_path)
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, f"Second install-hook failed: {result.stderr}")
        combined = result.stdout + result.stderr
        self.assertIn('already', combined.lower(),
                      f"Expected 'already' in output on second run, got: {combined!r}")

    def test_idempotent_does_not_duplicate_hook(self):
        run_install_hook(self.settings_path)
        run_install_hook(self.settings_path)
        data = self._read_settings()
        hooks = self._claudecat_hooks(data)
        self.assertEqual(len(hooks), 1,
                         f"Expected exactly 1 claudecat hook, found {len(hooks)}: {hooks}")

    def test_preserves_existing_stop_hooks_from_other_tools(self):
        other_hook = {"matcher": "", "hooks": [{"type": "command", "command": "echo other-tool"}]}
        settings = {"hooks": {"Stop": [other_hook]}}
        with open(self.settings_path, 'w') as f:
            json.dump(settings, f)

        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, f"install-hook failed: {result.stderr}")

        data = self._read_settings()
        stop_hooks = data.get('hooks', {}).get('Stop', [])
        all_commands = [
            h.get('command', '')
            for entry in stop_hooks
            for h in entry.get('hooks', [])
        ]
        self.assertTrue(any('other-tool' in c for c in all_commands),
                        "Expected other-tool hook to be preserved")
        self.assertTrue(any('claudecat_hook.py' in c for c in all_commands),
                        "Expected claudecat hook to be added")

    def test_output_contains_installed_on_success(self):
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('installed', result.stdout.lower() + result.stderr.lower())

    def test_hook_command_contains_claudecat_hook_py(self):
        run_install_hook(self.settings_path)
        data = self._read_settings()
        hooks = self._claudecat_hooks(data)
        self.assertEqual(len(hooks), 1)
        self.assertIn('claudecat_hook.py', hooks[0])

    def test_preserves_non_hooks_keys_in_settings(self):
        settings = {"permissions": {"allow": ["Bash(git log)"]}, "theme": "dark"}
        with open(self.settings_path, 'w') as f:
            json.dump(settings, f)

        run_install_hook(self.settings_path)
        data = self._read_settings()
        self.assertEqual(data.get('theme'), 'dark')
        self.assertIn('permissions', data)


if __name__ == '__main__':
    unittest.main()
