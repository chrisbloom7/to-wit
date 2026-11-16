# tests/helpers/towit_skill_test.py
"""Unit tests for towit_skill: installing, removing and checking the Claude Code plugin."""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
os.environ.setdefault('TOWIT_CONFIG_PATH', '/nonexistent/towit-config.toml')

import towit_skill  # noqa: E402

SOURCE = 'chrisbloom7/to-wit'


class FakeClaude:
    """Stands in for `claude plugin ...`: tracks marketplaces and installed plugins."""

    def __init__(self, marketplaces=None, plugins=None, fail_add=None):
        self.marketplaces = list(marketplaces or [])
        self.plugins = list(plugins or [])
        self.fail_add = fail_add
        self.calls = []

    def __call__(self, argv, **kwargs):
        assert isinstance(argv, list), "claude must be called in list form"
        assert not kwargs.get('shell'), "never shell=True"
        args = argv[2:]
        self.calls.append(args)
        head = args[:2]
        if head == ['marketplace', 'list']:
            return self._ok(json.dumps(self.marketplaces))
        if head == ['plugin', 'list'] or args[:1] == ['list']:
            return self._ok(json.dumps([{'id': p, 'scope': 'user'} for p in self.plugins]))
        if head == ['marketplace', 'add']:
            if self.fail_add:
                return self._fail({'outcome': 'failed', 'message': self.fail_add})
            source, _, ref = args[2].partition('#')
            self.marketplaces = [m for m in self.marketplaces if m['name'] != 'to-wit']
            self.marketplaces.append({'name': 'to-wit', 'source': 'github', 'repo': source, 'ref': ref})
            return self._ok(json.dumps({'outcome': 'ok'}))
        if head == ['marketplace', 'remove']:
            if not any(m['name'] == args[2] for m in self.marketplaces):
                return self._fail({'outcome': 'failed', 'message': 'Marketplace not found'})
            self.marketplaces = [m for m in self.marketplaces if m['name'] != args[2]]
            self.plugins = [p for p in self.plugins if not p.endswith('@' + args[2])]
            return self._ok(json.dumps({'outcome': 'ok'}))
        if args[0] == 'install':
            if args[1] not in self.plugins:  # the real install is idempotent
                self.plugins.append(args[1])
            return self._ok(json.dumps({'outcome': 'ok'}))
        if args[0] == 'uninstall':
            if args[1] not in self.plugins:
                return self._fail({'outcome': 'failed', 'failureCode': 'not_installed',
                                   'message': 'not found in installed plugins'})
            self.plugins.remove(args[1])
            return self._ok(json.dumps({'outcome': 'ok'}))
        raise AssertionError(f"unexpected claude call: {args}")

    @staticmethod
    def _ok(stdout):
        return subprocess.CompletedProcess([], 0, stdout=stdout + '\n', stderr='')

    @staticmethod
    def _fail(payload):
        return subprocess.CompletedProcess([], 1, stdout=json.dumps(payload) + '\n', stderr='')

    def verbs(self):
        return [' '.join(c[:2]) if c[0] == 'marketplace' else c[0] for c in self.calls]


def pinned(ref, repo=SOURCE):
    return {'name': 'to-wit', 'source': 'github', 'repo': repo, 'ref': ref}


class SkillTestCase(unittest.TestCase):
    def run_with(self, fake, func, *args, which='/usr/local/bin/claude'):
        with patch('shutil.which', return_value=which), \
                patch('subprocess.run', side_effect=fake):
            return func(*args)


class TestInstall(SkillTestCase):
    def test_fresh_install_adds_pinned_marketplace_then_plugin(self):
        fake = FakeClaude()
        self.run_with(fake, towit_skill.install, '0.12.0')
        self.assertIn(['marketplace', 'add', f'{SOURCE}#v0.12.0', '--scope', 'user', '--json'], fake.calls)
        self.assertIn(['install', 'towit@to-wit', '--scope', 'user', '--json'], fake.calls)
        self.assertLess(fake.verbs().index('marketplace add'), fake.verbs().index('install'))
        self.assertEqual(fake.plugins, ['towit@to-wit'])

    def test_rerun_at_same_version_does_not_touch_the_marketplace(self):
        fake = FakeClaude(marketplaces=[pinned('v0.12.0')], plugins=['towit@to-wit'])
        self.run_with(fake, towit_skill.install, '0.12.0')
        self.assertNotIn('marketplace add', fake.verbs())
        self.assertNotIn('marketplace remove', fake.verbs())
        self.assertEqual(fake.plugins, ['towit@to-wit'])

    def test_different_ref_is_repinned_and_plugin_reinstalled(self):
        fake = FakeClaude(marketplaces=[pinned('v0.11.1')], plugins=['towit@to-wit'])
        self.run_with(fake, towit_skill.install, '0.12.0')
        verbs = fake.verbs()
        self.assertLess(verbs.index('marketplace remove'), verbs.index('marketplace add'))
        self.assertEqual(fake.marketplaces[0]['ref'], 'v0.12.0')
        self.assertEqual(fake.plugins, ['towit@to-wit'])

    def test_unpinned_marketplace_is_repinned(self):
        fake = FakeClaude(marketplaces=[{'name': 'to-wit', 'source': 'github', 'repo': SOURCE}])
        self.run_with(fake, towit_skill.install, '0.12.0')
        self.assertEqual(fake.marketplaces[0]['ref'], 'v0.12.0')

    def test_marketplace_with_a_different_source_is_replaced(self):
        fake = FakeClaude(marketplaces=[{'name': 'to-wit', 'source': 'directory', 'path': '/x'}])
        self.run_with(fake, towit_skill.install, '0.12.0')
        self.assertEqual(fake.marketplaces[0]['repo'], SOURCE)

    def test_missing_claude_raises(self):
        with self.assertRaisesRegex(towit_skill.SkillError, 'claude CLI not found'):
            self.run_with(FakeClaude(), towit_skill.install, '0.12.0', which=None)

    def test_add_failure_surfaces_the_message(self):
        fake = FakeClaude(fail_add='Clone failed: ref v9.9.9 not found')
        with self.assertRaisesRegex(towit_skill.SkillError, 'v9.9.9 not found'):
            self.run_with(fake, towit_skill.install, '9.9.9')
        self.assertNotIn('install', fake.verbs())

    def test_version_is_validated_before_anything_runs(self):
        fake = FakeClaude()
        for bad in ('', 'v1.2.3', '1.2', '1.2.3; rm -rf /', '--flag', 'unknown'):
            with self.assertRaises(towit_skill.SkillError, msg=bad):
                self.run_with(fake, towit_skill.install, bad)
        self.assertEqual(fake.calls, [])


class TestUninstall(SkillTestCase):
    def test_removes_plugin_then_marketplace(self):
        fake = FakeClaude(marketplaces=[pinned('v0.12.0')], plugins=['towit@to-wit'])
        self.assertTrue(self.run_with(fake, towit_skill.uninstall))
        self.assertEqual(fake.plugins, [])
        self.assertEqual(fake.marketplaces, [])
        self.assertIn(['marketplace', 'remove', 'to-wit', '--scope', 'user', '--json'], fake.calls)

    def test_nothing_installed_is_not_an_error(self):
        fake = FakeClaude()
        self.assertFalse(self.run_with(fake, towit_skill.uninstall))

    def test_missing_claude_is_quietly_skipped(self):
        self.assertFalse(self.run_with(FakeClaude(), towit_skill.uninstall, which=None))


class TestStatus(SkillTestCase):
    def test_unavailable_without_claude(self):
        self.assertEqual(self.run_with(FakeClaude(), towit_skill.status, '0.12.0', which=None)[0],
                         'unavailable')

    def test_missing_when_plugin_not_installed(self):
        self.assertEqual(self.run_with(FakeClaude(), towit_skill.status, '0.12.0')[0], 'missing')

    def test_missing_when_marketplace_exists_but_plugin_does_not(self):
        fake = FakeClaude(marketplaces=[pinned('v0.12.0')])
        self.assertEqual(self.run_with(fake, towit_skill.status, '0.12.0')[0], 'missing')

    def test_ok_when_installed_at_the_cli_version(self):
        fake = FakeClaude(marketplaces=[pinned('v0.12.0')], plugins=['towit@to-wit'])
        self.assertEqual(self.run_with(fake, towit_skill.status, '0.12.0')[0], 'ok')

    def test_stale_when_pinned_to_another_version(self):
        fake = FakeClaude(marketplaces=[pinned('v0.11.1')], plugins=['towit@to-wit'])
        state, detail = self.run_with(fake, towit_skill.status, '0.12.0')
        self.assertEqual(state, 'stale')
        self.assertIn('v0.11.1', detail)

    def test_stale_when_unpinned(self):
        fake = FakeClaude(marketplaces=[{'name': 'to-wit', 'source': 'github', 'repo': SOURCE}],
                          plugins=['towit@to-wit'])
        self.assertEqual(self.run_with(fake, towit_skill.status, '0.12.0')[0], 'stale')


class TestPresent(SkillTestCase):
    def test_false_without_claude(self):
        self.assertFalse(self.run_with(FakeClaude(), towit_skill.present, which=None))

    def test_false_when_nothing_is_installed(self):
        self.assertFalse(self.run_with(FakeClaude(), towit_skill.present))

    def test_true_when_the_plugin_is_installed(self):
        fake = FakeClaude(marketplaces=[pinned('v0.12.0')], plugins=['towit@to-wit'])
        self.assertTrue(self.run_with(fake, towit_skill.present))

    def test_true_for_a_marketplace_left_without_its_plugin(self):
        fake = FakeClaude(marketplaces=[pinned('v0.12.0')])
        self.assertTrue(self.run_with(fake, towit_skill.present))


class TestMain(SkillTestCase):
    """The `install` / `uninstall` entry points that bin/towit and implode call."""

    def run_main(self, fake, argv, version='0.12.0', which='/usr/local/bin/claude'):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(towit_skill, 'installed_version', return_value=version), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.run_with(fake, towit_skill.main, argv, which=which)
        return code, out.getvalue(), err.getvalue()

    def test_install_reports_the_pinned_version(self):
        fake = FakeClaude()
        code, out, _ = self.run_main(fake, ['install'])
        self.assertEqual(code, 0)
        self.assertIn('v0.12.0', out)
        self.assertEqual(fake.plugins, ['towit@to-wit'])

    def test_install_failure_prints_the_error_and_returns_1(self):
        code, out, err = self.run_main(FakeClaude(fail_add='Clone failed'), ['install'])
        self.assertEqual(code, 1)
        self.assertIn('Clone failed', err)

    def test_install_without_claude_returns_1(self):
        code, _, err = self.run_main(FakeClaude(), ['install'], which=None)
        self.assertEqual(code, 1)
        self.assertIn('claude CLI not found', err)

    def test_install_with_unreadable_version_returns_1(self):
        code, _, err = self.run_main(FakeClaude(), ['install'], version=None)
        self.assertEqual(code, 1)
        self.assertIn('version', err)

    def test_uninstall_reports_what_it_did(self):
        fake = FakeClaude(marketplaces=[pinned('v0.12.0')], plugins=['towit@to-wit'])
        code, out, _ = self.run_main(fake, ['uninstall'])
        self.assertEqual(code, 0)
        self.assertIn('removed', out.lower())

    def test_uninstall_when_absent_is_quiet_success(self):
        code, out, err = self.run_main(FakeClaude(), ['uninstall'])
        self.assertEqual((code, err), (0, ''))
        self.assertIn('not installed', out.lower())

    def test_unknown_command_returns_2(self):
        code, _, err = self.run_main(FakeClaude(), ['frobnicate'])
        self.assertEqual(code, 2)
        self.assertIn('usage', err.lower())


if __name__ == '__main__':
    unittest.main()
