# tests/helpers/claudecat_stats_test.py
# Tests for libexec/claudecat/claudecat_stats.py
#
# Run with: python3 tests/helpers/claudecat_stats_test.py

import unittest
import tempfile
import shutil
import subprocess
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'claudecat'))
STATS_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_stats.py')

sys.path.insert(0, HELPERS_DIR)
from claudecat_db import Database


def run_stats(db_path):
    return subprocess.run(
        ['python3', STATS_SCRIPT],
        env={**os.environ, 'CLAUDECAT_DB_PATH': db_path},
        capture_output=True,
        text=True
    )


class TestClaudecatStats(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmpdir, 'projects', '-Users-alice')
        os.makedirs(self.projects_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()

        # conv-a: transcript exists, cwd exists
        self.db.upsert_conversation({
            'id': 'conv-a',
            'folder': self.projects_dir,
            'cwd': self.tmpdir,
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'SQLite WAL mode',
            'summary': '',
            'topics': ['SQLite', 'WAL mode']
        })
        open(os.path.join(self.projects_dir, 'conv-a.jsonl'), 'w').close()

        # conv-b: transcript exists, different cwd
        self.db.upsert_conversation({
            'id': 'conv-b',
            'folder': self.projects_dir,
            'cwd': os.path.join(self.tmpdir, 'other'),
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'Rails migrations',
            'summary': '',
            'topics': ['Rails', 'SQLite']
        })
        open(os.path.join(self.projects_dir, 'conv-b.jsonl'), 'w').close()

        # conv-c: transcript missing (pruneable)
        self.db.upsert_conversation({
            'id': 'conv-c',
            'folder': self.projects_dir,
            'cwd': self.tmpdir,
            'started_at': '2026-01-17T08:00:00Z',
            'last_active': '2026-01-17T08:30:00Z',
            'title': 'Missing transcript',
            'summary': '',
            'topics': ['Rails']
        })
        # no conv-c.jsonl written

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exits_0(self):
        result = run_stats(self.db_path)
        self.assertEqual(result.returncode, 0)

    def test_shows_total_conversations(self):
        result = run_stats(self.db_path)
        self.assertIn('3', result.stdout)

    def test_shows_date_range(self):
        result = run_stats(self.db_path)
        self.assertIn('2026-01-15', result.stdout)
        self.assertIn('2026-01-17', result.stdout)

    def test_shows_unique_projects(self):
        result = run_stats(self.db_path)
        # tmpdir and other are two distinct cwd values
        self.assertIn('2', result.stdout)

    def test_shows_top_topics(self):
        result = run_stats(self.db_path)
        self.assertIn('SQLite', result.stdout)
        self.assertIn('Rails', result.stdout)

    def test_shows_pruneable_when_transcripts_missing(self):
        result = run_stats(self.db_path)
        self.assertIn('Pruneable', result.stdout)
        self.assertIn('1', result.stdout)
        self.assertIn('claudecat prune', result.stdout)

    def test_no_pruneable_line_when_all_transcripts_intact(self):
        # Add the missing transcript so everything is intact
        open(os.path.join(self.projects_dir, 'conv-c.jsonl'), 'w').close()
        result = run_stats(self.db_path)
        self.assertNotIn('Pruneable', result.stdout)

    def test_empty_db_exits_0(self):
        empty_db = os.path.join(self.tmpdir, 'empty.db')
        db = Database(empty_db)
        db.create_schema()
        result = run_stats(empty_db)
        self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
