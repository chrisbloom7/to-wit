# tests/helpers/claudecat_uninstall_hook_test.py
# Tests for libexec/claudecat/claudecat_uninstall_hook.py
#
# Run with: python3 tests/helpers/claudecat_uninstall_hook_test.py

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
UNINSTALL_HOOK_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_uninstall_hook.py')
SETTINGS_REL_PATH = os.path.join('.claude', 'settings.local.json')


def run_install_hook(home):
    env = {**os.environ, 'HOME': home}
    return subprocess.run(
        ['python3', INSTALL_HOOK_SCRIPT],
        env=env, capture_output=True, text=True
    )


def run_uninstall_hook(home):
    env = {**os.environ, 'HOME': home}
    return subprocess.run(
        ['python3', UNINSTALL_HOOK_SCRIPT],
        env=env, capture_output=True, text=True
    )


class TestClaudecatUninstallHook(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, SETTINGS_REL_PATH)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_settings(self):
        with open(self.settings_path) as f:
            return json.load(f)

    def _write_settings(self, data):
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        with open(self.settings_path, 'w') as f:
            json.dump(data, f)

    def test_noop_when_settings_file_does_not_exist(self):
        self.assertFalse(os.path.exists(self.settings_path))
        result = run_uninstall_hook(self.tmpdir)
        self.assertEqual(result.returncode, 0, f"uninstall-hook failed: {result.stderr}")
        self.assertFalse(os.path.exists(self.settings_path),
                         "Settings file should not be created by uninstall")

    def test_noop_when_hook_not_installed(self):
        self._write_settings({"permissions": {"allow": ["Bash(git status)"]}})
        result = run_uninstall_hook(self.tmpdir)
        self.assertEqual(result.returncode, 0, f"uninstall-hook failed: {result.stderr}")
        combined = result.stdout + result.stderr
        self.assertIn('not', combined.lower(),
                      f"Expected 'not installed' message, got: {combined!r}")

    def test_removes_hook_when_installed(self):
        run_install_hook(self.tmpdir)
        # Verify hook is present
        data = self._read_settings()
        stop_hooks = data.get('hooks', {}).get('Stop', [])
        self.assertTrue(len(stop_hooks) > 0, "Expected hook to be installed before uninstall test")

        result = run_uninstall_hook(self.tmpdir)
        self.assertEqual(result.returncode, 0, f"uninstall-hook failed: {result.stderr}")

        data = self._read_settings()
        stop_hooks = data.get('hooks', {}).get('Stop', [])
        # Flatten all commands
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
            f"Expected claudecat hook to be removed, but found: {all_commands}"
        )

    def test_does_not_remove_other_stop_hooks(self):
        other_hook = {"matcher": "", "hooks": [{"type": "command", "command": "echo other-tool"}]}
        self._write_settings({"hooks": {"Stop": [other_hook]}})
        run_install_hook(self.tmpdir)
        run_uninstall_hook(self.tmpdir)

        data = self._read_settings()
        stop_hooks = data.get('hooks', {}).get('Stop', [])
        all_commands = []
        for entry in stop_hooks:
            if isinstance(entry, dict):
                if 'command' in entry:
                    all_commands.append(entry['command'])
                for nested in entry.get('hooks', []):
                    if isinstance(nested, dict) and 'command' in nested:
                        all_commands.append(nested['command'])
        self.assertTrue(
            any('other-tool' in c for c in all_commands),
            f"Expected other-tool hook to remain after uninstall, got: {stop_hooks}"
        )

    def test_cleans_up_empty_hooks_stop_array(self):
        run_install_hook(self.tmpdir)
        data = self._read_settings()
        # Ensure only claudecat hook exists in Stop
        stop_hooks = data.get('hooks', {}).get('Stop', [])
        claudecat_only = [
            entry for entry in stop_hooks
            if isinstance(entry, dict) and (
                'claudecat_hook.py' in entry.get('command', '') or
                any('claudecat_hook.py' in n.get('command', '')
                    for n in entry.get('hooks', []) if isinstance(n, dict))
            )
        ]
        if len(stop_hooks) == len(claudecat_only):
            # Only claudecat hooks present — after uninstall, Stop should be empty or absent
            run_uninstall_hook(self.tmpdir)
            data = self._read_settings()
            stop_hooks_after = data.get('hooks', {}).get('Stop', [])
            self.assertEqual(stop_hooks_after, [],
                             f"Expected empty Stop array after removing only hook, got: {stop_hooks_after}")

    def test_cleans_up_empty_hooks_object(self):
        run_install_hook(self.tmpdir)
        data = self._read_settings()
        # Overwrite to ensure hooks only has Stop with claudecat entry
        stop_hooks = data.get('hooks', {}).get('Stop', [])
        claudecat_entries = [
            entry for entry in stop_hooks
            if isinstance(entry, dict) and (
                'claudecat_hook.py' in entry.get('command', '') or
                any('claudecat_hook.py' in n.get('command', '')
                    for n in entry.get('hooks', []) if isinstance(n, dict))
            )
        ]
        # Write a settings file where hooks only contains the claudecat Stop entry
        self._write_settings({"hooks": {"Stop": claudecat_entries}})
        run_uninstall_hook(self.tmpdir)

        data = self._read_settings()
        hooks = data.get('hooks', {})
        # hooks should be empty or absent after removing the only entry
        remaining_stop = hooks.get('Stop', [])
        self.assertEqual(remaining_stop, [],
                         f"Expected empty/absent hooks after full removal, got hooks: {hooks}")

    def test_preserves_other_top_level_settings_keys(self):
        self._write_settings({"permissions": {"allow": ["Bash(git log)"]}, "extra": "value"})
        run_install_hook(self.tmpdir)
        run_uninstall_hook(self.tmpdir)

        data = self._read_settings()
        self.assertEqual(data.get('extra'), 'value',
                         "Expected 'extra' key preserved after uninstall")
        self.assertEqual(data.get('permissions', {}).get('allow'), ["Bash(git log)"],
                         "Expected permissions.allow preserved after uninstall")


if __name__ == '__main__':
    unittest.main()
