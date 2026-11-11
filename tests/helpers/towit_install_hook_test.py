# Tests for libexec/towit/towit_install_hook.py
#
# Run with: python3 tests/helpers/towit_install_hook_test.py

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


def run_install_hook(settings_path):
    """Run towit_install_hook.py with an isolated settings path."""
    env = {**os.environ, 'TOWIT_SETTINGS_PATH': settings_path}
    return subprocess.run(
        ['python3', INSTALL_HOOK_SCRIPT],
        env=env, capture_output=True, text=True
    )


class TestTowitInstallHook(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.local.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_settings(self):
        with open(self.settings_path) as f:
            return json.load(f)

    def _towit_hooks(self, data):
        """Return list of To Wit hook command strings from settings data."""
        hooks = []
        for entry in data.get('hooks', {}).get('Stop', []):
            for hook in entry.get('hooks', []):
                if 'towit_hook.py' in hook.get('command', ''):
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
        hooks = self._towit_hooks(data)
        self.assertEqual(len(hooks), 1,
                         f"Expected exactly 1 To Wit hook, found {len(hooks)}: {hooks}")

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
        self.assertTrue(any('towit_hook.py' in c for c in all_commands),
                        "Expected To Wit hook to be added")

    def test_output_contains_installed_on_success(self):
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('installed', result.stdout.lower() + result.stderr.lower())

    def test_hook_command_contains_towit_hook_py(self):
        run_install_hook(self.settings_path)
        data = self._read_settings()
        hooks = self._towit_hooks(data)
        self.assertEqual(len(hooks), 1)
        self.assertIn('towit_hook.py', hooks[0])

    def test_preserves_non_hooks_keys_in_settings(self):
        settings = {"permissions": {"allow": ["Bash(git log)"]}, "theme": "dark"}
        with open(self.settings_path, 'w') as f:
            json.dump(settings, f)

        run_install_hook(self.settings_path)
        data = self._read_settings()
        self.assertEqual(data.get('theme'), 'dark')
        self.assertIn('permissions', data)


class TestInstallHookEvents(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.local.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read(self):
        with open(self.settings_path) as f:
            return json.load(f)

    def _towit_entries(self, data, event):
        return [(entry.get('matcher', ''), h['command'])
                for entry in data.get('hooks', {}).get(event, [])
                for h in entry.get('hooks', [])
                if 'towit_hook.py' in h.get('command', '')]

    def test_hook_events_constant(self):
        import towit_install_hook
        self.assertEqual(towit_install_hook.HOOK_EVENTS,
                         {'Stop': '', 'SessionEnd': '', 'SessionStart': 'startup'})

    def test_installs_one_entry_per_event_with_matcher(self):
        run_install_hook(self.settings_path)
        data = self._read()
        for event, matcher in {'Stop': '', 'SessionEnd': '', 'SessionStart': 'startup'}.items():
            entries = self._towit_entries(data, event)
            self.assertEqual(len(entries), 1, f"{event}: {entries}")
            self.assertEqual(entries[0][0], matcher)

    def test_rerun_leaves_one_entry_per_event(self):
        run_install_hook(self.settings_path)
        result = run_install_hook(self.settings_path)
        self.assertIn('already', (result.stdout + result.stderr).lower())
        data = self._read()
        for event in ('Stop', 'SessionEnd', 'SessionStart'):
            self.assertEqual(len(self._towit_entries(data, event)), 1)

    def test_upgrade_from_stop_only_adds_missing_events(self):
        stop_only = {"hooks": {"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "python3 /x/towit_hook.py"}]}]}}
        with open(self.settings_path, 'w') as f:
            json.dump(stop_only, f)
        run_install_hook(self.settings_path)
        data = self._read()
        for event in ('Stop', 'SessionEnd', 'SessionStart'):
            self.assertEqual(len(self._towit_entries(data, event)), 1, event)

    def test_preserves_unrelated_hooks_under_all_events(self):
        other = {"type": "command", "command": "echo other-tool"}
        settings = {"hooks": {
            "Stop": [{"matcher": "", "hooks": [other]}],
            "SessionStart": [{"matcher": "startup", "hooks": [other]},
                             {"matcher": "resume", "hooks": [other]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [other]}],
        }}
        with open(self.settings_path, 'w') as f:
            json.dump(settings, f)
        run_install_hook(self.settings_path)
        data = self._read()
        for event in ('Stop', 'SessionStart'):
            cmds = [h['command'] for e in data['hooks'][event] for h in e['hooks']]
            self.assertIn('echo other-tool', cmds)
        self.assertEqual(data['hooks']['PreToolUse'], settings['hooks']['PreToolUse'])
        resume = [e for e in data['hooks']['SessionStart'] if e['matcher'] == 'resume']
        self.assertEqual(resume, settings['hooks']['SessionStart'][1:])
        self.assertEqual(len(self._towit_entries(data, 'SessionStart')), 1)

    def test_write_is_atomic_via_os_replace(self):
        import towit_install_hook
        from unittest.mock import patch
        with patch.object(towit_install_hook, 'SETTINGS_PATH', self.settings_path), \
             patch('os.replace', side_effect=OSError('boom')) as rep:
            with self.assertRaises(OSError):
                towit_install_hook._save_settings({'a': 1})
        rep.assert_called_once()
        self.assertFalse(os.path.exists(self.settings_path))
        self.assertEqual([f for f in os.listdir(self.tmpdir) if f.endswith('.tmp')], [])


class TestInstallHookHelp(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.local.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_help_flag_exits_zero(self):
        env = {**os.environ, 'TOWIT_SETTINGS_PATH': self.settings_path}
        result = subprocess.run(
            ['python3', INSTALL_HOOK_SCRIPT, '--help'],
            env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0)

    def test_help_flag_prints_usage(self):
        env = {**os.environ, 'TOWIT_SETTINGS_PATH': self.settings_path}
        result = subprocess.run(
            ['python3', INSTALL_HOOK_SCRIPT, '--help'],
            env=env, capture_output=True, text=True
        )
        combined = result.stdout + result.stderr
        self.assertIn('usage', combined.lower())

    def test_help_flag_does_not_install_hook(self):
        env = {**os.environ, 'TOWIT_SETTINGS_PATH': self.settings_path}
        subprocess.run(
            ['python3', INSTALL_HOOK_SCRIPT, '--help'],
            env=env, capture_output=True, text=True
        )
        self.assertFalse(os.path.exists(self.settings_path),
                         "--help should not create or modify settings file")


REAL_HOOK_COMMAND = f"python3 {os.path.join(HELPERS_DIR, 'towit_hook.py')}"
ALL_EVENTS = {'Stop': '', 'SessionEnd': '', 'SessionStart': 'startup'}


def _stale_settings(command='python3 /old/clone/towit_hook.py', events=ALL_EVENTS):
    return {"hooks": {ev: [{"matcher": m, "hooks": [{"type": "command", "command": command}]}]
                      for ev, m in events.items()}}


class TestStableScriptPath(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_cellar(self, prefix, version='0.9.0', link=True):
        libexec = os.path.join(prefix, 'Cellar', 'towit', version, 'libexec', 'towit')
        os.makedirs(libexec)
        script = os.path.join(libexec, 'towit_hook.py')
        open(script, 'w').close()
        if link:
            os.makedirs(os.path.join(prefix, 'opt'))
            os.symlink(f'../Cellar/towit/{version}', os.path.join(prefix, 'opt', 'towit'))
        return script

    def test_cellar_path_rewritten_to_opt_when_opt_exists(self):
        from towit_install_hook import stable_script_path
        script = self._make_cellar(self.tmpdir)
        self.assertEqual(stable_script_path(script),
                         os.path.join(self.tmpdir, 'opt', 'towit', 'libexec', 'towit', 'towit_hook.py'))

    def test_cellar_path_unchanged_when_opt_missing(self):
        from towit_install_hook import stable_script_path
        script = self._make_cellar(self.tmpdir, link=False)
        self.assertEqual(stable_script_path(script), script)

    def test_non_cellar_path_unchanged(self):
        from towit_install_hook import stable_script_path
        clone = os.path.join(self.tmpdir, 'clone', 'libexec', 'towit', 'towit_hook.py')
        os.makedirs(os.path.dirname(clone))
        open(clone, 'w').close()
        self.assertEqual(stable_script_path(clone), clone)

    def test_works_for_two_different_prefixes(self):
        from towit_install_hook import stable_script_path
        for name, version in (('arm', '0.9.0'), ('intel', '1.2.3')):
            prefix = os.path.join(self.tmpdir, name)
            script = self._make_cellar(prefix, version)
            self.assertEqual(
                stable_script_path(script),
                os.path.join(prefix, 'opt', 'towit', 'libexec', 'towit', 'towit_hook.py'), name)


class TestFakeHomebrewLayout(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _install_version(self, version):
        """Copy libexec/towit into Cellar/towit/<version> and repoint opt/towit at it."""
        dest = os.path.join(self.tmpdir, 'Cellar', 'towit', version, 'libexec', 'towit')
        shutil.copytree(HELPERS_DIR, dest, ignore=shutil.ignore_patterns('__pycache__'))
        opt = os.path.join(self.tmpdir, 'opt')
        os.makedirs(opt, exist_ok=True)
        link = os.path.join(opt, 'towit')
        if os.path.islink(link):
            os.unlink(link)
        os.symlink(f'../Cellar/towit/{version}', link)
        return os.path.join(dest, 'towit_install_hook.py')

    def _run(self, script):
        env = {**os.environ, 'TOWIT_SETTINGS_PATH': self.settings_path}
        return subprocess.run(['python3', script], env=env, capture_output=True, text=True)

    def _commands(self):
        with open(self.settings_path) as f:
            data = json.load(f)
        return {ev: [h['command'] for e in data['hooks'][ev] for h in e['hooks']]
                for ev in ALL_EVENTS}

    def test_installs_version_independent_opt_path_and_survives_upgrade(self):
        script_090 = self._install_version('0.9.0')
        result = self._run(script_090)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = f"python3 {self.tmpdir}/opt/towit/libexec/towit/towit_hook.py"
        for ev, cmds in self._commands().items():
            self.assertEqual(cmds, [expected], ev)
            self.assertNotIn('Cellar', cmds[0])
            self.assertNotIn('0.9.0', cmds[0])

        with open(self.settings_path, 'rb') as f:
            before = f.read()

        # Simulate `brew upgrade`: new keg, opt symlink repointed, old keg removed.
        script_091 = self._install_version('0.9.1')
        shutil.rmtree(os.path.join(self.tmpdir, 'Cellar', 'towit', '0.9.0'))
        result = self._run(script_091)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already installed', (result.stdout + result.stderr).lower())
        with open(self.settings_path, 'rb') as f:
            self.assertEqual(f.read(), before)


def _make_stub_python(directory, name='stub-python'):
    """Create an executable file (not a real interpreter) and return its path."""
    path = os.path.join(directory, name)
    with open(path, 'w') as f:
        f.write('#!/bin/sh\nexit 0\n')
    os.chmod(path, 0o755)
    return path


class TestHookInterpreter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.json')
        self.stub = _make_stub_python(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _interp(self, env):
        import contextlib
        import io
        from towit_install_hook import hook_interpreter
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            value = hook_interpreter(env)
        return value, err.getvalue()

    def test_valid_absolute_executable_is_returned_without_warning(self):
        value, err = self._interp({'TOWIT_PYTHON': self.stub})
        self.assertEqual(value, self.stub)
        self.assertEqual(err, '')

    def test_unset_returns_python3_without_warning(self):
        value, err = self._interp({})
        self.assertEqual(value, 'python3')
        self.assertEqual(err, '')

    def test_reads_os_environ_when_env_is_none(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'TOWIT_PYTHON': self.stub}):
            value, _ = self._interp(None)
        self.assertEqual(value, self.stub)

    def test_relative_path_is_ignored_with_warning(self):
        value, err = self._interp({'TOWIT_PYTHON': 'bin/python3'})
        self.assertEqual(value, 'python3')
        self.assertIn('TOWIT_PYTHON', err)

    def test_missing_path_is_ignored_with_warning(self):
        value, err = self._interp({'TOWIT_PYTHON': os.path.join(self.tmpdir, 'nope')})
        self.assertEqual(value, 'python3')
        self.assertIn('TOWIT_PYTHON', err)

    def test_non_executable_file_is_ignored_with_warning(self):
        plain = os.path.join(self.tmpdir, 'plain-file')
        open(plain, 'w').close()
        os.chmod(plain, 0o644)
        value, err = self._interp({'TOWIT_PYTHON': plain})
        self.assertEqual(value, 'python3')
        self.assertIn('TOWIT_PYTHON', err)

    def test_absolute_executable_path_with_whitespace_is_accepted_without_warning(self):
        spaced_dir = os.path.join(self.tmpdir, 'with space')
        os.makedirs(spaced_dir)
        spaced = _make_stub_python(spaced_dir)
        value, err = self._interp({'TOWIT_PYTHON': spaced})
        self.assertEqual(value, spaced)
        self.assertEqual(err, '')

    def test_relative_path_with_whitespace_is_still_rejected(self):
        value, err = self._interp({'TOWIT_PYTHON': 'with space/python3'})
        self.assertEqual(value, 'python3')
        self.assertIn('TOWIT_PYTHON', err)

    def test_non_executable_path_with_whitespace_is_still_rejected(self):
        spaced_dir = os.path.join(self.tmpdir, 'with space')
        os.makedirs(spaced_dir)
        plain = os.path.join(spaced_dir, 'plain-file')
        open(plain, 'w').close()
        os.chmod(plain, 0o644)
        value, err = self._interp({'TOWIT_PYTHON': plain})
        self.assertEqual(value, 'python3')
        self.assertIn('TOWIT_PYTHON', err)

    def test_importing_module_with_invalid_towit_python_does_not_warn(self):
        env = {**os.environ, 'TOWIT_PYTHON': 'relative/python'}
        result = subprocess.run(
            ['python3', '-c', f"import sys; sys.path.insert(0, {HELPERS_DIR!r}); import towit_install_hook"],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def _run(self, **extra_env):
        env = {k: v for k, v in os.environ.items() if k != 'TOWIT_PYTHON'}
        env.update({'TOWIT_SETTINGS_PATH': self.settings_path}, **extra_env)
        return subprocess.run(['python3', INSTALL_HOOK_SCRIPT], env=env,
                              capture_output=True, text=True)

    def _commands(self):
        with open(self.settings_path) as f:
            data = json.load(f)
        return {ev: [h['command'] for e in data['hooks'][ev] for h in e['hooks']]
                for ev in ALL_EVENTS}

    def test_install_with_towit_python_writes_that_interpreter(self):
        result = self._run(TOWIT_PYTHON=self.stub)
        self.assertEqual(result.returncode, 0, result.stderr)
        for ev, cmds in self._commands().items():
            self.assertEqual(len(cmds), 1, ev)
            self.assertTrue(cmds[0].startswith(f'{self.stub} '), f'{ev}: {cmds[0]}')
            self.assertTrue(cmds[0].endswith('towit_hook.py'), f'{ev}: {cmds[0]}')

    def test_install_with_invalid_towit_python_falls_back_and_warns(self):
        result = self._run(TOWIT_PYTHON='relative/python')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('TOWIT_PYTHON', result.stderr)
        for ev, cmds in self._commands().items():
            self.assertTrue(cmds[0].startswith('python3 '), f'{ev}: {cmds[0]}')

    def test_rerun_with_towit_python_repairs_plain_python3_commands(self):
        self.assertEqual(self._run().returncode, 0)
        result = self._run(TOWIT_PYTHON=self.stub)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('updated', result.stdout.lower())
        for ev, cmds in self._commands().items():
            self.assertTrue(cmds[0].startswith(f'{self.stub} '), f'{ev}: {cmds[0]}')

    def test_rerun_without_towit_python_repairs_back_to_python3(self):
        self.assertEqual(self._run(TOWIT_PYTHON=self.stub).returncode, 0)
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('updated', result.stdout.lower())
        for ev, cmds in self._commands().items():
            self.assertTrue(cmds[0].startswith('python3 '), f'{ev}: {cmds[0]}')
            self.assertNotIn(self.stub, cmds[0])


class TestInstallHookRepair(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, data):
        with open(self.settings_path, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')

    def _read(self):
        with open(self.settings_path) as f:
            return json.load(f)

    def _bytes(self):
        with open(self.settings_path, 'rb') as f:
            return f.read()

    def test_stale_commands_are_rewritten_and_matchers_preserved(self):
        self._write(_stale_settings())
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('updated', (result.stdout + result.stderr).lower())
        data = self._read()
        for ev, matcher in ALL_EVENTS.items():
            entries = data['hooks'][ev]
            self.assertEqual(len(entries), 1, ev)
            self.assertEqual(entries[0]['matcher'], matcher, ev)
            self.assertEqual([h['command'] for h in entries[0]['hooks']], [REAL_HOOK_COMMAND], ev)

    def test_repair_leaves_sibling_hooks_and_other_keys_untouched_in_order(self):
        other = {"type": "command", "command": "echo other"}
        settings = {
            "theme": "dark",
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [dict(other)]}],
                "Stop": [{"matcher": "", "hooks": [
                    dict(other),
                    {"type": "command", "command": "python3 /old/clone/towit_hook.py"},
                    {"type": "command", "command": "echo after"}]}],
                "SessionEnd": [{"matcher": "", "hooks": [
                    {"type": "command", "command": "python3 /old/clone/towit_hook.py"}]}],
                "SessionStart": [{"matcher": "startup", "hooks": [
                    dict(other),
                    {"type": "command", "command": "python3 /old/clone/towit_hook.py"}]}],
            },
            "permissions": {"allow": ["Bash(git status)"]},
        }
        self._write(settings)
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, result.stderr)

        expected = json.loads(json.dumps(settings))
        for entries in expected['hooks'].values():
            for entry in entries:
                for hook in entry['hooks']:
                    if 'towit_hook.py' in hook['command']:
                        hook['command'] = REAL_HOOK_COMMAND
        # json.dumps without sort_keys compares key order as well as content.
        self.assertEqual(json.dumps(self._read(), indent=2), json.dumps(expected, indent=2))

    def test_partial_install_with_stale_stop_repairs_and_adds_missing_events(self):
        self._write(_stale_settings(events={'Stop': ''}))
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self._read()
        for ev, matcher in ALL_EVENTS.items():
            cmds = [(e['matcher'], h['command']) for e in data['hooks'][ev] for h in e['hooks']]
            self.assertEqual(cmds, [(matcher, REAL_HOOK_COMMAND)], ev)

    def test_rerun_after_repair_is_noop(self):
        self._write(_stale_settings())
        run_install_hook(self.settings_path)
        for ev in ALL_EVENTS:  # guard: the first run must actually have repaired
            self.assertEqual(self._read()['hooks'][ev][0]['hooks'][0]['command'],
                             REAL_HOOK_COMMAND, ev)
        before = self._bytes()
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already installed', (result.stdout + result.stderr).lower())
        self.assertEqual(self._bytes(), before)

    def test_two_towit_entries_one_stale_one_current_all_end_current(self):
        other = {"type": "command", "command": "echo other"}
        stale = {"type": "command", "command": "python3 /old/clone/towit_hook.py"}
        current = {"type": "command", "command": REAL_HOOK_COMMAND}
        settings = _stale_settings()
        # Stop: stale + current in the same entry; SessionEnd: split across two entries.
        settings['hooks']['Stop'][0]['hooks'] = [dict(stale), dict(other), dict(current)]
        settings['hooks']['SessionEnd'] = [
            {"matcher": "", "hooks": [dict(current)]},
            {"matcher": "", "hooks": [dict(stale)]},
        ]
        self._write(settings)
        result = run_install_hook(self.settings_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('updated', (result.stdout + result.stderr).lower())
        data = self._read()
        stop = [h['command'] for e in data['hooks']['Stop'] for h in e['hooks']]
        self.assertEqual(stop, [REAL_HOOK_COMMAND, 'echo other', REAL_HOOK_COMMAND])
        end = [[h['command'] for h in e['hooks']] for e in data['hooks']['SessionEnd']]
        self.assertEqual(end, [[REAL_HOOK_COMMAND], [REAL_HOOK_COMMAND]])
        start = [h['command'] for e in data['hooks']['SessionStart'] for h in e['hooks']]
        self.assertEqual(start, [REAL_HOOK_COMMAND])


class TestHookCommandQuoting(unittest.TestCase):
    """hook_command() must survive a shell split even when paths contain odd characters."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _command(self, script, env=None):
        import contextlib
        import io
        from unittest.mock import patch
        import towit_install_hook
        with patch.object(towit_install_hook, 'HOOK_SCRIPT', script), \
                patch.dict(os.environ, env or {}), \
                contextlib.redirect_stderr(io.StringIO()):
            if not env:
                os.environ.pop('TOWIT_PYTHON', None)
            return towit_install_hook.hook_command()

    def _assert_roundtrip(self, script):
        import shlex
        command = self._command(script)
        try:
            words = shlex.split(command)
        except ValueError as e:
            self.fail(f'command is not shell-parseable ({e}): {command}')
        self.assertEqual(words, ['python3', script])

    def test_script_path_with_space_roundtrips(self):
        self._assert_roundtrip('/opt/My Apps/towit/libexec/towit/towit_hook.py')

    def test_script_path_with_single_quote_roundtrips(self):
        self._assert_roundtrip("/opt/it's here/towit/libexec/towit/towit_hook.py")

    def test_script_path_with_shell_metacharacters_roundtrips(self):
        self._assert_roundtrip('/opt/$(touch x)/`id`;&|<>*/towit_hook.py')

    def test_metacharacters_are_not_executed_by_the_shell(self):
        marker = os.path.join(self.tmpdir, 'pwned')
        script = f'/opt/$(touch {marker})/towit_hook.py'
        quoted_script = self._command(script).split(' ', 1)[1]
        result = subprocess.run(['sh', '-c', 'printf "%s\\n" ' + quoted_script],
                                capture_output=True, text=True)
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(result.stdout.strip(), script)

    def test_normal_homebrew_path_is_unchanged_and_unquoted(self):
        script = '/opt/homebrew/opt/towit/libexec/libexec/towit/towit_hook.py'
        interp = '/opt/homebrew/opt/python@3.15/bin/python3.15'
        cmd = self._command(script, {'TOWIT_PYTHON': interp}) if os.path.isfile(interp) else None
        if cmd is None:
            from unittest.mock import patch
            import towit_install_hook
            with patch.object(towit_install_hook, 'HOOK_SCRIPT', script), \
                    patch.object(towit_install_hook, 'hook_interpreter', return_value=interp):
                cmd = towit_install_hook.hook_command()
        self.assertEqual(cmd, f'{interp} {script}')
        self.assertNotIn("'", cmd)
        self.assertNotIn('"', cmd)

    def test_towit_python_with_space_is_accepted_and_quoted(self):
        import shlex
        spaced_dir = os.path.join(self.tmpdir, 'with space')
        os.makedirs(spaced_dir)
        stub = _make_stub_python(spaced_dir)
        script = '/opt/towit/towit_hook.py'
        cmd = self._command(script, {'TOWIT_PYTHON': stub})
        self.assertEqual(shlex.split(cmd), [stub, script])

    def test_relative_towit_python_still_falls_back_to_python3(self):
        script = '/opt/towit/towit_hook.py'
        cmd = self._command(script, {'TOWIT_PYTHON': 'rel/python3'})
        self.assertEqual(cmd, f'python3 {script}')

    def test_install_hook_writes_quoted_command_for_spaced_script_path(self):
        import shlex
        settings_path = os.path.join(self.tmpdir, 'settings.json')
        spaced = os.path.join(self.tmpdir, 'with space')
        shutil.copytree(HELPERS_DIR, os.path.join(spaced, 'towit'),
                        ignore=shutil.ignore_patterns('__pycache__'))
        script = os.path.join(spaced, 'towit', 'towit_install_hook.py')
        env = {k: v for k, v in os.environ.items() if k != 'TOWIT_PYTHON'}
        env['TOWIT_SETTINGS_PATH'] = settings_path
        result = subprocess.run(['python3', script], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(settings_path) as f:
            data = json.load(f)
        command = data['hooks']['Stop'][0]['hooks'][0]['command']
        self.assertEqual(shlex.split(command),
                         ['python3', os.path.join(spaced, 'towit', 'towit_hook.py')],
                         command)


class TestRepairQuoting(unittest.TestCase):
    def _settings(self, command):
        return {'hooks': {ev: [{'matcher': m, 'hooks': [{'type': 'command', 'command': command}]}]
                          for ev, m in {'Stop': '', 'SessionEnd': '', 'SessionStart': 'startup'}.items()}}

    def test_old_unquoted_command_with_space_is_rewritten_to_quoted_form_idempotently(self):
        import shlex
        from unittest.mock import patch
        import towit_install_hook
        script = '/opt/My Apps/towit/towit_hook.py'
        settings = self._settings(f'python3 {script}')
        with patch.object(towit_install_hook, 'HOOK_SCRIPT', script), \
                patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_PYTHON', None)
            self.assertEqual(towit_install_hook.repair_commands(settings), 3)
            for ev in towit_install_hook.HOOK_EVENTS:
                cmd = settings['hooks'][ev][0]['hooks'][0]['command']
                self.assertEqual(shlex.split(cmd), ['python3', script])
                self.assertNotEqual(cmd, f'python3 {script}')
            self.assertEqual(towit_install_hook.repair_commands(settings), 0)


if __name__ == '__main__':
    unittest.main()
