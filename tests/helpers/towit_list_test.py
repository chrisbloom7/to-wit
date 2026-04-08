# tests/helpers/towit_list_test.py
# Tests for libexec/towit/towit_list.py
#
# Run with: python3 tests/helpers/towit_list_test.py

import unittest
import tempfile
import shutil
import subprocess
import csv
import io
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
LIST_SCRIPT = os.path.join(HELPERS_DIR, 'towit_list.py')

sys.path.insert(0, HELPERS_DIR)
from towit_db import Database


def write_config(tmpdir, db_path):
    """Write a minimal config.toml containing db_path. Returns config file path."""
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_list(config_path, args=None):
    """Run towit_list.py as a subprocess."""
    return subprocess.run(
        ['python3', LIST_SCRIPT] + (args or []),
        env={**os.environ, 'TOWIT_CONFIG_PATH': config_path},
        capture_output=True,
        text=True
    )


class TestTowitList(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.myapp_dir = os.path.join(self.tmpdir, 'myapp')
        self.otherapp_dir = os.path.join(self.tmpdir, 'otherapp')
        os.makedirs(self.myapp_dir)
        os.makedirs(self.otherapp_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        db.upsert_conversation({
            'id': 'conv-a',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.myapp_dir,
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'SQLite WAL mode deep dive',
            'summary': 'Deep dive into SQLite WAL mode',
            'topics': ['SQLite', 'WAL mode'],
            'keywords': ['sqlite', 'wal-mode', 'journal-mode'],
        })
        db.upsert_conversation({
            'id': 'conv-b',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.otherapp_dir,
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'Rails migration strategies',
            'summary': 'Rails migration strategies',
            'topics': ['Rails', 'migrations'],
            'keywords': ['rails', 'schema-changes', 'rollback'],
        })
        db.upsert_conversation({
            'id': 'conv-c',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.myapp_dir,
            'started_at': '2026-01-17T08:00:00Z',
            'last_active': '2026-01-17T08:30:00Z',
            'title': 'SQLite index optimization',
            'summary': 'SQLite index optimization techniques',
            'topics': ['SQLite', 'indexes'],
            'keywords': ['sqlite', 'index-optimization', 'query-performance'],
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ids_in_output(self, output):
        ids = set()
        for conv_id in ('conv-a', 'conv-b', 'conv-c'):
            if conv_id in output:
                ids.add(conv_id)
        return ids

    def test_list_returns_all_conversations(self):
        result = run_list(self.config_path)
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-b', ids)
        self.assertIn('conv-c', ids)

    def test_list_with_topic_returns_only_matching(self):
        result = run_list(self.config_path, ['--topic', 'SQLite'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_list_with_folder_returns_only_matching_cwd(self):
        result = run_list(self.config_path, ['--folder', self.myapp_dir])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_list_with_format_csv_includes_header_and_all_rows(self):
        result = run_list(self.config_path, ['--format', 'csv'])
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.strip().splitlines()
        # At least header + 3 data rows
        self.assertGreaterEqual(len(lines), 4, f"Expected header + 3 rows, got {len(lines)} lines")
        # Header should contain a field name
        header = lines[0].lower()
        self.assertTrue(
            'id' in header or 'title' in header or 'session' in header,
            f"Unexpected CSV header: {header!r}"
        )
        # All CSV rows should parse cleanly
        reader = csv.reader(io.StringIO(result.stdout))
        rows = list(reader)
        self.assertGreaterEqual(len(rows), 4)

    def test_csv_flag_is_not_recognized(self):
        result = run_list(self.config_path, ['--csv'])
        self.assertNotEqual(result.returncode, 0)

    def test_list_with_nonexistent_folder_returns_no_results(self):
        result = run_list(self.config_path, ['--folder', '/nonexistent/path'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-a', result.stdout)
        self.assertNotIn('conv-b', result.stdout)
        self.assertNotIn('conv-c', result.stdout)

    def test_empty_db_returns_exit_0(self):
        empty_db = os.path.join(self.tmpdir, 'empty.db')
        empty_config = write_config(self.tmpdir, empty_db)
        db = Database(empty_db)
        db.create_schema()
        result = run_list(empty_config)
        self.assertEqual(result.returncode, 0)

    def test_format_json_outputs_valid_json(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)

    def test_format_json_contains_all_conversations(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        ids = {row['id'] for row in data}
        self.assertIn('conv-a', ids)
        self.assertIn('conv-b', ids)
        self.assertIn('conv-c', ids)

    def test_format_json_includes_expected_fields(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        row = json.loads(result.stdout)[0]
        for field in ('id', 'title', 'topics', 'cwd', 'date'):
            self.assertIn(field, row, f"Missing field: {field}")

    def test_format_json_topics_is_list(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        conv_a = next(r for r in data if r['id'] == 'conv-a')
        self.assertIsInstance(conv_a['topics'], list)
        self.assertIn('SQLite', conv_a['topics'])

    def test_format_json_respects_topic_filter(self):
        import json
        result = run_list(self.config_path, ['--format', 'json', '--topic', 'SQLite'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        ids = {row['id'] for row in data}
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_keyword_filter_returns_only_matching(self):
        result = run_list(self.config_path, ['--keyword', 'journal-mode'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-a', result.stdout)
        self.assertNotIn('conv-b', result.stdout)
        self.assertNotIn('conv-c', result.stdout)

    def test_keyword_filter_excludes_non_matching(self):
        result = run_list(self.config_path, ['--keyword', 'rollback'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-b', result.stdout)
        self.assertNotIn('conv-a', result.stdout)

    def test_table_output_shows_keywords_column_header(self):
        result = run_list(self.config_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Keywords', result.stdout)
        self.assertNotIn('Topics', result.stdout)

    def test_format_json_includes_keywords_field(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        conv_a = next(r for r in data if r['id'] == 'conv-a')
        self.assertIn('keywords', conv_a)
        self.assertIsInstance(conv_a['keywords'], list)

    def test_format_csv_includes_keywords_column(self):
        import csv, io
        result = run_list(self.config_path, ['--format', 'csv'])
        self.assertEqual(result.returncode, 0)
        reader = csv.DictReader(io.StringIO(result.stdout))
        self.assertIn('keywords', reader.fieldnames)

    def test_format_json_respects_keyword_filter(self):
        import json
        result = run_list(self.config_path, ['--format', 'json', '--keyword', 'rollback'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        ids = {row['id'] for row in data}
        self.assertIn('conv-b', ids)
        self.assertNotIn('conv-a', ids)
        self.assertNotIn('conv-c', ids)


if __name__ == '__main__':
    unittest.main()
