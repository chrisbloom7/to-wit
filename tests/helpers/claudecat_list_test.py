# tests/helpers/claudecat_list_test.py
# Tests for libexec/claudecat/claudecat_list.py
#
# Run with: python3 tests/helpers/claudecat_list_test.py

import unittest
import tempfile
import shutil
import subprocess
import csv
import io
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'claudecat'))
LIST_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_list.py')

sys.path.insert(0, HELPERS_DIR)
from claudecat_db import Database


def run_list(db_path, args=None):
    """Run claudecat_list.py as a subprocess."""
    return subprocess.run(
        ['python3', LIST_SCRIPT] + (args or []),
        env={**os.environ, 'CLAUDECAT_DB_PATH': db_path},
        capture_output=True,
        text=True
    )


class TestClaudecatList(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.myapp_dir = os.path.join(self.tmpdir, 'myapp')
        self.otherapp_dir = os.path.join(self.tmpdir, 'otherapp')
        os.makedirs(self.myapp_dir)
        os.makedirs(self.otherapp_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
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
            'topics': ['SQLite', 'WAL mode']
        })
        db.upsert_conversation({
            'id': 'conv-b',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.otherapp_dir,
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'Rails migration strategies',
            'summary': 'Rails migration strategies',
            'topics': ['Rails', 'migrations']
        })
        db.upsert_conversation({
            'id': 'conv-c',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.myapp_dir,
            'started_at': '2026-01-17T08:00:00Z',
            'last_active': '2026-01-17T08:30:00Z',
            'title': 'SQLite index optimization',
            'summary': 'SQLite index optimization techniques',
            'topics': ['SQLite', 'indexes']
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
        result = run_list(self.db_path)
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-b', ids)
        self.assertIn('conv-c', ids)

    def test_list_with_topic_returns_only_matching(self):
        result = run_list(self.db_path, ['--topic', 'SQLite'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_list_with_folder_returns_only_matching_cwd(self):
        result = run_list(self.db_path, ['--folder', self.myapp_dir])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_list_with_csv_includes_header_and_all_rows(self):
        result = run_list(self.db_path, ['--csv'])
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

    def test_list_with_nonexistent_folder_exits_1(self):
        result = run_list(self.db_path, ['--folder', '/nonexistent/path'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('folder not found', result.stderr)

    def test_empty_db_returns_exit_0(self):
        empty_db = os.path.join(self.tmpdir, 'empty.db')
        db = Database(empty_db)
        db.create_schema()
        result = run_list(empty_db)
        self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
