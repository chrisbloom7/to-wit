# tests/helpers/towit_backfill_test.py
# Tests for libexec/towit/towit_backfill.py
#
# Run with: python3 tests/helpers/towit_backfill_test.py

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)

from towit_db import Database


def write_config(tmpdir, db_path):
    """Write a minimal config.toml containing db_path. Returns config file path."""
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def write_jsonl(path, messages, session_id='test-session-abc'):
    """Write a minimal JSONL conversation file."""
    with open(path, 'w') as f:
        for i, msg in enumerate(messages):
            line = {
                'type': msg['role'],
                'message': {'role': msg['role'], 'content': msg['content']},
                'sessionId': session_id,
                'cwd': '/Users/test',
                'timestamp': f'2026-01-15T10:0{i}:00Z',
            }
            f.write(json.dumps(line) + '\n')


SUBSTANTIAL_MESSAGES = [
    {'role': 'user',      'content': 'Hello, can you help me understand SQLite WAL mode?'},
    {'role': 'assistant', 'content': 'Sure! WAL mode stands for Write-Ahead Logging.'},
    {'role': 'user',      'content': 'How does WAL mode improve concurrency for reads and writes?'},
    {'role': 'assistant', 'content': 'WAL allows readers and writers to coexist without blocking each other.'},
]

# Only one user turn — fails should_index's "fewer than 2 user turns" check
TOO_SHORT_MESSAGES = [
    {'role': 'user',      'content': 'ok'},
    {'role': 'assistant', 'content': 'Acknowledged.'},
]


def run_backfill(argv, config_path, projects_dir):
    """Import and run main() with patched sys.argv and env."""
    import importlib
    import towit_backfill
    importlib.reload(towit_backfill)

    with patch('sys.argv', ['towit_backfill'] + argv), \
         patch.dict(os.environ, {'TOWIT_CONFIG_PATH': config_path}):
        captured = io.StringIO()
        with patch('sys.stdout', captured), patch('sys.stderr', captured):
            try:
                towit_backfill.main()
            except SystemExit:
                pass
        return captured.getvalue()


class TestBackfillDryRun(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmpdir, 'projects', 'my-project')
        os.makedirs(self.projects_dir)
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_session(self, session_id, messages):
        path = os.path.join(self.projects_dir, f'{session_id}.jsonl')
        write_jsonl(path, messages, session_id=session_id)
        return path

    def test_dry_run_reports_would_skip_for_too_short_session(self):
        """Dry-run should count sessions that fail should_index() as skipped, not indexed."""
        self._write_session('short-session-001', TOO_SHORT_MESSAGES)
        output = run_backfill(
            ['--dry-run', '--folder', self.projects_dir],
            self.config_path, self.projects_dir,
        )
        self.assertIn('Skipped: 1', output)
        self.assertIn('Indexed: 0', output)

    def test_dry_run_reports_would_index_for_substantial_session(self):
        """Dry-run should count sessions that pass should_index() as indexed."""
        self._write_session('good-session-001', SUBSTANTIAL_MESSAGES)
        output = run_backfill(
            ['--dry-run', '--folder', self.projects_dir],
            self.config_path, self.projects_dir,
        )
        self.assertIn('Indexed: 1', output)
        self.assertIn('Skipped: 0', output)

    def test_dry_run_output_mentions_skip_reason_for_short_session(self):
        """Dry-run per-session output should say 'would skip' for short sessions."""
        self._write_session('short-session-002', TOO_SHORT_MESSAGES)
        output = run_backfill(
            ['--dry-run', '--folder', self.projects_dir],
            self.config_path, self.projects_dir,
        )
        self.assertIn('would skip', output)

    def test_dry_run_does_not_write_to_database(self):
        """Dry-run must never write any records to the database."""
        self._write_session('good-session-002', SUBSTANTIAL_MESSAGES)
        run_backfill(
            ['--dry-run', '--folder', self.projects_dir],
            self.config_path, self.projects_dir,
        )
        db = Database(self.db_path)
        # is_indexed should return False — nothing was written
        self.assertFalse(db.is_indexed('good-session-002'))


if __name__ == '__main__':
    unittest.main()
