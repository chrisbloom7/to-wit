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
from unittest.mock import PropertyMock, patch

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


class TestBackfillIngest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmpdir, 'projects', 'my-project')
        os.makedirs(self.projects_dir)
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        Database(self.db_path).create_schema()
        # The shared `config` singleton is built at import; patch the class so
        # ingest_transcript's Database() and indexing_enabled see this test's values.
        from towit_config import Config
        self.indexing_enabled = PropertyMock(return_value=True)
        self.patches = [
            patch('towit_index.index_conversation', return_value='indexed'),
            patch.object(Config, 'db_path', new_callable=PropertyMock,
                         return_value=self.db_path),
            patch.object(Config, 'indexing_enabled', self.indexing_enabled),
        ]
        self.index = self.patches[0].start()
        for p in self.patches[1:]:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _count(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute('SELECT COUNT(*) FROM conversations').fetchone()[0]

    def _write_session(self, session_id, messages=SUBSTANTIAL_MESSAGES, subdir=None):
        folder = os.path.join(self.projects_dir, subdir) if subdir else self.projects_dir
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f'{session_id}.jsonl')
        write_jsonl(path, messages, session_id=session_id)
        return path

    def _run(self, extra=None, enabled=True):
        self.indexing_enabled.return_value = enabled
        return run_backfill(['--folder', self.projects_dir] + (extra or []),
                            self.config_path, self.projects_dir)

    def test_ingests_then_indexes_each_session(self):
        self._write_session('good-session-001')
        self._write_session('good-session-002')
        output = self._run()
        self.assertEqual(self._count(), 2)
        self.assertEqual(self.index.call_count, 2)
        self.assertIn('ingested', output)
        self.assertIn('Archived: 2', output)
        self.assertIn('Indexed: 2', output)

    def test_indexing_disabled_archives_only(self):
        self._write_session('good-session-001')
        output = self._run(enabled=False)
        self.assertEqual(self._count(), 1)
        self.index.assert_not_called()
        self.assertIn('Archived: 1', output)
        self.assertIn('Indexed: 0', output)

    def test_short_session_is_skipped_and_not_indexed(self):
        self._write_session('short-session-001', TOO_SHORT_MESSAGES)
        output = self._run()
        self.index.assert_not_called()
        self.assertIn('Skipped: 1', output)

    def test_subagent_sessions_are_not_counted_or_printed(self):
        self._write_session('sub-session-001', subdir='subagents')
        output = self._run()
        self.index.assert_not_called()
        self.assertEqual(self._count(), 0)
        self.assertNotIn('sub-session-001', output)
        self.assertIn('No JSONL files found', output)

    def test_included_subagent_is_archived_but_not_indexed(self):
        from towit_config import Config
        self._write_session('sub-session-001', subdir='subagents')
        with patch.object(Config, 'ingest_include_subagents', new_callable=PropertyMock,
                          return_value=True):
            output = self._run()
        self.assertEqual(self._count(), 1)
        self.index.assert_not_called()
        self.assertIn('-> ingested', output)

    def test_symlinked_sessions_are_skipped(self):
        real = os.path.join(self.tmpdir, 'outside', 'link-session-001.jsonl')
        os.makedirs(os.path.dirname(real))
        write_jsonl(real, SUBSTANTIAL_MESSAGES, session_id='link-session-001')
        os.symlink(real, os.path.join(self.projects_dir, 'link-session-001.jsonl'))
        self._write_session('good-session-001')
        output = self._run()
        self.assertEqual(self.index.call_count, 1)
        self.assertEqual(self._count(), 1)
        self.assertNotIn('link-session-001', output)
        self.assertIn('[0/1]', output)

    def test_per_file_line_shows_ingest_status(self):
        self._write_session('good-session-001')
        output = self._run()
        self.assertIn('-> ingested', output)

    def test_ingest_error_counts_and_continues(self):
        self._write_session('good-session-001')
        with patch('towit_ingest.ingest_transcript', side_effect=RuntimeError('boom')):
            output = self._run()
        self.assertIn('Errors: 1', output)


if __name__ == '__main__':
    unittest.main()
