# tests/helpers/towit_prune_test.py
# Tests for libexec/towit/towit_prune.py
#
# Run with: python3 tests/helpers/towit_prune_test.py

import unittest
import tempfile
import shutil
import subprocess
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
PRUNE_SCRIPT = os.path.join(HELPERS_DIR, 'towit_prune.py')

sys.path.insert(0, HELPERS_DIR)
from towit_db import Database


def run_prune(db_path, args=None):
    """Run towit_prune.py as a subprocess."""
    return subprocess.run(
        ['python3', PRUNE_SCRIPT] + (args or []),
        env={**os.environ, 'TOWIT_DB_PATH': db_path},
        capture_output=True,
        text=True
    )


class TestClaudecatPrune(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmpdir, 'projects', '-Users-alice')
        os.makedirs(self.projects_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()

        # conv-a: transcript exists
        self.db.upsert_conversation({
            'id': 'conv-a',
            'folder': self.projects_dir,
            'cwd': self.tmpdir,
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'Has transcript',
            'summary': '',
            'topics': ['SQLite']
        })
        open(os.path.join(self.projects_dir, 'conv-a.jsonl'), 'w').close()

        # conv-b: transcript missing
        self.db.upsert_conversation({
            'id': 'conv-b',
            'folder': self.projects_dir,
            'cwd': self.tmpdir,
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'Missing transcript',
            'summary': '',
            'topics': ['Rails']
        })
        # no conv-b.jsonl written

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dry_run_does_not_delete(self):
        run_prune(self.db_path, ['--dry-run'])
        self.assertTrue(self.db.is_indexed('conv-b'))

    def test_dry_run_reports_missing(self):
        result = run_prune(self.db_path, ['--dry-run'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-b', result.stdout)
        self.assertIn('would remove', result.stdout)

    def test_dry_run_does_not_report_intact(self):
        result = run_prune(self.db_path, ['--dry-run'])
        self.assertNotIn('conv-a', result.stdout)

    def test_prune_removes_missing_transcript(self):
        run_prune(self.db_path)
        self.assertFalse(self.db.is_indexed('conv-b'))

    def test_prune_keeps_intact_transcript(self):
        run_prune(self.db_path)
        self.assertTrue(self.db.is_indexed('conv-a'))

    def test_prune_reports_removed(self):
        result = run_prune(self.db_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-b', result.stdout)
        self.assertIn('removed', result.stdout)

    def test_nothing_to_prune_reports_clean(self):
        # Remove conv-b from DB manually so both are intact
        self.db.delete_conversation('conv-b')
        result = run_prune(self.db_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Nothing to prune', result.stdout)

    def test_empty_catalog(self):
        self.db.delete_conversation('conv-a')
        self.db.delete_conversation('conv-b')
        result = run_prune(self.db_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('No conversations', result.stdout)


if __name__ == '__main__':
    unittest.main()
