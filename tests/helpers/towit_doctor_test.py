# tests/helpers/towit_doctor_test.py
import unittest
import sys, os
import tempfile
import shutil
import sqlite3
import json
import subprocess
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
        try:
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
        finally:
            conn.close()

    def test_db_missing_is_fail(self):
        from towit_doctor import check_db_exists
        result = check_db_exists(os.path.join(self.tmpdir, 'nonexistent.db'))
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
        from towit_db import Database
        Database(self.db_path).create_schema()
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

    def test_db_schema_missing_keywords_table_is_warn(self):
        from towit_doctor import check_db_schema
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript("""
                CREATE TABLE conversations (id TEXT PRIMARY KEY, folder TEXT NOT NULL,
                    cwd TEXT, started_at TEXT, last_active TEXT, title TEXT, summary TEXT,
                    message_count INTEGER, indexed_at TEXT NOT NULL DEFAULT (datetime('now')));
                CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_topics (
                    conversation_id TEXT NOT NULL, topic_id INTEGER NOT NULL,
                    PRIMARY KEY (conversation_id, topic_id));
            """)
            conn.commit()
        finally:
            conn.close()
        result = check_db_schema(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('towit setup', result.remediation)


class TestArchiveSchemaChecks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _legacy_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript("""
                CREATE TABLE conversations (id TEXT PRIMARY KEY, folder TEXT NOT NULL,
                    cwd TEXT, started_at TEXT, last_active TEXT, title TEXT, summary TEXT,
                    message_count INTEGER, indexed_at TEXT NOT NULL DEFAULT (datetime('now')));
                CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_topics (conversation_id TEXT NOT NULL,
                    topic_id INTEGER NOT NULL, PRIMARY KEY (conversation_id, topic_id));
                CREATE TABLE keywords (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_keywords (conversation_id TEXT NOT NULL,
                    keyword_id INTEGER NOT NULL, PRIMARY KEY (conversation_id, keyword_id));
            """)
            conn.commit()
        finally:
            conn.close()

    def _migrated_db(self):
        from towit_db import Database
        Database(self.db_path).create_schema()

    def test_fts5_available_passes_on_this_machine(self):
        from towit_doctor import check_fts5_available
        self.assertEqual(check_fts5_available().status, 'PASS')

    def test_fts5_unavailable_fails(self):
        from towit_doctor import check_fts5_available
        with patch('towit_doctor.sqlite3.connect',
                   side_effect=sqlite3.OperationalError('no such module: fts5')):
            result = check_fts5_available()
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('FTS5', result.label)
        self.assertTrue(result.remediation)

    def test_fts5_missing_module_during_create_fails(self):
        from towit_doctor import check_fts5_available

        class FakeConn:
            def execute(self, sql, *a):
                raise sqlite3.OperationalError('no such module: fts5')

            def close(self):
                pass
        with patch('towit_doctor.sqlite3.connect', return_value=FakeConn()):
            self.assertEqual(check_fts5_available().status, 'FAIL')

    def test_archive_schema_warns_on_legacy_db(self):
        from towit_doctor import check_archive_schema
        self._legacy_db()
        result = check_archive_schema(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('messages', result.label)
        self.assertIn('towit setup', result.remediation)

    def test_archive_schema_passes_after_migration(self):
        from towit_doctor import check_archive_schema
        self._migrated_db()
        self.assertEqual(check_archive_schema(self.db_path).status, 'PASS')

    def test_archive_schema_warns_when_user_version_behind(self):
        from towit_doctor import check_archive_schema
        self._migrated_db()
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        conn.close()
        result = check_archive_schema(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('user_version', result.label)

    def test_archive_schema_fails_when_fts_index_is_inconsistent(self):
        from towit_doctor import check_archive_schema
        self._migrated_db()
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO conversations (id, folder, archived) VALUES ('c', '/x', 1)")
        conn.execute("INSERT INTO messages (conversation_id, seq, role, text) "
                     "VALUES ('c', 0, 'user', 'hello world')")
        # desynchronise the external-content index: a message the index never saw
        conn.execute("DROP TRIGGER messages_ai")
        conn.execute("INSERT INTO messages (conversation_id, seq, role, text) "
                     "VALUES ('c', 1, 'user', 'unindexed words')")
        conn.commit()
        conn.close()
        result = check_archive_schema(self.db_path)
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('integrity', result.label.lower())
        self.assertIn('rebuild', result.remediation.lower())

    def test_archive_schema_check_does_not_modify_db(self):
        from towit_doctor import check_archive_schema
        self._migrated_db()
        with open(self.db_path, 'rb') as f:
            before = f.read()
        check_archive_schema(self.db_path)
        with open(self.db_path, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_db_schema_warns_when_archive_tables_missing(self):
        from towit_doctor import check_db_schema
        self._legacy_db()
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 1")  # irrelevant to this check
        conn.commit()
        conn.close()
        result = check_db_schema(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('messages', result.label)

    def test_archive_schema_on_garbage_file_does_not_raise(self):
        from towit_doctor import check_archive_schema
        with open(self.db_path, 'wb') as f:
            f.write(b'not a sqlite database at all' * 10)
        self.assertIn(check_archive_schema(self.db_path).status, ('WARN', 'FAIL'))


class TestHookChecks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.json')
        self.hook_script = os.path.join(self.tmpdir, 'towit_hook.py')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_settings(self, data):
        with open(self.settings_path, 'w') as f:
            json.dump(data, f)

    def test_settings_missing_is_warn(self):
        from towit_doctor import check_hook_settings_file
        result = check_hook_settings_file('/tmp/no_such_settings_towit.json')
        self.assertEqual(result.status, 'WARN')
        self.assertIn('not found', result.label)

    def test_settings_present_is_pass(self):
        from towit_doctor import check_hook_settings_file
        self._write_settings({})
        result = check_hook_settings_file(self.settings_path)
        self.assertEqual(result.status, 'PASS')

    def _hooks(self, events, script=None, extra=None):
        script = script or self.hook_script
        data = {'hooks': {ev: [{'matcher': '', 'hooks': [
            {'type': 'command', 'command': f'python3 {script}'}]}] for ev in events}}
        data.update(extra or {})
        self._write_settings(data)

    def test_no_hooks_registered_is_fail(self):
        from towit_doctor import check_hook_installed
        self._write_settings({'hooks': {'Stop': []}})
        result = check_hook_installed(self.settings_path)
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('hooks not found', result.label)
        self.assertIn('towit install-hook', result.remediation)

    def test_hook_installed_is_pass(self):
        from towit_doctor import check_hook_installed
        self._hooks(['Stop'])
        result = check_hook_installed(self.settings_path)
        self.assertEqual(result.status, 'PASS')

    def test_all_three_events_registered_is_pass(self):
        from towit_doctor import check_hook_events
        self._hooks(['Stop', 'SessionEnd', 'SessionStart'])
        self.assertEqual(check_hook_events(self.settings_path).status, 'PASS')

    def test_only_stop_registered_warns_naming_missing_events(self):
        from towit_doctor import check_hook_events
        self._hooks(['Stop'])
        result = check_hook_events(self.settings_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('SessionEnd', result.label)
        self.assertIn('SessionStart', result.label)
        self.assertNotIn('Stop', result.label.replace('SessionStart', ''))
        self.assertIn('towit install-hook', result.remediation)

    def test_non_towit_hook_does_not_count_as_registered(self):
        from towit_doctor import check_hook_events
        self._write_settings({'hooks': {ev: [{'matcher': '', 'hooks': [
            {'type': 'command', 'command': 'echo hi'}]}]
            for ev in ('Stop', 'SessionEnd', 'SessionStart')}})
        self.assertEqual(check_hook_events(self.settings_path).status, 'WARN')

    def test_disable_all_hooks_true_is_warn(self):
        from towit_doctor import check_hooks_not_disabled
        self._hooks(['Stop', 'SessionEnd', 'SessionStart'], extra={'disableAllHooks': True})
        result = check_hooks_not_disabled(self.settings_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('disableAllHooks', result.label)

    def test_disable_all_hooks_absent_is_pass(self):
        from towit_doctor import check_hooks_not_disabled
        self._hooks(['Stop'])
        self.assertEqual(check_hooks_not_disabled(self.settings_path).status, 'PASS')

    def test_hook_commands_all_existing_and_same_path_is_pass(self):
        from towit_doctor import check_hook_commands
        open(self.hook_script, 'w').close()
        self._hooks(['Stop', 'SessionEnd', 'SessionStart'])
        self.assertEqual(check_hook_commands(self.settings_path).status, 'PASS')

    def test_hook_command_path_missing_is_warn_naming_event(self):
        from towit_doctor import check_hook_commands
        self._hooks(['Stop'], script='/no/such/towit_hook.py')
        result = check_hook_commands(self.settings_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('Stop', result.label)
        self.assertIn('/no/such/towit_hook.py', result.label)
        self.assertIn('towit install-hook', result.remediation)

    def test_one_event_pointing_at_a_missing_path_is_warn(self):
        from towit_doctor import check_hook_commands
        open(self.hook_script, 'w').close()
        self._hooks(['Stop', 'SessionStart'])
        with open(self.settings_path) as f:
            data = json.load(f)
        data['hooks']['SessionEnd'] = [{'matcher': '', 'hooks': [
            {'type': 'command', 'command': 'python3 /old/place/towit_hook.py'}]}]
        self._write_settings(data)
        result = check_hook_commands(self.settings_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('SessionEnd', result.label)
        self.assertNotIn('SessionStart', result.label)

    def test_mixed_existing_hook_paths_is_warn(self):
        from towit_doctor import check_hook_commands
        other = os.path.join(self.tmpdir, 'moved', 'towit_hook.py')
        os.makedirs(os.path.dirname(other))
        open(other, 'w').close()
        open(self.hook_script, 'w').close()
        self._hooks(['Stop', 'SessionStart'])
        with open(self.settings_path) as f:
            data = json.load(f)
        data['hooks']['SessionEnd'] = [{'matcher': '', 'hooks': [
            {'type': 'command', 'command': f'python3 {other}'}]}]
        self._write_settings(data)
        result = check_hook_commands(self.settings_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('different', result.label)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HELPERS_DIR = os.path.join(PROJECT_ROOT, 'libexec', 'towit')
DOCTOR_SCRIPT = os.path.join(HELPERS_DIR, 'towit_doctor.py')


class TestDoctorMain(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = os.path.join(self.tmpdir, 'config.toml')
        self.settings_path = os.path.join(self.tmpdir, 'settings.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, extra_env=None):
        env = {
            **os.environ,
            'TOWIT_CONFIG_PATH': self.config_path,
            'TOWIT_SETTINGS_PATH': self.settings_path,
        }
        if extra_env:
            env.update(extra_env)
        env.pop('TOWIT_DB_PATH', None)
        return subprocess.run(
            ['python3', DOCTOR_SCRIPT],
            capture_output=True, text=True, env=env,
        )

    def _fake_claude_env(self):
        """PATH with a stub `claude` first, so doctor never needs the real CLI."""
        bin_dir = os.path.join(self.tmpdir, 'fakebin')
        os.makedirs(bin_dir, exist_ok=True)
        stub = os.path.join(bin_dir, 'claude')
        with open(stub, 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(stub, 0o755)
        return {'PATH': bin_dir + os.pathsep + os.environ.get('PATH', '')}

    def _write_config(self):
        with open(self.config_path, 'w') as f:
            f.write(f'[database]\npath = "{self.db_path}"\n')

    def _make_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript("""
                CREATE TABLE conversations (id TEXT PRIMARY KEY, folder TEXT NOT NULL,
                    cwd TEXT, started_at TEXT, last_active TEXT, title TEXT, summary TEXT,
                    message_count INTEGER, indexed_at TEXT NOT NULL DEFAULT (datetime('now')));
                CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_topics (
                    conversation_id TEXT NOT NULL, topic_id INTEGER NOT NULL,
                    PRIMARY KEY (conversation_id, topic_id));
                CREATE TABLE keywords (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_keywords (
                    conversation_id TEXT NOT NULL, keyword_id INTEGER NOT NULL,
                    PRIMARY KEY (conversation_id, keyword_id));
            """)
            conn.commit()
        finally:
            conn.close()
        os.chmod(self.db_path, 0o600)
        os.chmod(self.tmpdir, 0o700)

    def _install_hook(self, hook_script_path, events=('Stop', 'SessionEnd', 'SessionStart')):
        data = {'hooks': {ev: [{'matcher': '', 'hooks': [
            {'type': 'command', 'command': f'python3 {hook_script_path}'}
        ]}] for ev in events}}
        with open(self.settings_path, 'w') as f:
            json.dump(data, f)

    def test_help_exits_zero(self):
        result = subprocess.run(
            ['python3', DOCTOR_SCRIPT, '--help'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn('usage', combined.lower())

    def test_missing_db_prints_fail_and_exits_one(self):
        self._write_config()
        self._install_hook(DOCTOR_SCRIPT)  # any existing file works; hook content not checked here
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn('[FAIL]', result.stdout)
        self.assertIn('Database not found', result.stdout)
        self.assertIn('failure(s)', result.stdout)

    def test_hook_not_installed_prints_fail_and_exits_one(self):
        self._write_config()
        self._make_db()
        with open(self.settings_path, 'w') as f:
            json.dump({}, f)
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn('[FAIL]', result.stdout)
        self.assertIn('hooks not found', result.stdout.lower())
        self.assertIn('failure(s)', result.stdout)

    def test_all_ok_prints_pass_lines_and_exits_zero(self):
        self._write_config()
        sys.path.insert(0, HELPERS_DIR)
        from towit_db import Database
        Database(self.db_path).create_schema()
        os.chmod(self.db_path, 0o600)
        os.chmod(self.tmpdir, 0o700)
        hook_script = os.path.join(
            PROJECT_ROOT, 'libexec', 'towit', 'towit_hook.py'
        )
        self._install_hook(hook_script)
        result = self._run(self._fake_claude_env())
        self.assertEqual(result.returncode, 0, f"Expected exit 0, got output:\n{result.stdout}")
        self.assertNotIn('[FAIL]', result.stdout)
        self.assertIn('[PASS]', result.stdout)
        self.assertIn('All checks passed', result.stdout)

    def test_only_stop_hook_registered_warns_but_exits_zero(self):
        self._write_config()
        sys.path.insert(0, HELPERS_DIR)
        from towit_db import Database
        Database(self.db_path).create_schema()
        os.chmod(self.db_path, 0o600)
        os.chmod(self.tmpdir, 0o700)
        self._install_hook(os.path.join(HELPERS_DIR, 'towit_hook.py'), events=('Stop',))
        result = self._run(self._fake_claude_env())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('[WARN]', result.stdout)
        self.assertIn('SessionEnd', result.stdout)
        self.assertIn('SessionStart', result.stdout)

    def test_legacy_db_gets_archive_schema_warning(self):
        self._write_config()
        self._make_db()
        self._install_hook(os.path.join(HELPERS_DIR, 'towit_hook.py'))
        result = self._run()
        self.assertIn('messages', result.stdout)
        self.assertIn('[WARN]', result.stdout)


if __name__ == '__main__':
    unittest.main()
