# tests/helpers/towit_doctor_test.py
import unittest
import sys, os
import tempfile
import shutil
import sqlite3
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


class TestDatabaseChecks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_db(self, tables=True):
        conn = sqlite3.connect(self.db_path)
        if tables:
            conn.executescript("""
                CREATE TABLE conversations (id TEXT PRIMARY KEY, folder TEXT NOT NULL,
                    cwd TEXT, started_at TEXT, last_active TEXT, title TEXT, summary TEXT,
                    message_count INTEGER, indexed_at TEXT NOT NULL DEFAULT (datetime('now')));
                CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_topics (
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    PRIMARY KEY (conversation_id, topic_id));
                CREATE TABLE keywords (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_keywords (
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
                    PRIMARY KEY (conversation_id, keyword_id));
            """)
        conn.commit()
        conn.close()

    def test_db_missing_is_fail(self):
        from towit_doctor import check_db_exists
        result = check_db_exists('/tmp/does_not_exist_towit.db')
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('not found', result.label)
        self.assertIn('towit setup', result.remediation)

    def test_db_present_is_pass(self):
        from towit_doctor import check_db_exists
        self._make_db()
        result = check_db_exists(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_permissions_correct_is_pass(self):
        from towit_doctor import check_db_permissions
        self._make_db()
        os.chmod(self.db_path, 0o600)
        result = check_db_permissions(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_permissions_too_open_is_warn(self):
        from towit_doctor import check_db_permissions
        self._make_db()
        os.chmod(self.db_path, 0o644)
        result = check_db_permissions(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('644', result.label)
        self.assertTrue(result.remediation)

    def test_db_dir_permissions_correct_is_pass(self):
        from towit_doctor import check_db_dir_permissions
        self._make_db()
        os.chmod(self.tmpdir, 0o700)
        result = check_db_dir_permissions(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_dir_permissions_too_open_is_warn(self):
        from towit_doctor import check_db_dir_permissions
        self._make_db()
        os.chmod(self.tmpdir, 0o755)
        result = check_db_dir_permissions(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertTrue(result.remediation)

    def test_db_tables_all_present_is_pass(self):
        from towit_doctor import check_db_tables
        self._make_db()
        result = check_db_tables(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_tables_missing_is_fail(self):
        from towit_doctor import check_db_tables
        self._make_db(tables=False)
        result = check_db_tables(self.db_path)
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('towit setup', result.remediation)

    def test_db_schema_current_is_pass(self):
        from towit_doctor import check_db_schema
        self._make_db()
        result = check_db_schema(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_schema_missing_message_count_is_warn(self):
        from towit_doctor import check_db_schema
        # Create DB without message_count column
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE conversations (id TEXT PRIMARY KEY,
            folder TEXT NOT NULL, cwd TEXT, started_at TEXT, last_active TEXT,
            title TEXT, summary TEXT, indexed_at TEXT NOT NULL DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL COLLATE NOCASE)""")
        conn.execute("""CREATE TABLE conversation_topics (
            conversation_id TEXT NOT NULL, topic_id INTEGER NOT NULL,
            PRIMARY KEY (conversation_id, topic_id))""")
        conn.commit()
        conn.close()
        result = check_db_schema(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('towit setup', result.remediation)

if __name__ == '__main__':
    unittest.main()
