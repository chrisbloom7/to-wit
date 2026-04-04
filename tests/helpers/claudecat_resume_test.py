# tests/helpers/claudecat_resume_test.py
# Tests for libexec/claudecat/claudecat_resume.py
#
# Run with: python3 tests/helpers/claudecat_resume_test.py

import unittest
import tempfile
import shutil
import subprocess
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'claudecat'))
RESUME_SCRIPT = os.path.join(HELPERS_DIR, 'claudecat_resume.py')

sys.path.insert(0, HELPERS_DIR)
from claudecat_db import Database


def run_resume(db_path, args=None):
    """Run claudecat_resume.py as a subprocess."""
    return subprocess.run(
        ['python3', RESUME_SCRIPT] + (args or []),
        env={**os.environ, 'CLAUDECAT_DB_PATH': db_path},
        capture_output=True,
        text=True
    )


class TestClaudecatResume(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cwd_dir = os.path.join(self.tmpdir, 'myapp')
        os.makedirs(self.cwd_dir)

        # Simulate the ~/.claude/projects folder structure
        self.projects_dir = os.path.join(self.tmpdir, 'projects', '-Users-alice')
        os.makedirs(self.projects_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
        db = Database(self.db_path)
        db.create_schema()
        db.upsert_conversation({
            'id': 'conv-a',
            'folder': self.projects_dir,
            'cwd': self.cwd_dir,
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'SQLite WAL mode deep dive',
            'summary': 'Deep dive into SQLite WAL mode',
            'topics': ['SQLite', 'WAL mode']
        })
        db.upsert_conversation({
            'id': 'conv-no-cwd',
            'folder': self.projects_dir,
            'cwd': None,
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'No cwd conversation',
            'summary': '',
            'topics': []
        })

        # Write a real JSONL transcript for conv-a
        open(os.path.join(self.projects_dir, 'conv-a.jsonl'), 'w').close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unknown_session_exits_1(self):
        result = run_resume(self.db_path, ['nonexistent-id'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('session not found', result.stderr)

    def test_missing_session_id_exits_nonzero(self):
        result = run_resume(self.db_path, [])
        self.assertNotEqual(result.returncode, 0)

    def test_cwd_missing_transcript_intact_without_force_exits_1(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.db_path, ['conv-a'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('working directory no longer exists', result.stderr)
        self.assertIn('--force', result.stderr)

    def test_cwd_missing_transcript_intact_without_force_mentions_manual_resume(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.db_path, ['conv-a'])
        self.assertIn('claude --resume', result.stderr)

    def test_cwd_missing_transcript_intact_without_force_suggests_resume_subcommand(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.db_path, ['conv-a'])
        self.assertIn('claudecat resume --force', result.stderr)

    def test_cwd_and_transcript_both_missing_exits_1(self):
        shutil.rmtree(self.cwd_dir)
        os.remove(os.path.join(self.projects_dir, 'conv-a.jsonl'))
        result = run_resume(self.db_path, ['conv-a'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('no longer resumable', result.stderr)

    def test_cwd_missing_with_force_recreates_directory(self):
        shutil.rmtree(self.cwd_dir)
        # Will fail trying to exec claude, but the directory should be created first
        run_resume(self.db_path, ['--force', 'conv-a'])
        self.assertTrue(os.path.isdir(self.cwd_dir))

    def test_cwd_missing_with_force_warns_about_recreation(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.db_path, ['--force', 'conv-a'])
        self.assertIn('recreated missing directory', result.stderr)

    def test_valid_session_attempts_exec(self):
        # With a valid session and existing cwd, the script will try to exec
        # `claude --resume conv-a`. Since `claude` may not be installed in the
        # test environment, we just verify it does NOT fail with our own errors.
        result = run_resume(self.db_path, ['conv-a'])
        self.assertNotIn('session not found', result.stderr)
        self.assertNotIn('working directory no longer exists', result.stderr)
        self.assertNotIn('no longer resumable', result.stderr)


if __name__ == '__main__':
    unittest.main()
