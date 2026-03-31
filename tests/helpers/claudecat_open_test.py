# tests/helpers/claudecat_open_test.py
# Tests for libexec/claudecat/claudecat_open.py
#
# Run with: python3 tests/helpers/claudecat_open_test.py

import unittest
import tempfile
import shutil
import subprocess
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'claudecat'))
OPEN_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_open.py')

sys.path.insert(0, HELPERS_DIR)
from claudecat_db import Database


def run_open(db_path, args=None):
    """Run claudecat_open.py as a subprocess."""
    return subprocess.run(
        ['python3', OPEN_SCRIPT] + (args or []),
        env={**os.environ, 'CLAUDECAT_DB_PATH': db_path},
        capture_output=True,
        text=True
    )


class TestClaudecatOpen(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cwd_dir = os.path.join(self.tmpdir, 'myapp')
        os.makedirs(self.cwd_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
        db = Database(self.db_path)
        db.create_schema()
        db.upsert_conversation({
            'id': 'conv-a',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.cwd_dir,
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'SQLite WAL mode deep dive',
            'summary': 'Deep dive into SQLite WAL mode',
            'topics': ['SQLite', 'WAL mode']
        })
        db.upsert_conversation({
            'id': 'conv-no-cwd',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': None,
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'No cwd conversation',
            'summary': '',
            'topics': []
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unknown_session_exits_1(self):
        result = run_open(self.db_path, ['nonexistent-id'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('session not found', result.stderr)

    def test_missing_session_id_exits_nonzero(self):
        result = run_open(self.db_path, [])
        self.assertNotEqual(result.returncode, 0)

    def test_cwd_no_longer_exists_exits_1(self):
        shutil.rmtree(self.cwd_dir)
        result = run_open(self.db_path, ['conv-a'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('working directory no longer exists', result.stderr)

    def test_valid_session_attempts_exec(self):
        # With a valid session and existing cwd, the script will try to exec
        # `claude --resume conv-a`. Since `claude` may not be installed in the
        # test environment, we just verify it does NOT fail with our own errors.
        result = run_open(self.db_path, ['conv-a'])
        self.assertNotIn('session not found', result.stderr)
        self.assertNotIn('working directory no longer exists', result.stderr)


if __name__ == '__main__':
    unittest.main()
