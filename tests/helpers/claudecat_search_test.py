# tests/helpers/claudecat_search_test.py
# Tests for libexec/claudecat/claudecat_search.py
#
# Run with: python3 tests/helpers/claudecat_search_test.py

import unittest
import tempfile
import shutil
import subprocess
import csv
import io
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'claudecat'))
SEARCH_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_search.py')

sys.path.insert(0, HELPERS_DIR)
from claudecat_db import Database


def run_search(db_path, args):
    """Run claudecat_search.py as a subprocess."""
    return subprocess.run(
        ['python3', SEARCH_SCRIPT] + args,
        env={**os.environ, 'CLAUDECAT_DB_PATH': db_path},
        capture_output=True,
        text=True
    )


class TestClaudecatSearch(unittest.TestCase):
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
        # Unique summary/title words; hyphenated topic for stem-match testing
        db.upsert_conversation({
            'id': 'conv-d',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.otherapp_dir,
            'started_at': '2026-01-18T07:00:00Z',
            'last_active': '2026-01-18T07:45:00Z',
            'title': 'Velocity estimation for Q2',
            'summary': 'Reviewed burndown charts and story-point estimation for the quarter.',
            'topics': ['project-estimation', 'agile']
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ids_in_output(self, output):
        ids = set()
        for conv_id in ('conv-a', 'conv-b', 'conv-c'):
            if conv_id in output:
                ids.add(conv_id)
        return ids

    def test_search_sqlite_returns_a_and_c(self):
        result = run_search(self.db_path, ['SQLite'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_search_sqlite_wal_and_mode_returns_only_a(self):
        result = run_search(self.db_path, ['SQLite', 'WAL'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertNotIn('conv-b', ids)
        self.assertNotIn('conv-c', ids)

    def test_search_sqlite_rails_or_mode_returns_all(self):
        result = run_search(self.db_path, ['SQLite', 'Rails', '--or'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-b', ids)
        self.assertIn('conv-c', ids)

    def test_search_sqlite_rails_and_mode_returns_nothing(self):
        result = run_search(self.db_path, ['SQLite', 'Rails'])
        # exit 0 with no results is acceptable; no conv IDs in output
        ids = self._ids_in_output(result.stdout)
        self.assertEqual(ids, set())

    def test_search_with_csv_includes_header_row(self):
        result = run_search(self.db_path, ['SQLite', '--csv'])
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.strip().splitlines()
        self.assertTrue(len(lines) >= 1, "Expected at least a header line")
        header = lines[0].lower()
        # Header should contain common field names
        self.assertTrue(
            'id' in header or 'title' in header or 'session' in header,
            f"Unexpected CSV header: {header!r}"
        )

    def test_search_with_csv_output_is_valid_csv(self):
        result = run_search(self.db_path, ['SQLite', '--csv'])
        self.assertEqual(result.returncode, 0)
        # Should parse without error
        reader = csv.reader(io.StringIO(result.stdout))
        rows = list(reader)
        self.assertTrue(len(rows) >= 1, "Expected at least a header row in CSV output")

    def test_search_with_folder_scoped_to_cwd(self):
        result = run_search(self.db_path, ['SQLite', '--folder', self.myapp_dir])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_search_with_nonexistent_folder_returns_no_results(self):
        result = run_search(self.db_path, ['SQLite', '--folder', '/nonexistent/path'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-a', result.stdout)
        self.assertNotIn('conv-b', result.stdout)
        self.assertNotIn('conv-c', result.stdout)

    def test_no_results_exits_0(self):
        result = run_search(self.db_path, ['absolutelyunknownterm'])
        self.assertEqual(result.returncode, 0)

    def test_missing_terms_exits_nonzero(self):
        result = run_search(self.db_path, [])
        self.assertNotEqual(result.returncode, 0)

    def test_default_does_not_match_summary_only(self):
        # "burndown" is only in conv-d's summary, not any topic
        result = run_search(self.db_path, ['burndown'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-d', result.stdout)

    def test_summary_flag_finds_summary_match(self):
        result = run_search(self.db_path, ['burndown', '--summary'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_title_flag_finds_title_match(self):
        # "Velocity" is only in conv-d's title, not any topic
        result = run_search(self.db_path, ['Velocity', '--title'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_default_does_not_match_title_only(self):
        result = run_search(self.db_path, ['Velocity'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-d', result.stdout)

    def test_stem_matches_hyphenated_topic(self):
        # "estimate" (stem "estimat") should match topic "project-estimation"
        result = run_search(self.db_path, ['estimate'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)


if __name__ == '__main__':
    unittest.main()
