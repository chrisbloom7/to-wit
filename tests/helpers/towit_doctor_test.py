# tests/helpers/towit_doctor_test.py
import unittest
import sys, os
import tempfile
import shutil
from unittest.mock import patch
from collections import namedtuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit')))
from towit_doctor import CheckResult, format_result, summarise, check_python_version, check_claude_cli

class TestCheckResult(unittest.TestCase):
    def test_pass_has_no_remediation_line(self):
        r = CheckResult('PASS', 'Something works')
        lines = format_result(r)
        self.assertEqual(lines, ['[PASS] Something works'])

    def test_warn_includes_remediation_indented(self):
        r = CheckResult('WARN', 'Something is off', remediation='Fix it with foo')
        lines = format_result(r)
        self.assertEqual(lines, ['[WARN] Something is off', "       → Fix it with foo"])

    def test_fail_includes_remediation_indented(self):
        r = CheckResult('FAIL', 'Something is broken', remediation='Run bar')
        lines = format_result(r)
        self.assertEqual(lines, ['[FAIL] Something is broken', "       → Run bar"])

    def test_summarise_all_pass(self):
        results = [CheckResult('PASS', 'a'), CheckResult('PASS', 'b')]
        msg, code = summarise(results)
        self.assertEqual(msg, 'All checks passed.')
        self.assertEqual(code, 0)

    def test_summarise_with_warn_only(self):
        results = [CheckResult('PASS', 'a'), CheckResult('WARN', 'b')]
        msg, code = summarise(results)
        self.assertIn('1 warning(s)', msg)
        self.assertIn('0 failure(s)', msg)
        self.assertEqual(code, 0)

    def test_summarise_with_fail(self):
        results = [CheckResult('WARN', 'a'), CheckResult('FAIL', 'b')]
        msg, code = summarise(results)
        self.assertIn('1 warning(s)', msg)
        self.assertIn('1 failure(s)', msg)
        self.assertEqual(code, 1)


class TestChecks(unittest.TestCase):
    def test_python_version_pass_on_current_interpreter(self):
        # This test runs on Python 3.11+, so it must pass
        result = check_python_version()
        self.assertEqual(result.status, 'PASS')
        self.assertIn('3.', result.label)

    def test_python_version_fail_below_311(self):
        # Create a namedtuple to properly mock sys.version_info
        VersionInfo = namedtuple('VersionInfo', ['major', 'minor', 'micro', 'releaselevel', 'serial'])
        mock_version = VersionInfo(major=3, minor=10, micro=0, releaselevel='final', serial=0)
        with patch('towit_doctor.sys.version_info', mock_version):
            result = check_python_version()
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('3.10', result.label)
        self.assertIn('towit setup', result.remediation)

    def test_claude_cli_pass_when_found(self):
        with patch('shutil.which', return_value='/usr/local/bin/claude'):
            result = check_claude_cli()
        self.assertEqual(result.status, 'PASS')
        self.assertIn('/usr/local/bin/claude', result.label)

    def test_claude_cli_fail_when_not_found(self):
        with patch('shutil.which', return_value=None):
            result = check_claude_cli()
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('not found', result.label)
        self.assertTrue(result.remediation)


class TestConfigChecks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _config_path(self, content=None):
        p = os.path.join(self.tmpdir, 'config.toml')
        if content is not None:
            with open(p, 'w') as f:
                f.write(content)
        return p

    def test_config_missing_is_warn(self):
        from towit_doctor import check_config_file
        result = check_config_file(os.path.join(self.tmpdir, 'nonexistent.toml'))
        self.assertEqual(result.status, 'WARN')
        self.assertIn('not found', result.label)
        self.assertIn('towit setup --config', result.remediation)

    def test_config_present_is_pass(self):
        from towit_doctor import check_config_file
        p = self._config_path('[database]\npath = "/tmp/x.db"\n')
        result = check_config_file(p)
        self.assertEqual(result.status, 'PASS')
        self.assertIn(p, result.label)

    def test_config_invalid_toml_is_fail(self):
        from towit_doctor import check_config_file
        p = self._config_path('not valid toml ][')
        result = check_config_file(p)
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('invalid TOML', result.label)
        self.assertTrue(result.remediation)

    def test_unknown_keys_is_warn(self):
        from towit_doctor import check_config_unknown_keys
        p = self._config_path('[unknownsection]\nfoo = 1\n')
        result = check_config_unknown_keys(p)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('unknown', result.label.lower())

    def test_known_keys_only_is_pass(self):
        from towit_doctor import check_config_unknown_keys
        p = self._config_path('[database]\npath = "/tmp/x.db"\n')
        result = check_config_unknown_keys(p)
        self.assertEqual(result.status, 'PASS')

    def test_deprecated_env_var_is_warn(self):
        from towit_doctor import check_deprecated_env
        with patch.dict(os.environ, {'TOWIT_DB_PATH': '/tmp/x.db'}):
            result = check_deprecated_env()
        self.assertEqual(result.status, 'WARN')
        self.assertIn('TOWIT_DB_PATH', result.label)

    def test_no_deprecated_env_var_is_pass(self):
        from towit_doctor import check_deprecated_env
        env = {k: v for k, v in os.environ.items() if k != 'TOWIT_DB_PATH'}
        with patch.dict(os.environ, env, clear=True):
            result = check_deprecated_env()
        self.assertEqual(result.status, 'PASS')

if __name__ == '__main__':
    unittest.main()
