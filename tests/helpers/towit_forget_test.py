# tests/helpers/towit_forget_test.py
# Tests for `towit forget`: Database.forget_conversation(s), conversation_ids_for_scope
# and libexec/towit/towit_forget.py
#
# Run with: python3 tests/helpers/towit_forget_test.py

import contextlib
import glob
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
FORGET_SCRIPT = os.path.join(HELPERS_DIR, 'towit_forget.py')
sys.path.insert(0, HELPERS_DIR)

import towit_forget
import towit_ingest
from towit_db import Database
from towit_ingest import ingest_transcript


def _entry(role, content, cwd='/work/proj'):
    return {'type': role, 'timestamp': '2026-01-01T00:00:00Z', 'cwd': cwd, 'sessionId': 'sid',
            'message': {'role': role, 'content': content}}


def _write_transcript(path, texts, cwd='/work/proj'):
    with open(path, 'w', encoding='utf-8') as fh:
        for i, text in enumerate(texts):
            fh.write(json.dumps(_entry('user' if i % 2 == 0 else 'assistant', text, cwd)) + '\n')


class ForgetBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.folder = os.path.join(self.tmp, 'projects', '-work-proj')
        os.makedirs(self.folder)
        self.db_path = os.path.join(self.tmp, 'catalog.db')
        self.config_path = os.path.join(self.tmp, 'config.toml')
        with open(self.config_path, 'w') as fh:
            fh.write(f'[database]\npath = "{self.db_path}"\n')
        self.db = Database(self.db_path)
        self.db.create_schema()
        for name, value in (('ingest_redact', True), ('ingest_extra_patterns', []),
                            ('ingest_include_subagents', False), ('ingest_folders', [])):
            patcher = unittest.mock.patch.object(
                type(towit_ingest.config), name, new_callable=unittest.mock.PropertyMock,
                return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ingest(self, sid, texts, cwd='/work/proj'):
        path = os.path.join(self.folder, f'{sid}.jsonl')
        _write_transcript(path, texts, cwd)
        self.assertEqual(ingest_transcript(path, self.db), 'ingested')
        return path

    def count(self, sql, params=()):
        with self.db.connect() as conn:
            return conn.execute(sql, params).fetchone()[0]

    def run_forget(self, args, stdin=''):
        return subprocess.run(
            ['python3', FORGET_SCRIPT] + args, input=stdin, capture_output=True, text=True,
            env={**os.environ, 'TOWIT_CONFIG_PATH': self.config_path})


class TestForgetConversation(ForgetBase):
    def test_removes_messages_and_search_hits_and_tombstones(self):
        self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'])
        self.assertEqual(len(self.db.search_archive(['zorblax'])), 1)
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self.db.search_archive(['zorblax']), [])
        self.assertEqual(self.count("SELECT COUNT(*) FROM messages WHERE conversation_id='sess-0001'"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM conversations"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'zorblax'"), 0)
        self.assertTrue(self.db.is_forgotten('sess-0001'))

    def test_tombstone_stores_only_id_and_timestamp(self):
        self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'])
        self.db.forget_conversation('sess-0001')
        with self.db.connect() as conn:
            cols = [r['name'] for r in conn.execute('PRAGMA table_info(forgotten)')]
        self.assertEqual(cols, ['id', 'forgotten_at'])

    def test_unknown_id_returns_false_and_writes_nothing(self):
        self.assertFalse(self.db.forget_conversation('nope-0000'))
        self.assertFalse(self.db.is_forgotten('nope-0000'))

    def test_cascades_topic_and_keyword_links(self):
        self.db.upsert_conversation({'id': 'sess-0001', 'folder': self.folder, 'cwd': '/w',
                                     'title': 't', 'summary': 's', 'topics': ['Alpha'],
                                     'keywords': ['kw']})
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self.count("SELECT COUNT(*) FROM conversation_topics"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM conversation_keywords"), 0)

    def test_orphan_topics_and_keywords_removed_shared_ones_kept(self):
        base = {'folder': self.folder, 'cwd': '/w', 'title': 't', 'summary': 's'}
        self.db.upsert_conversation({**base, 'id': 'sess-0001',
                                     'topics': ['OnlyMine', 'Shared'], 'keywords': ['mine-kw', 'shared-kw']})
        self.db.upsert_conversation({**base, 'id': 'sess-0002',
                                     'topics': ['Shared'], 'keywords': ['shared-kw']})
        self.db.forget_conversation('sess-0001')
        with self.db.connect() as conn:
            topics = [r['name'] for r in conn.execute('SELECT name FROM topics')]
            keywords = [r['name'] for r in conn.execute('SELECT name FROM keywords')]
        self.assertEqual(topics, ['Shared'])
        self.assertEqual(keywords, ['shared-kw'])

    def test_other_conversations_untouched(self):
        self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'])
        self.ingest('sess-0002', ['quuxify question', 'an answer', 'follow up'])
        self.db.forget_conversation('sess-0001')
        self.assertEqual(len(self.db.search_archive(['quuxify'])), 1)
        self.assertFalse(self.db.is_forgotten('sess-0002'))

    def test_already_tombstoned_existing_row_is_handled(self):
        self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'])
        with self.db.connect() as conn:
            conn.execute("INSERT INTO forgotten (id) VALUES ('sess-0001')")
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self.count("SELECT COUNT(*) FROM conversations"), 0)

    def test_ingest_after_forget_returns_forgotten_and_writes_nothing(self):
        path = self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'])
        self.db.forget_conversation('sess-0001')
        self.assertTrue(os.path.exists(path))
        self.assertEqual(ingest_transcript(path, self.db), 'forgotten')
        self.assertEqual(self.count("SELECT COUNT(*) FROM conversations"), 0)
        self.assertEqual(self.count("SELECT COUNT(*) FROM messages"), 0)

    def test_forget_conversations_is_all_or_nothing(self):
        self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'])
        self.ingest('sess-0002', ['quuxify question', 'an answer', 'follow up'])
        with unittest.mock.patch.object(Database, '_prune_orphan_labels',
                                        side_effect=RuntimeError('boom'), create=True):
            with self.assertRaises(RuntimeError):
                self.db.forget_conversations(['sess-0001', 'sess-0002'])
        self.assertEqual(self.count("SELECT COUNT(*) FROM conversations"), 2)
        self.assertEqual(self.count("SELECT COUNT(*) FROM forgotten"), 0)

    def test_forget_conversations_returns_count_of_existing(self):
        self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'])
        self.ingest('sess-0002', ['quuxify question', 'an answer', 'follow up'])
        self.assertEqual(self.db.forget_conversations(['sess-0001', 'sess-0002', 'nope-0000']), 2)
        self.assertEqual(self.db.forget_conversations([]), 0)
        self.assertFalse(self.db.is_forgotten('nope-0000'))


class TestRawBytesPurged(ForgetBase):
    MARKER = 'QZXWVMARKER' + 'k7q2p9d4'
    LONG = 'filler words ' * 400  # > one page, so text spills onto overflow pages

    def _scan(self):
        hits = {}
        for path in glob.glob(self.db_path + '*'):
            with open(path, 'rb') as fh:
                data = fh.read()
            # FTS5 stores lowercased tokens, so compare case-insensitively.
            hits[os.path.basename(path)] = data.lower().count(self.MARKER.lower().encode())
        return hits

    def _total(self):
        return sum(self._scan().values())

    def _archive(self, sid, texts):
        return self.db.archive_session(
            {'id': sid, 'folder': self.folder, 'cwd': '/w', 'repo_key': None, 'started_at': None,
             'last_active': None, 'source_path': None},
            [{'role': 'user' if i % 2 == 0 else 'assistant', 'ts': None, 'text': t}
             for i, t in enumerate(texts)])

    def _raw(self):
        """A connection with secure_delete OFF, standing in for older/other writers."""
        conn = sqlite3.connect(self.db_path)
        conn.execute('PRAGMA secure_delete=OFF')
        self.addCleanup(conn.close)
        return conn

    def test_marker_absent_from_db_wal_and_shm_after_forget(self):
        self.db.upsert_conversation({'id': 'sess-0001', 'folder': self.folder, 'cwd': '/w',
                                     'title': 'title ' + self.MARKER, 'summary': 'sum ' + self.MARKER,
                                     'topics': ['topic' + self.MARKER], 'keywords': ['kw' + self.MARKER]})
        self.ingest('sess-0001', ['hello ' + self.MARKER + ' world', 'reply ' + self.MARKER, 'final'])
        self.ingest('sess-0002', ['keep this other conversation', 'and its reply', 'more'])
        self.assertGreater(self._total(), 0)
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self._total(), 0, self._scan())
        self.assertEqual(len(self.db.search_archive(['keep'])), 1)

    def test_marker_absent_while_another_connection_keeps_wal_alive(self):
        self.ingest('sess-0001', ['hello ' + self.MARKER + ' world', 'reply', 'final'])
        keeper = sqlite3.connect(self.db_path)
        self.addCleanup(keeper.close)
        keeper.execute('PRAGMA journal_mode=WAL')
        self.assertGreater(self._total(), 0)
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self._total(), 0, self._scan())

    def test_marker_rewritten_away_through_archive_session_is_purged(self):
        self._archive('sess-0001', [self.LONG + self.MARKER + self.LONG, 'reply'])
        self.assertEqual(self._archive('sess-0001', ['different one', 'different two']), 'rewritten')
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self._total(), 0, self._scan())

    def test_residue_freed_without_secure_delete_is_purged(self):
        self._archive('sess-0001', [self.LONG + self.MARKER + self.LONG, 'reply'])
        raw = self._raw()
        raw.execute("DELETE FROM messages WHERE conversation_id='sess-0001'")
        raw.execute("INSERT INTO messages (conversation_id, seq, role, text) VALUES ('sess-0001', 0, 'user', 'x')")
        raw.commit()
        raw.close()
        self.assertGreater(self._total(), 0)  # freed pages still hold the text
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self._total(), 0, self._scan())

    def test_summary_reindexed_over_is_purged(self):
        base = {'id': 'sess-0001', 'folder': self.folder, 'cwd': '/w', 'title': 't', 'topics': []}
        self.db.upsert_conversation({**base, 'summary': self.LONG + self.MARKER + self.LONG})
        self.db.upsert_conversation({**base, 'summary': 'short'})
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self._total(), 0, self._scan())

    def test_summary_overwritten_without_secure_delete_is_purged(self):
        base = {'id': 'sess-0001', 'folder': self.folder, 'cwd': '/w', 'title': 't', 'topics': []}
        self.db.upsert_conversation({**base, 'summary': self.LONG + self.MARKER + self.LONG})
        raw = self._raw()
        raw.execute("UPDATE conversations SET summary='short' WHERE id='sess-0001'")
        raw.commit()
        raw.close()
        self.assertGreater(self._total(), 0)
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self._total(), 0, self._scan())

    def test_fts_optimize_is_load_bearing(self):
        self.ingest('sess-0001', ['hello ' + self.MARKER + ' world', 'reply', 'final'])
        with unittest.mock.patch.object(Database, '_optimize_fts', lambda self, conn: None):
            self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertGreater(self._total(), 0, 'lowercase FTS token should survive without optimize')
        self.ingest('sess-0003', ['hello ' + self.MARKER + ' world', 'reply', 'final'])
        self.assertTrue(self.db.forget_conversation('sess-0003'))
        self.assertEqual(self._total(), 0, self._scan())

    def test_connect_enables_secure_delete(self):
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('PRAGMA secure_delete').fetchone()[0], 1)


class TestForgetKeepsPermissions(unittest.TestCase):
    def test_files_stay_private_after_vacuuming_forget(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        d = os.path.join(tmp, 'towit')
        old = os.umask(0o077)
        try:
            os.mkdir(d)
            os.umask(0o177)
            db = Database(os.path.join(d, 'catalog.db'))
            db.create_schema()
        finally:
            os.umask(old)
        os.umask(0o022)
        self.addCleanup(os.umask, old)
        db.archive_session({'id': 'sess-0001', 'folder': 'f', 'cwd': '/w', 'repo_key': None,
                            'started_at': None, 'last_active': None, 'source_path': None},
                           [{'role': 'user', 'ts': None, 'text': 'hello ' * 500}])
        keeper = sqlite3.connect(db.db_path)
        self.addCleanup(keeper.close)
        keeper.execute('PRAGMA journal_mode=WAL')
        self.assertTrue(db.forget_conversation('sess-0001'))
        self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)
        for path in glob.glob(db.db_path + '*'):
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600, path)


class TestForgetCleanupWarnings(ForgetBase):
    def setUp(self):
        super().setUp()
        self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'])

    def remaining(self):
        return self.count("SELECT COUNT(*) FROM conversations")

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(towit_forget, 'Database', return_value=self.db), \
                unittest.mock.patch.object(sys, 'argv', ['towit_forget.py'] + args), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                towit_forget.main()
            finally:
                self.last_err = err.getvalue()
        return out.getvalue(), err.getvalue()

    def test_clean_run_has_no_warning(self):
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertIsNone(self.db.cleanup_warning)

    def test_busy_checkpoint_with_open_reader_sets_warning(self):
        reader = sqlite3.connect(self.db_path)
        self.addCleanup(reader.close)
        reader.execute('BEGIN')
        reader.execute('SELECT COUNT(*) FROM messages').fetchone()
        self.assertTrue(self.db.forget_conversation('sess-0001'))
        self.assertEqual(self.remaining(), 0)
        self.assertIn('write-ahead log', self.db.cleanup_warning)
        self.assertIn('`towit forget sess-0001`', self.db.cleanup_warning)

    def test_post_commit_failure_warns_and_exits_cleanly(self):
        with unittest.mock.patch.object(Database, '_purge_free_space',
                                        side_effect=sqlite3.OperationalError('disk I/O error')):
            out, err = self.run_cli(['sess-0001', '--yes'])
        self.assertIn('Forgot 1 conversation(s).', out)
        self.assertIn('Warning:', err)
        self.assertIn('physical cleanup', err)
        self.assertIn('`towit forget sess-0001`', err)
        self.assertEqual(self.remaining(), 0)
        self.assertTrue(self.db.is_forgotten('sess-0001'))

    def test_busy_reader_cli_warns_on_stderr(self):
        reader = sqlite3.connect(self.db_path)
        self.addCleanup(reader.close)
        reader.execute('BEGIN')
        reader.execute('SELECT COUNT(*) FROM messages').fetchone()
        out, err = self.run_cli(['sess-0001', '--yes'])
        self.assertIn('Forgot 1 conversation(s).', out)
        self.assertIn('Warning: some deleted data may remain in the write-ahead log', err)
        self.assertIn('Re-run `towit forget sess-0001`', err)

    def test_bulk_warning_names_first_forgotten_id(self):
        self.ingest('sess-0002', ['two', 'answer', 'more'])
        with unittest.mock.patch.object(Database, '_purge_free_space',
                                        side_effect=sqlite3.OperationalError('x')):
            self.db.forget_conversations(['sess-0002', 'sess-0001'])
        self.assertIn('`towit forget sess-0002`', self.db.cleanup_warning)

    def test_purge_free_space_is_idempotent_and_returns_none_when_clean(self):
        self.db.forget_conversation('sess-0001')
        self.assertIsNone(self.db.purge_free_space('sess-0001'))
        self.assertIsNone(self.db.purge_free_space('sess-0001'))

    def test_already_forgotten_id_reruns_cleanup_and_exits_zero(self):
        self.db.forget_conversation('sess-0001')
        with unittest.mock.patch.object(Database, 'purge_free_space', return_value=None) as purge:
            out, err = self.run_cli(['sess-0001'])
        purge.assert_called_once()
        self.assertIn('Already forgotten; re-ran physical cleanup.', out)
        self.assertEqual(err, '')

    def test_already_forgotten_rerun_prints_cleanup_warning(self):
        self.db.forget_conversation('sess-0001')
        with unittest.mock.patch.object(Database, 'purge_free_space', return_value='Re-run it'):
            out, err = self.run_cli(['sess-0001'])
        self.assertIn('Warning: Re-run it', err)

    def test_unknown_untombstoned_id_exits_1_without_cleanup(self):
        with unittest.mock.patch.object(Database, 'purge_free_space') as purge:
            with self.assertRaises(SystemExit) as cm:
                self.run_cli(['nope-0000'])
        self.assertEqual(cm.exception.code, 1)
        purge.assert_not_called()
        self.assertFalse(self.db.is_forgotten('nope-0000'))

    def test_bulk_selector_matching_nothing_does_not_run_cleanup(self):
        with unittest.mock.patch.object(Database, 'purge_free_space') as purge:
            with self.assertRaises(SystemExit) as cm:
                self.run_cli(['--folder', '/nowhere', '--yes'])
        self.assertEqual(cm.exception.code, 1)
        purge.assert_not_called()

    def test_in_transaction_failure_is_a_clean_error(self):
        with unittest.mock.patch.object(Database, '_optimize_fts',
                                        side_effect=sqlite3.OperationalError('boom')):
            with self.assertRaises(SystemExit) as cm:
                self.run_cli(['sess-0001', '--yes'])
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(self.remaining(), 1)
        self.assertIn('Error: could not forget (boom); nothing was deleted.', self.last_err)
        self.assertNotIn('Traceback', self.last_err)

    def test_optimize_failure_rolls_back_the_whole_forget(self):
        with unittest.mock.patch.object(Database, '_optimize_fts',
                                        side_effect=sqlite3.OperationalError('boom')):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.forget_conversation('sess-0001')
        self.assertEqual(self.remaining(), 1)
        self.assertFalse(self.db.is_forgotten('sess-0001'))
        self.assertEqual(self.count("SELECT COUNT(*) FROM messages"), 3)


class TestForgetScope(ForgetBase):
    def setUp(self):
        super().setUp()
        for sid, cwd, repo in (('sess-0001', '/work/proj', '/home/a/repo-one'),
                               ('sess-0002', '/work/other', '/home/a/repo-one'),
                               ('sess-0003', '/work/proj/sub', '/home/a/repo-two')):
            self.db.archive_session({'id': sid, 'folder': self.folder, 'cwd': cwd, 'repo_key': repo,
                                     'started_at': None, 'last_active': None, 'source_path': None},
                                    [{'role': 'user', 'ts': None, 'text': 'hi'}])

    def test_folder_matches_cwd_exactly(self):
        self.assertEqual(self.db.conversation_ids_for_scope(folder='/work/proj'), ['sess-0001'])

    def test_repo_matches_basename_and_exact(self):
        self.assertEqual(sorted(self.db.conversation_ids_for_scope(repo='repo-one')),
                         ['sess-0001', 'sess-0002'])
        self.assertEqual(self.db.conversation_ids_for_scope(repo='/home/a/repo-two'), ['sess-0003'])

    def test_repo_wildcards_are_literal(self):
        self.assertEqual(self.db.conversation_ids_for_scope(repo='repo-%'), [])
        self.assertEqual(self.db.conversation_ids_for_scope(repo='repo_one'), [])

    def test_no_selector_returns_empty(self):
        self.assertEqual(self.db.conversation_ids_for_scope(), [])


class TestForgetCli(ForgetBase):
    def setUp(self):
        super().setUp()
        self.ingest('sess-0001', ['zorblax question', 'an answer', 'follow up'], cwd='/work/proj')
        self.ingest('sess-0002', ['quuxify question', 'an answer', 'follow up'], cwd='/work/other')

    def remaining(self):
        return self.count("SELECT COUNT(*) FROM conversations")

    def test_session_id_yes(self):
        r = self.run_forget(['sess-0001', '--yes'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Forgot 1 conversation(s).', r.stdout)
        self.assertEqual(self.remaining(), 1)
        self.assertTrue(self.db.is_forgotten('sess-0001'))

    def _subagent(self, sid, parent):
        folder = os.path.join(self.folder, parent, 'subagents')
        self.db.archive_session({'id': sid, 'folder': folder, 'cwd': '/work/proj', 'repo_key': None,
                                 'started_at': None, 'last_active': None, 'source_path': None},
                                [{'role': 'user', 'ts': None, 'text': 'subagent secret work'}])

    def test_forgetting_a_session_also_forgets_its_subagent_conversations(self):
        self._subagent('agent-aaaa1', 'sess-0001')
        self._subagent('agent-aaaa2', 'sess-0001')
        self._subagent('agent-bbbb1', 'sess-0002')  # another session's subagent stays
        r = self.run_forget(['sess-0001', '--yes'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Forgot 3 conversation(s)', r.stdout)
        self.assertIn('2 subagent', r.stdout)
        with self.db.connect() as conn:
            left = sorted(x[0] for x in conn.execute("SELECT id FROM conversations"))
        self.assertEqual(left, ['agent-bbbb1', 'sess-0002'])
        for sid in ('sess-0001', 'agent-aaaa1', 'agent-aaaa2'):
            self.assertTrue(self.db.is_forgotten(sid), sid)
        self.assertFalse(self.db.is_forgotten('agent-bbbb1'))

    def test_prompt_counts_subagent_conversations(self):
        self._subagent('agent-aaaa1', 'sess-0001')
        r = self.run_forget(['sess-0001'], stdin='n\n')
        self.assertIn('Delete 2 conversation(s)? [y/N]', r.stdout)
        self.assertEqual(self.remaining(), 3)

    def test_prompt_shows_count_and_n_deletes_nothing(self):
        r = self.run_forget(['sess-0001'], stdin='n\n')
        self.assertIn('Delete 1 conversation(s)? [y/N]', r.stdout)
        self.assertIn('Aborted', r.stdout)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.remaining(), 2)

    def test_eof_and_empty_answers_delete_nothing(self):
        for stdin in ('', '\n', 'maybe\n'):
            r = self.run_forget(['sess-0001'], stdin=stdin)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(self.remaining(), 2, stdin)

    def test_piped_y_confirms(self):
        r = self.run_forget(['sess-0001'], stdin='Y\n')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.remaining(), 1)

    def test_unknown_session_exits_1(self):
        r = self.run_forget(['nope-0000', '--yes'])
        self.assertEqual(r.returncode, 1)
        self.assertIn('not found', r.stderr)
        self.assertEqual(self.remaining(), 2)
        self.assertFalse(self.db.is_forgotten('nope-0000'))

    def test_folder_deletes_only_exact_cwd(self):
        r = self.run_forget(['--folder', '/work/proj'], stdin='y\n')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Delete 1 conversation(s)? [y/N]', r.stdout)
        self.assertTrue(self.db.is_forgotten('sess-0001'))
        self.assertFalse(self.db.is_forgotten('sess-0002'))

    def test_repo_matches_by_basename(self):
        for sid, repo in (('sess-0001', '/home/a/repo-one'), ('sess-0002', '/home/a/repo-two')):
            with self.db.connect() as conn:
                conn.execute('UPDATE conversations SET repo_key=? WHERE id=?', (repo, sid))
        r = self.run_forget(['--repo', 'repo-one', '--yes'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.db.is_forgotten('sess-0001'))
        self.assertEqual(self.remaining(), 1)

    def test_repo_prompt_states_repo_span(self):
        for sid, repo in (('sess-0001', '/home/a/api'), ('sess-0002', '/home/b/api')):
            with self.db.connect() as conn:
                conn.execute('UPDATE conversations SET repo_key=? WHERE id=?', (repo, sid))
        r = self.run_forget(['--repo', 'api'], stdin='n\n')
        self.assertIn("Delete 2 conversation(s) across 2 repo(s) matching 'api'? [y/N]", r.stdout)
        self.assertEqual(self.remaining(), 2)

    def test_bulk_prompt_n_deletes_nothing(self):
        r = self.run_forget(['--folder', '/work/proj'], stdin='n\n')
        self.assertIn('Delete 1 conversation(s)? [y/N]', r.stdout)
        self.assertEqual(self.remaining(), 2)

    def test_no_selector_exits_2_with_usage(self):
        r = self.run_forget(['--yes'])
        self.assertEqual(r.returncode, 2)
        self.assertIn('usage', r.stderr.lower())
        self.assertEqual(self.remaining(), 2)

    def test_two_selectors_exit_2(self):
        for args in (['sess-0001', '--folder', '/work/proj'], ['--repo', 'x', '--folder', '/y'],
                     ['sess-0001', '--repo', 'x']):
            r = self.run_forget(args + ['--yes'])
            self.assertEqual(r.returncode, 2, args)
            self.assertIn('usage', r.stderr.lower())
        self.assertEqual(self.remaining(), 2)

    def test_selector_matching_nothing_exits_1(self):
        for args in (['--folder', '/nowhere'], ['--repo', 'nothing-here']):
            r = self.run_forget(args + ['--yes'])
            self.assertEqual(r.returncode, 1)
            self.assertIn('no conversations match', r.stderr)
        self.assertEqual(self.remaining(), 2)


if __name__ == '__main__':
    unittest.main()
