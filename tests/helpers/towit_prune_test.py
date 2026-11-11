# tests/helpers/towit_prune_test.py
# Tests for libexec/towit/towit_prune.py
#
# Run with: python3 tests/helpers/towit_prune_test.py

import glob
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


def write_config(tmpdir, db_path):
    """Write a minimal config.toml containing db_path. Returns config file path."""
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_prune(config_path, args=None, input_text=''):
    """Run towit_prune.py as a subprocess (stdin is empty unless input_text is given)."""
    return subprocess.run(
        ['python3', PRUNE_SCRIPT] + (args or []),
        env={**os.environ, 'TOWIT_CONFIG_PATH': config_path},
        input=input_text,
        capture_output=True,
        text=True
    )


class TestTowitPrune(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmpdir, 'projects', '-Users-alice')
        os.makedirs(self.projects_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
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
        run_prune(self.config_path, ['--dry-run'])
        self.assertTrue(self.db.is_indexed('conv-b'))

    def test_dry_run_reports_missing(self):
        result = run_prune(self.config_path, ['--dry-run'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-b', result.stdout)
        self.assertIn('would remove', result.stdout)

    def test_dry_run_does_not_report_intact(self):
        result = run_prune(self.config_path, ['--dry-run'])
        self.assertNotIn('conv-a', result.stdout)

    def test_prune_removes_missing_transcript(self):
        run_prune(self.config_path)
        self.assertFalse(self.db.is_indexed('conv-b'))

    def test_prune_keeps_intact_transcript(self):
        run_prune(self.config_path)
        self.assertTrue(self.db.is_indexed('conv-a'))

    def test_prune_reports_removed(self):
        result = run_prune(self.config_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-b', result.stdout)
        self.assertIn('removed', result.stdout)

    def test_nothing_to_prune_reports_clean(self):
        # Remove conv-b from DB manually so both are intact
        self.db.delete_conversation('conv-b')
        result = run_prune(self.config_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Nothing to prune', result.stdout)

    def test_empty_catalog(self):
        self.db.delete_conversation('conv-a')
        self.db.delete_conversation('conv-b')
        result = run_prune(self.config_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('No conversations', result.stdout)


class TestTowitPruneArchive(unittest.TestCase):
    """Archived rows survive default prune; --archive removes them after confirmation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmpdir, 'projects', '-Users-alice')
        os.makedirs(self.projects_dir)
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        self.db = Database(self.db_path)
        self.db.create_schema()

        # arch-kept: archived, transcript missing, project folder still exists
        self._archive('arch-kept', self.projects_dir, 'zebrafish habitat notes')
        # arch-purged: archived, whole project folder gone
        self.gone_dir = os.path.join(self.tmpdir, 'projects', '-Users-gone')
        self._archive('arch-purged', self.gone_dir, 'quokka migration notes')
        # meta-only: not archived, transcript missing
        self.db.upsert_conversation({
            'id': 'meta-only', 'folder': self.projects_dir, 'cwd': self.tmpdir,
            'started_at': '2026-01-18T09:00:00Z', 'last_active': '2026-01-18T09:45:00Z',
            'title': 'Metadata only', 'summary': '', 'topics': []
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _archive(self, conv_id, folder, text):
        self.db.archive_session(
            {'id': conv_id, 'folder': folder, 'cwd': self.tmpdir,
             'started_at': '2026-01-15T10:00:00Z', 'last_active': '2026-01-15T10:30:00Z',
             'repo_key': None, 'source_path': os.path.join(folder, f'{conv_id}.jsonl')},
            [{'role': 'user', 'ts': None, 'text': text},
             {'role': 'assistant', 'ts': None, 'text': 'ok'}],
        )

    def _exists(self, conv_id):
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conv_id,)).fetchone() is not None

    def _fts_hits(self, term):
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?", (term,)
            ).fetchone()[0]

    def test_default_prune_keeps_archived_and_removes_metadata_only(self):
        result = run_prune(self.config_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self._exists('arch-kept'))
        self.assertTrue(self._exists('arch-purged'))
        self.assertFalse(self._exists('meta-only'))
        self.assertIn('removed: meta-only', result.stdout)
        self.assertEqual(self._fts_hits('zebrafish'), 1)

    def test_dry_run_lists_archived_as_kept_not_removed(self):
        result = run_prune(self.config_path, ['--dry-run'])
        self.assertIn('would remove: meta-only', result.stdout)
        self.assertNotIn('would remove: arch-kept', result.stdout)
        self.assertIn('arch-kept', result.stdout)
        self.assertIn('archived', result.stdout)
        self.assertTrue(self._exists('arch-kept'))
        self.assertTrue(self._exists('meta-only'))

    def test_purge_report_counts_only_rows_with_missing_folder(self):
        for args in ([], ['--dry-run']):
            result = run_prune(self.config_path, args)
            self.assertIn(
                'Likely removed by claude purge: 1 archived conversations '
                'whose project folder no longer exists', result.stdout)
            purge_section = result.stdout.split('Likely removed by claude purge')[1]
            self.assertIn('arch-purged', purge_section)
            self.assertNotIn('arch-kept', purge_section)
            self.assertTrue(self._exists('arch-purged'))

    def test_purged_row_is_listed_once_and_hint_uses_cwd(self):
        # forget --folder matches cwd, so the purge section must show cwd, not the folder
        result = run_prune(self.config_path)
        self.assertEqual(result.stdout.count('arch-purged'), 1)
        purge_section = result.stdout.split('Likely removed by claude purge')[1]
        self.assertIn(self.tmpdir, purge_section)
        self.assertNotIn(self.gone_dir, purge_section)
        self.assertIn('towit forget --folder', purge_section)

    def test_report_absent_when_every_folder_exists(self):
        self.db.delete_conversation('arch-purged')
        result = run_prune(self.config_path)
        self.assertNotIn('Likely removed by claude purge', result.stdout)

    def test_report_only_when_only_archived_rows_missing(self):
        self.db.delete_conversation('meta-only')
        result = run_prune(self.config_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Nothing to prune', result.stdout)
        self.assertTrue(self._exists('arch-kept'))

    def test_subagent_folder_missing_is_judged_on_folder_itself(self):
        # a subagent conversation's folder is <proj>/<sess>/subagents; its own
        # directory not existing is what counts, even if <proj> exists
        sub_folder = os.path.join(self.projects_dir, 'sess-1', 'subagents')
        self._archive('arch-sub', sub_folder, 'subagent notes')
        result = run_prune(self.config_path, ['--dry-run'])
        self.assertIn('Likely removed by claude purge: 2 archived', result.stdout)

    def test_archive_flag_prompts_with_count_and_declining_removes_nothing(self):
        result = run_prune(self.config_path, ['--archive'], input_text='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('2 archived conversations', result.stdout)
        for cid in ('arch-kept', 'arch-purged', 'meta-only'):
            self.assertTrue(self._exists(cid), cid)

    def test_archive_flag_with_closed_stdin_removes_nothing(self):
        result = run_prune(self.config_path, ['--archive'])
        self.assertEqual(result.returncode, 0, result.stderr)
        for cid in ('arch-kept', 'arch-purged', 'meta-only'):
            self.assertTrue(self._exists(cid), cid)

    def test_archive_flag_confirmed_removes_archived_rows_and_fts(self):
        result = run_prune(self.config_path, ['--archive'], input_text='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        for cid in ('arch-kept', 'arch-purged', 'meta-only'):
            self.assertFalse(self._exists(cid), cid)
        self.assertEqual(self._fts_hits('zebrafish'), 0)
        self.assertEqual(self._fts_hits('quokka'), 0)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
        # prune is not forget: no tombstone, so the session can be re-ingested
        self.assertFalse(self.db.is_forgotten('arch-kept'))

    def test_archive_yes_skips_prompt(self):
        result = run_prune(self.config_path, ['--archive', '--yes'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self._exists('arch-kept'))
        self.assertFalse(self._exists('arch-purged'))
        self.assertNotIn('[y/N]', result.stdout)

    def test_archive_dry_run_lists_without_prompting_or_deleting(self):
        result = run_prune(self.config_path, ['--archive', '--dry-run'])
        self.assertIn('would remove: arch-kept', result.stdout)
        self.assertTrue(self._exists('arch-kept'))
        self.assertNotIn('[y/N]', result.stdout)

    def test_archive_flag_without_archived_rows_does_not_prompt(self):
        self.db.delete_conversation('arch-kept')
        self.db.delete_conversation('arch-purged')
        result = run_prune(self.config_path, ['--archive'])
        self.assertNotIn('[y/N]', result.stdout)
        self.assertFalse(self._exists('meta-only'))

    def test_archive_prune_physically_removes_text_and_leaves_no_tombstone(self):
        marker = 'QZXPRUNE' + 'marker8h3k'
        self._archive('arch-marker', self.projects_dir, 'hello ' + marker + ' world')
        self.db.upsert_conversation({'id': 'arch-marker', 'folder': self.projects_dir,
                                     'cwd': self.tmpdir, 'title': 'T ' + marker,
                                     'summary': '', 'topics': ['tp' + marker],
                                     'keywords': ['kw' + marker]})

        def total():
            n = 0
            for path in glob.glob(self.db_path + '*'):
                with open(path, 'rb') as fh:
                    n += fh.read().lower().count(marker.lower().encode())
            return n

        self.assertGreater(total(), 0)
        result = run_prune(self.config_path, ['--archive', '--yes'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self._exists('arch-marker'))
        self.assertEqual(total(), 0)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM forgotten").fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
