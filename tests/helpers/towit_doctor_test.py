# tests/helpers/towit_doctor_test.py
import unittest
import sys, os
from unittest.mock import patch, MagicMock
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

if __name__ == '__main__':
    unittest.main()
