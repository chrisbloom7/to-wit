# tests/helpers/towit_db_test.py
# Tests for libexec/towit/towit_db.py
#
# Run with: python3 tests/helpers/towit_db_test.py

import contextlib
import io
import threading
import unittest
import unittest.mock
import tempfile
import shutil
import sqlite3
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)

import towit_db
from towit_db import SCHEMA_VERSION, Database, message_hash, build_match_expression, is_fts_query_error

SAMPLE_CONV = {
    'id': 'test-session-001',
    'folder': '/home/user/.claude/projects/-Users-alice',
    'cwd': '/Users/alice/src/myapp',
    'started_at': '2026-01-15T10:00:00Z',
    'last_active': '2026-01-15T10:30:00Z',
    'title': 'SQLite WAL mode deep dive',
    'summary': 'Explored SQLite WAL mode for concurrent access in production.',
    'topics': ['SQLite', 'WAL mode', 'database concurrency'],
    'keywords': ['sqlite', 'wal-mode', 'write-ahead-log', 'concurrent-reads', 'journal-mode'],
}

SAMPLE_CONV_B = {
    'id': 'test-session-002',
    'folder': '/home/user/.claude/projects/-Users-alice',
    'cwd': '/Users/alice/src/otherapp',
    'started_at': '2026-01-16T09:00:00Z',
    'last_active': '2026-01-16T09:45:00Z',
    'title': 'Rails migration strategies',
    'summary': 'Discussed various Rails migration strategies.',
    'topics': ['Rails', 'migrations', 'activerecord'],
    # 'activerecord' is a topic-only term (not in keywords) for testing default scope
    'keywords': ['rails', 'schema-changes', 'rollback', 'data-migration'],
}

# Has a unique word only in summary/title, and a hyphenated topic for stem-match testing.
# 'burndown' is summary-only (not in keywords) to preserve that test coverage.
SAMPLE_CONV_C = {
    'id': 'test-session-003',
    'folder': '/home/user/.claude/projects/-Users-alice',
    'cwd': '/Users/alice/src/otherapp',
    'started_at': '2026-01-17T08:00:00Z',
    'last_active': '2026-01-17T08:30:00Z',
    'title': 'Velocity estimation for Q2',
    'summary': 'Reviewed burndown charts and story-point estimation for the quarter.',
    'topics': ['project-estimation', 'agile'],
    'keywords': ['sprint-planning', 'story-points', 'quarterly-review'],
}


class TestDatabaseSchema(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_schema_creates_conversations_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'")
        self.assertIsNotNone(cursor.fetchone(), "conversations table should exist")
        conn.close()

    def test_create_schema_creates_topics_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='topics'")
        self.assertIsNotNone(cursor.fetchone(), "topics table should exist")
        conn.close()

    def test_create_schema_creates_conversation_topics_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_topics'")
        self.assertIsNotNone(cursor.fetchone(), "conversation_topics table should exist")
        conn.close()

    def test_create_schema_creates_keywords_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='keywords'")
        self.assertIsNotNone(cursor.fetchone(), "keywords table should exist")
        conn.close()

    def test_create_schema_creates_conversation_keywords_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_keywords'")
        self.assertIsNotNone(cursor.fetchone(), "conversation_keywords table should exist")
        conn.close()


class TestDatabaseUpsert(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_upsert_conversation_inserts_record(self):
        self.db.upsert_conversation(SAMPLE_CONV)
        result = self.db.get_conversation(SAMPLE_CONV['id'])
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], SAMPLE_CONV['id'])

    def test_upsert_conversation_stores_title(self):
        self.db.upsert_conversation(SAMPLE_CONV)
        result = self.db.get_conversation(SAMPLE_CONV['id'])
        self.assertEqual(result['title'], SAMPLE_CONV['title'])

    def test_upsert_conversation_stores_topics(self):
        self.db.upsert_conversation(SAMPLE_CONV)
        result = self.db.get_conversation(SAMPLE_CONV['id'])
        # topics may be returned as comma-joined string or list
        topics_str = result['topics'] if isinstance(result['topics'], str) else ', '.join(result['topics'])
        for topic in SAMPLE_CONV['topics']:
            self.assertIn(topic.lower(), topics_str.lower())

    def test_upsert_conversation_updates_existing_record(self):
        self.db.upsert_conversation(SAMPLE_CONV)
        updated = dict(SAMPLE_CONV)
        updated['title'] = 'Updated title'
        self.db.upsert_conversation(updated)
        result = self.db.get_conversation(SAMPLE_CONV['id'])
        self.assertEqual(result['title'], 'Updated title')

    def test_topics_stored_case_insensitively(self):
        conv = dict(SAMPLE_CONV)
        conv['topics'] = ['SQLite', 'sqlite', 'SQLITE']
        self.db.upsert_conversation(conv)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM topics WHERE LOWER(name) = 'sqlite'")
        rows = cursor.fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)

    def test_upsert_conversation_stores_keywords(self):
        self.db.upsert_conversation(SAMPLE_CONV)

        result = self.db.get_conversation(SAMPLE_CONV['id'])

        keywords_str = result['keywords'] if isinstance(result['keywords'], str) else ', '.join(result['keywords'])
        for kw in SAMPLE_CONV['keywords']:
            self.assertIn(kw.lower(), keywords_str.lower())

    def test_upsert_conversation_replaces_keywords_on_reindex(self):
        self.db.upsert_conversation(SAMPLE_CONV)
        updated = dict(SAMPLE_CONV)
        updated['keywords'] = ['new-keyword', 'another-keyword']

        self.db.upsert_conversation(updated)

        result = self.db.get_conversation(SAMPLE_CONV['id'])
        keywords_str = result['keywords'] if isinstance(result['keywords'], str) else ', '.join(result['keywords'])
        self.assertIn('new-keyword', keywords_str.lower())
        for old_kw in SAMPLE_CONV['keywords']:
            self.assertNotIn(old_kw.lower(), keywords_str.lower())

    def test_upsert_conversation_without_keywords_stores_empty(self):
        conv = {k: v for k, v in SAMPLE_CONV.items() if k != 'keywords'}

        self.db.upsert_conversation(conv)

        result = self.db.get_conversation(SAMPLE_CONV['id'])
        keywords_str = result.get('keywords', '') or ''
        self.assertEqual(keywords_str, '')

    def test_keywords_stored_case_insensitively(self):
        conv = dict(SAMPLE_CONV)
        conv['keywords'] = ['SQLite', 'sqlite', 'SQLITE']

        self.db.upsert_conversation(conv)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM keywords WHERE LOWER(name) = 'sqlite'")
        rows = cursor.fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)


class TestDatabaseIsIndexed(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_is_indexed_returns_true_for_existing(self):
        self.db.upsert_conversation(SAMPLE_CONV)
        self.assertTrue(self.db.is_indexed(SAMPLE_CONV['id']))

    def test_is_indexed_returns_false_for_missing(self):
        self.assertFalse(self.db.is_indexed('nonexistent-id'))

    def test_is_indexed_false_for_archive_only_row_true_for_titled(self):
        conv = {'id': 'arc-only', 'folder': '/f', 'cwd': '/w', 'started_at': None,
                'last_active': None, 'repo_key': 'r', 'source_path': '/p'}
        self.db.archive_session(conv, [{'role': 'user', 'ts': None, 'text': 'hi'}])
        self.assertFalse(self.db.is_indexed('arc-only'))
        self.db.upsert_conversation(dict(SAMPLE_CONV, id='arc-only'))
        self.assertTrue(self.db.is_indexed('arc-only'))


class TestDatabaseSearch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()
        self.db.upsert_conversation(SAMPLE_CONV)
        self.db.upsert_conversation(SAMPLE_CONV_B)
        self.db.upsert_conversation(SAMPLE_CONV_C)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ids(self, results):
        return {r['id'] for r in results}

    def test_search_and_mode_finds_matching_single_term(self):
        results = self.db.search(['SQLite'], mode='and')
        self.assertIn(SAMPLE_CONV['id'], self._ids(results))
        self.assertNotIn(SAMPLE_CONV_B['id'], self._ids(results))

    def test_search_and_mode_finds_matching_multiple_terms(self):
        results = self.db.search(['SQLite', 'WAL'], mode='and')
        self.assertIn(SAMPLE_CONV['id'], self._ids(results))
        self.assertNotIn(SAMPLE_CONV_B['id'], self._ids(results))

    def test_search_or_mode_finds_any_matching(self):
        results = self.db.search(['SQLite', 'Rails'], mode='or')
        ids = self._ids(results)
        self.assertIn(SAMPLE_CONV['id'], ids)
        self.assertIn(SAMPLE_CONV_B['id'], ids)

    def test_search_and_mode_no_match_returns_empty(self):
        results = self.db.search(['SQLite', 'Rails'], mode='and')
        self.assertEqual(results, [])

    def test_search_no_matches_returns_empty(self):
        results = self.db.search(['completelyunknownterm'], mode='and')
        self.assertEqual(results, [])

    def test_search_folder_filter_returns_only_matching_cwd(self):
        results = self.db.search(['SQLite'], mode='and', folder='/Users/alice/src/myapp')
        ids = self._ids(results)
        self.assertIn(SAMPLE_CONV['id'], ids)
        for r in results:
            self.assertIn('/Users/alice/src/myapp', r['cwd'])

    def test_search_default_finds_by_keyword(self):
        # "journal-mode" is in SAMPLE_CONV's keywords but not its topics/title/summary
        results = self.db.search(['journal-mode'], mode='and')
        self.assertIn(SAMPLE_CONV['id'], self._ids(results))

    def test_search_default_does_not_find_topic_only_match(self):
        # "activerecord" is a topic on SAMPLE_CONV_B but not a keyword
        results = self.db.search(['activerecord'], mode='and')
        self.assertEqual(results, [])

    def test_search_with_include_topics_finds_topic_match(self):
        results = self.db.search(['activerecord'], mode='and', include_topics=True)
        self.assertIn(SAMPLE_CONV_B['id'], self._ids(results))

    def test_search_with_include_keywords_false_does_not_find_keyword_match(self):
        results = self.db.search(['journal-mode'], mode='and', include_keywords=False)
        self.assertEqual(results, [])

    def test_search_results_include_keywords_field(self):
        results = self.db.search(['journal-mode'], mode='and')
        result = next(r for r in results if r['id'] == SAMPLE_CONV['id'])
        self.assertIn('keywords', result)
        self.assertIn('journal-mode', result['keywords'])

    def test_search_default_does_not_match_summary_only(self):
        # "burndown" appears only in SAMPLE_CONV_C's summary, not in keywords or topics
        results = self.db.search(['burndown'], mode='and')
        self.assertEqual(results, [])

    def test_search_default_does_not_match_title_only(self):
        # "Velocity" appears only in SAMPLE_CONV_C's title, not in keywords or topics
        results = self.db.search(['Velocity'], mode='and')
        self.assertEqual(results, [])

    def test_search_include_summary_finds_summary_match(self):
        results = self.db.search(['burndown'], mode='and', include_summary=True)
        self.assertIn(SAMPLE_CONV_C['id'], self._ids(results))

    def test_search_include_title_finds_title_match(self):
        results = self.db.search(['Velocity'], mode='and', include_title=True)
        self.assertIn(SAMPLE_CONV_C['id'], self._ids(results))

    def test_search_stem_matches_hyphenated_topic(self):
        # "estimate" (stem "estimat") should match topic "project-estimation" when topics included
        results = self.db.search(['estimate'], mode='and', include_topics=True)
        self.assertIn(SAMPLE_CONV_C['id'], self._ids(results))

    def test_search_stem_matches_hyphenated_keyword(self):
        # "sprint" (stem "sprin") should match keyword "sprint-planning"
        results = self.db.search(['sprint'], mode='and')
        self.assertIn(SAMPLE_CONV_C['id'], self._ids(results))


class TestDatabaseList(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()
        self.db.upsert_conversation(SAMPLE_CONV)
        self.db.upsert_conversation(SAMPLE_CONV_B)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ids(self, results):
        return {r['id'] for r in results}

    def test_list_conversations_returns_all(self):
        results = self.db.list_conversations()
        ids = self._ids(results)
        self.assertIn(SAMPLE_CONV['id'], ids)
        self.assertIn(SAMPLE_CONV_B['id'], ids)

    def test_list_conversations_with_topic_filter(self):
        results = self.db.list_conversations(topic='SQLite')
        ids = self._ids(results)
        self.assertIn(SAMPLE_CONV['id'], ids)
        self.assertNotIn(SAMPLE_CONV_B['id'], ids)

    def test_list_conversations_with_folder_filter(self):
        results = self.db.list_conversations(folder='/Users/alice/src/myapp')
        ids = self._ids(results)
        self.assertIn(SAMPLE_CONV['id'], ids)
        self.assertNotIn(SAMPLE_CONV_B['id'], ids)

    def test_list_conversations_with_keyword_filter_returns_matching(self):
        results = self.db.list_conversations(keyword='journal-mode')
        ids = self._ids(results)
        self.assertIn(SAMPLE_CONV['id'], ids)
        self.assertNotIn(SAMPLE_CONV_B['id'], ids)

    def test_list_conversations_with_keyword_filter_excludes_non_matching(self):
        results = self.db.list_conversations(keyword='rollback')
        ids = self._ids(results)
        self.assertIn(SAMPLE_CONV_B['id'], ids)
        self.assertNotIn(SAMPLE_CONV['id'], ids)


class TestDatabaseGetConversation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()
        self.db.upsert_conversation(SAMPLE_CONV)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_conversation_returns_correct_data(self):
        result = self.db.get_conversation(SAMPLE_CONV['id'])
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], SAMPLE_CONV['id'])
        self.assertEqual(result['title'], SAMPLE_CONV['title'])
        self.assertEqual(result['summary'], SAMPLE_CONV['summary'])

    def test_get_conversation_returns_none_for_missing(self):
        result = self.db.get_conversation('nonexistent-id')
        self.assertIsNone(result)


class TestDatabaseGetForReindex(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()
        self.db.upsert_conversation(SAMPLE_CONV)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_for_reindex_returns_keywords(self):
        result = self.db.get_for_reindex(SAMPLE_CONV['id'])

        self.assertIn('keywords', result)
        self.assertIsInstance(result['keywords'], list)
        for kw in SAMPLE_CONV['keywords']:
            self.assertIn(kw.lower(), [k.lower() for k in result['keywords']])

    def test_get_for_reindex_returns_empty_keywords_when_none_stored(self):
        conv = {k: v for k, v in SAMPLE_CONV.items() if k != 'keywords'}
        conv['id'] = 'no-keywords-session'
        self.db.upsert_conversation(conv)

        result = self.db.get_for_reindex('no-keywords-session')

        self.assertEqual(result['keywords'], [])


class TestDatabaseValidate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_validate_exits_with_1_when_db_missing(self):
        missing_path = os.path.join(self.tmpdir, 'nonexistent', 'catalog.db')
        db = Database(missing_path)
        with self.assertRaises(SystemExit) as ctx, open(os.devnull, 'w') as devnull:
            with unittest.mock.patch('sys.stderr', devnull):
                db.validate()
        self.assertEqual(ctx.exception.code, 1)


class TestMeta(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db = Database(os.path.join(self.tmpdir, 'catalog.db'))
        self.db.create_schema()

    def test_get_missing_is_none(self):
        self.assertIsNone(self.db.get_meta('x'))

    def test_set_then_get(self):
        self.db.set_meta('x', '1')
        self.assertEqual(self.db.get_meta('x'), '1')

    def test_set_overwrites(self):
        self.db.set_meta('x', '1')
        self.db.set_meta('x', '2')
        self.assertEqual(self.db.get_meta('x'), '2')


class TestArchiveSchema(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'catalog.db')
        self.db = Database(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _names(self, conn):
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _add_conv(self, conn, cid='c1'):
        conn.execute("INSERT INTO conversations (id, folder) VALUES (?, ?)", (cid, '/f'))

    def _add_msg(self, conn, text, cid='c1', seq=0):
        return conn.execute(
            "INSERT INTO messages (conversation_id, seq, role, text) VALUES (?, ?, 'user', ?)",
            (cid, seq, text)).lastrowid

    def _match(self, conn, term):
        return [r[0] for r in conn.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?", ('"%s"' % term,))]

    def test_create_schema_adds_archive_objects(self):
        self.db.create_schema()
        conn = self._conn()
        names = self._names(conn)
        for n in ('messages', 'messages_fts', 'forgotten', 'meta'):
            self.assertIn(n, names)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
        for c in ('tail_hash', 'source_path', 'archived', 'archived_message_count', 'repo_key'):
            self.assertIn(c, cols)
        self.assertIn('idx_conversations_repo_key', names)
        conn.close()

    def test_migration_from_legacy_db_is_idempotent(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE conversations (
              id TEXT PRIMARY KEY, folder TEXT NOT NULL, cwd TEXT, started_at TEXT,
              last_active TEXT, title TEXT, summary TEXT, message_count INTEGER,
              indexed_at TEXT NOT NULL DEFAULT (datetime('now')));
            CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL COLLATE NOCASE);
            CREATE TABLE conversation_topics (
              conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
              topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
              PRIMARY KEY (conversation_id, topic_id));
        """)
        conn.close()
        self.db.run_migrations()
        self.db.run_migrations()
        conn = self._conn()
        names = self._names(conn)
        for n in ('messages', 'messages_fts', 'forgotten', 'meta', 'idx_conversations_repo_key'):
            self.assertIn(n, names)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
        self.assertTrue({'tail_hash', 'source_path', 'archived',
                         'archived_message_count', 'repo_key'} <= cols)
        conn.close()

    def test_fts_triggers_track_insert_update_delete(self):
        self.db.create_schema()
        conn = self._conn()
        self._add_conv(conn)
        mid = self._add_msg(conn, "the TOWIT_INDEXING guard")
        self.assertEqual(self._match(conn, 'TOWIT_INDEXING'), [mid])
        conn.execute("UPDATE messages SET text='changed' WHERE id=?", (mid,))
        self.assertEqual(self._match(conn, 'TOWIT_INDEXING'), [])
        self.assertEqual(self._match(conn, 'changed'), [mid])
        conn.execute("DELETE FROM messages WHERE id=?", (mid,))
        self.assertEqual(self._match(conn, 'changed'), [])
        conn.close()

    def test_deleting_conversation_cascades_into_fts(self):
        self.db.create_schema()
        conn = self._conn()
        self._add_conv(conn)
        self._add_msg(conn, "the TOWIT_INDEXING guard")
        conn.commit()
        conn.execute("DELETE FROM conversations WHERE id='c1'")
        self.assertEqual(self._match(conn, 'TOWIT_INDEXING'), [])
        self.assertEqual(conn.execute("SELECT count(*) FROM messages").fetchone()[0], 0)
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('integrity-check')")
        conn.close()

    def test_unique_conversation_seq(self):
        self.db.create_schema()
        conn = self._conn()
        self._add_conv(conn)
        self._add_msg(conn, "a", seq=0)
        with self.assertRaises(sqlite3.IntegrityError):
            self._add_msg(conn, "b", seq=0)
        conn.close()

    def test_identifier_tokenizes_whole(self):
        self.db.create_schema()
        conn = self._conn()
        self._add_conv(conn)
        mid = self._add_msg(conn, "call reindex_delta then TOWIT_INDEXING now")
        self.assertEqual(self._match(conn, 'reindex_delta'), [mid])
        self.assertEqual(self._match(conn, 'TOWIT_INDEXING'), [mid])
        self.assertEqual(self._match(conn, 'reindex'), [])
        conn.close()


class TestArchiveSession(unittest.TestCase):
    CONV = {
        'id': 'arc-1', 'folder': '/f', 'cwd': '/w', 'started_at': '2026-01-01T00:00:00Z',
        'last_active': '2026-01-01T01:00:00Z', 'repo_key': 'repo', 'source_path': '/p/arc-1.jsonl',
    }

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'catalog.db')
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _msgs(self, n, prefix='m'):
        return [{'role': 'user' if i % 2 == 0 else 'assistant',
                 'ts': '2026-01-01T00:0%d:00Z' % i, 'text': '%s%d' % (prefix, i)} for i in range(n)]

    def _rows(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT seq, role, ts, text FROM messages WHERE conversation_id='arc-1' ORDER BY seq"
        ).fetchall()
        conn.close()
        return rows

    def _conv_row(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM conversations WHERE id='arc-1'").fetchone()
        conn.close()
        return row

    def _fts(self, term):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?",
                            ('"%s"' % term,)).fetchall()
        conn.close()
        return rows

    def _fts_consistent(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('integrity-check')")
        conn.close()

    def test_message_hash_is_sha256_of_role_nul_text(self):
        import hashlib
        self.assertEqual(message_hash('user', 'hi'),
                         hashlib.sha256(b'user\x00hi').hexdigest())

    def test_forgotten_session_not_archived(self):
        with self.db.connect() as conn:
            conn.execute("INSERT INTO forgotten (id) VALUES (?)", (self.CONV['id'],))
        self.assertEqual(self.db.archive_session(dict(self.CONV), self._msgs(2)), 'forgotten')
        self.assertIsNone(self._conv_row())
        self.assertEqual(self._rows(), [])

    def test_first_call_ingests(self):
        msgs = self._msgs(3)
        self.assertEqual(self.db.archive_session(dict(self.CONV), msgs), 'ingested')
        self.assertEqual([r[0] for r in self._rows()], [0, 1, 2])
        row = self._conv_row()
        self.assertEqual(row['archived'], 1)
        self.assertEqual(row['archived_message_count'], 3)
        self.assertEqual(row['tail_hash'], message_hash('user', 'm2'))
        self.assertEqual(row['repo_key'], 'repo')
        self.assertEqual(row['source_path'], '/p/arc-1.jsonl')
        self.assertIsNone(row['title'])
        self.assertIsNone(row['summary'])

    def test_same_messages_unchanged(self):
        msgs = self._msgs(3)
        self.db.archive_session(dict(self.CONV), msgs)
        self.assertEqual(self.db.archive_session(dict(self.CONV), msgs), 'unchanged')
        self.assertEqual(len(self._rows()), 3)

    def test_extra_messages_append(self):
        self.db.archive_session(dict(self.CONV), self._msgs(3))
        self.assertEqual(self.db.archive_session(dict(self.CONV), self._msgs(5)), 'appended')
        rows = self._rows()
        self.assertEqual([r[0] for r in rows], [0, 1, 2, 3, 4])
        self.assertEqual(self._conv_row()['archived_message_count'], 5)
        self.assertEqual(self._conv_row()['tail_hash'], message_hash('user', 'm4'))

    def test_same_count_different_tail_rewrites(self):
        self.db.archive_session(dict(self.CONV), self._msgs(3))
        new = self._msgs(3)
        new[2]['text'] = 'different tail'
        self.assertEqual(self.db.archive_session(dict(self.CONV), new), 'rewritten')
        self.assertEqual([r[3] for r in self._rows()], ['m0', 'm1', 'different tail'])
        self.assertEqual(self._conv_row()['tail_hash'], message_hash('user', 'different tail'))

    def test_fewer_messages_with_different_content_rewrites(self):
        self.db.archive_session(dict(self.CONV), self._msgs(4))
        self.assertEqual(self.db.archive_session(dict(self.CONV), self._msgs(2, 'x')), 'rewritten')
        self.assertEqual([r[0] for r in self._rows()], [0, 1])
        self.assertEqual(self._conv_row()['archived_message_count'], 2)

    def test_older_shorter_snapshot_of_a_longer_archive_is_unchanged(self):
        early = self._msgs(6)
        self.db.archive_session(dict(self.CONV), early)
        self.db.archive_session(dict(self.CONV), self._msgs(8))
        before = self._conv_row()
        conv = dict(self.CONV, last_active='2026-03-03T00:00:00Z')
        self.assertEqual(self.db.archive_session(conv, early), 'unchanged')
        rows = self._rows()
        self.assertEqual([r[0] for r in rows], list(range(8)))
        after = self._conv_row()
        self.assertEqual(after['archived_message_count'], 8)
        self.assertEqual(after['tail_hash'], message_hash('assistant', 'm7'))
        self.assertEqual(after['last_active'], before['last_active'])
        self._fts_consistent()

    def test_genuine_rewind_with_different_tail_still_rewrites(self):
        self.db.archive_session(dict(self.CONV), self._msgs(8))
        rewound = self._msgs(6)
        rewound[5]['text'] = 'compacted tail'
        self.assertEqual(self.db.archive_session(dict(self.CONV), rewound), 'rewritten')
        self.assertEqual([r[3] for r in self._rows()][-1], 'compacted tail')
        self.assertEqual(len(self._rows()), 6)
        self.assertEqual(self._conv_row()['archived_message_count'], 6)

    def test_llm_metadata_survives_all_outcomes(self):
        self.db.upsert_conversation({
            'id': 'arc-1', 'folder': '/f', 'cwd': '/w', 'started_at': None,
            'last_active': None, 'title': 'T', 'summary': 'S', 'message_count': 7,
            'topics': ['Topic A'], 'keywords': ['kw-one']})
        steps = [self._msgs(3), self._msgs(3), self._msgs(5), self._msgs(2, 'x')]
        for msgs in steps:
            self.db.archive_session(dict(self.CONV), msgs)
            row = self._conv_row()
            self.assertEqual((row['title'], row['summary'], row['message_count']), ('T', 'S', 7))
            conn = sqlite3.connect(self.db_path)
            self.assertEqual(conn.execute("SELECT count(*) FROM conversation_topics").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM conversation_keywords").fetchone()[0], 1)
            conn.close()

    def test_conversation_metadata_updated_but_repo_key_kept(self):
        self.db.archive_session(dict(self.CONV), self._msgs(2))
        conv = dict(self.CONV, last_active='2026-02-02T00:00:00Z', cwd='/new', repo_key='r2')
        self.db.archive_session(conv, self._msgs(2))
        row = self._conv_row()
        self.assertEqual((row['last_active'], row['cwd'], row['repo_key']),
                         ('2026-02-02T00:00:00Z', '/new', self.CONV['repo_key']))  # key resolved once

    def test_fts_finds_appended_and_drops_rewritten_text(self):
        self.db.archive_session(dict(self.CONV), self._msgs(2, 'alpha'))
        self.db.archive_session(dict(self.CONV), self._msgs(3, 'alpha') )
        self.assertEqual(len(self._fts('alpha2')), 1)
        self.db.archive_session(dict(self.CONV), self._msgs(1, 'beta'))
        self.assertEqual(self._fts('alpha2'), [])
        self.assertEqual(self._fts('alpha1'), [])
        self.assertEqual(len(self._fts('beta0')), 1)
        self._fts_consistent()

    def test_failed_write_rolls_back_everything(self):
        self.db.archive_session(dict(self.CONV), self._msgs(3))
        before_rows = self._rows()
        before_conv = dict(self._conv_row())
        bad = self._msgs(2, 'new')
        bad.append({'role': 'bogus', 'ts': None, 'text': 'boom'})  # violates CHECK mid-write
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.archive_session(dict(self.CONV, last_active='later'), bad)
        self.assertEqual(self._rows(), before_rows)
        self.assertEqual(dict(self._conv_row()), before_conv)
        self.assertEqual(len(self._fts('m1')), 1)
        self.assertEqual(self._fts('new0'), [])
        self._fts_consistent()

    def test_is_forgotten(self):
        self.assertFalse(self.db.is_forgotten('arc-1'))
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO forgotten (id) VALUES ('arc-1')")
        conn.commit()
        conn.close()
        self.assertTrue(self.db.is_forgotten('arc-1'))


class TestBuildMatchExpression(unittest.TestCase):
    def test_single_phrase(self):
        self.assertEqual(build_match_expression(['stop hook']), '"stop hook"')

    def test_and_join_default(self):
        self.assertEqual(build_match_expression(['a', 'b']), '"a" AND "b"')

    def test_or_join(self):
        self.assertEqual(build_match_expression(['a', 'b'], 'or'), '"a" OR "b"')

    def test_embedded_quote_doubled(self):
        self.assertEqual(build_match_expression(['a"b']), '"a""b"')

    def test_untokenizable_returns_none(self):
        for terms in (['"'], ['***'], [], ['  '], ['"', '*']):
            self.assertIsNone(build_match_expression(terms), terms)

    def test_untokenizable_terms_dropped_when_others_remain(self):
        self.assertEqual(build_match_expression(['***', 'ok']), '"ok"')


class TestRepoFilter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, 't.db'))
        self.db.create_schema()
        for i, key in enumerate(['/src/acme/webapp', '/src/other/webapp', '/src/acme/web',
                                 '/src/acme/we_app', '/src/acme/50%', None]):
            self.db.archive_session({'id': 'c%d' % i, 'folder': '/f', 'cwd': '/w',
                                     'started_at': None, 'last_active': None,
                                     'repo_key': key, 'source_path': None}, [])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _match(self, repo, col='c.repo_key'):
        sql, params = self.db._repo_filter(repo, col)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT c.repo_key FROM conversations c WHERE " + sql + " ORDER BY c.id", params
            ).fetchall()
        return [r[0] for r in rows]

    def test_exact_key(self):
        self.assertEqual(self._match('/src/acme/webapp'), ['/src/acme/webapp'])

    def test_basename_matches_every_repo_with_that_name(self):
        self.assertEqual(self._match('webapp'), ['/src/acme/webapp', '/src/other/webapp'])

    def test_basename_is_not_a_suffix_of_component(self):
        self.assertEqual(self._match('app'), [])

    def test_wildcards_match_nothing_extra(self):
        for arg in ('web%', 'web_pp', '%', '_', '\\'):
            self.assertEqual(self._match(arg), [], arg)
        self.assertEqual(self._match('we_app'), ['/src/acme/we_app'])
        self.assertEqual(self._match('50%'), ['/src/acme/50%'])

    def test_trailing_slash_ignored(self):
        self.assertEqual(self._match('/src/acme/webapp/'), ['/src/acme/webapp'])
        self.assertEqual(self._match('webapp/'), ['/src/acme/webapp', '/src/other/webapp'])

    def test_empty_matches_nothing(self):
        self.assertEqual(self._match(''), [])

    def test_custom_column(self):
        sql, params = self.db._repo_filter('webapp', 'x.k')
        self.assertIn('x.k', sql)
        self.assertNotIn('c.repo_key', sql)

    def test_fully_parameterized(self):
        sql, params = self.db._repo_filter("x'; DROP TABLE conversations; --")
        self.assertNotIn('DROP', sql)
        self.assertEqual(sql.count('?'), len(params))


class _FailingMatchConn:
    """Connection proxy that raises a chosen OperationalError for FTS MATCH queries."""
    def __init__(self, conn, message):
        self.conn, self.message = conn, message

    def execute(self, sql, *args):
        if 'MATCH' in sql:
            raise sqlite3.OperationalError(self.message)
        return self.conn.execute(sql, *args)


class TestSearchArchive(unittest.TestCase):
    def _conv(self, cid, cwd='/w/app', repo='/src/app', started='2026-01-01T00:00:00Z'):
        return {'id': cid, 'folder': '/f', 'cwd': cwd, 'started_at': started,
                'last_active': started, 'repo_key': repo, 'source_path': None}

    def _m(self, role, text):
        return {'role': role, 'ts': None, 'text': text}

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 't.db')
        self.db = Database(self.db_path)
        self.db.create_schema()
        # s1: text-only hit in an assistant turn (seq 3), no metadata
        self.db.archive_session(self._conv('s1', started='2026-01-01T00:00:00Z'), [
            self._m('user', 'how do hooks work?'), self._m('assistant', 'they run'),
            self._m('user', 'and recursion?'),
            self._m('assistant', 'The recursion guard stops the stop hook from re-entering.')])
        # s2: keyword metadata match plus a text hit
        self.db.archive_session(self._conv('s2', cwd='/w/other', repo='/src/other',
                                           started='2026-01-02T00:00:00Z'), [
            self._m('user', 'unrelated'), self._m('assistant', 'recursion')])
        self.db.upsert_conversation({
            'id': 's2', 'folder': '/f', 'cwd': '/w/other', 'started_at': '2026-01-02T00:00:00Z',
            'last_active': '2026-01-02T00:00:00Z', 'title': 'Other title', 'summary': 'sum',
            'topics': ['misc'], 'keywords': ['recursion-guard']})
        # s3: metadata-only (keyword), no matching text
        self.db.archive_session(self._conv('s3', started='2026-01-03T00:00:00Z'), [
            self._m('user', 'first user words'), self._m('assistant', 'ok')])
        self.db.upsert_conversation({
            'id': 's3', 'folder': '/f', 'cwd': '/w/app', 'started_at': '2026-01-03T00:00:00Z',
            'last_active': '2026-01-03T00:00:00Z', 'title': 'T3', 'summary': 'sum3',
            'topics': [], 'keywords': ['recursion']})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ids(self, results):
        return [r['id'] for r in results]

    def test_hostile_terms_return_list_and_do_not_raise(self):
        for t in ['"', '*', 'NEAR(', 'AND', 'OR', 'NOT', 'a"b', '"unbalanced', ')', '^x', 'col:x', "'"]:
            for scope in ('all', 'text'):
                self.assertIsInstance(self.db.search_archive([t], scope=scope), list, t)

    def test_untokenizable_term_returns_empty(self):
        self.assertEqual(self.db.search_archive(['***'], scope='text'), [])

    def test_text_hit_has_snippet_and_seq(self):
        res = self.db.search_archive(['guard'], scope='text')
        self.assertEqual(self._ids(res), ['s1'])
        self.assertEqual(res[0]['seq'], 3)
        self.assertIn('[guard]', res[0]['snippet'])
        self.assertIsInstance(res[0]['score'], float)

    def test_phrase_argument_is_exact_vs_and(self):
        self.assertEqual(self._ids(self.db.search_archive(['stop hook'], scope='text')), ['s1'])
        self.assertEqual(self.db.search_archive(['hook stop'], scope='text'), [])
        self.assertEqual(self._ids(self.db.search_archive(['hook', 'stop'], scope='text')), ['s1'])

    def test_or_mode(self):
        res = self.db.search_archive(['guard', 'unrelated'], mode='or', scope='text')
        self.assertEqual(set(self._ids(res)), {'s1', 's2'})

    def test_tiering_metadata_above_text_only(self):
        res = self.db.search_archive(['recursion'])
        ids = self._ids(res)
        self.assertEqual(set(ids), {'s1', 's2', 's3'})
        self.assertEqual(ids[-1], 's1')  # text-only ranks last
        by = {r['id']: r for r in res}
        self.assertEqual(by['s2']['seq'], 1)  # metadata + text keeps its text hit
        self.assertIsNotNone(by['s2']['score'])
        self.assertIsNone(by['s3']['seq'])
        self.assertIsNone(by['s3']['score'])
        self.assertEqual(by['s3']['snippet'], '')

    def test_scope_text_ignores_metadata(self):
        self.assertEqual(self.db.search_archive(['recursion-guard'], scope='text'), [])

    def test_scope_metadata_reproduces_old_search(self):
        old = self.db.search(['recursion'], mode='and', include_keywords=True)
        new = self.db.search_archive(['recursion'], scope='metadata')
        self.assertEqual([{k: r[k] for k in old[0]} for r in new], old)

    def test_include_flags_apply_to_metadata_side(self):
        self.assertNotIn('s3', self._ids(self.db.search_archive(['sum3'], scope='metadata')))
        self.assertIn('s3', self._ids(self.db.search_archive(['sum3'], scope='metadata',
                                                             include_summary=True)))

    def test_one_result_per_conversation(self):
        self.db.archive_session(self._conv('s4'), [self._m('user', 'dup'),
                                                   self._m('assistant', 'dup dup')])
        self.assertEqual(self._ids(self.db.search_archive(['dup'], scope='text')), ['s4'])

    def test_repo_filter_exact_and_basename(self):
        self.assertEqual(set(self._ids(self.db.search_archive(['recursion'], repo='/src/other'))), {'s2'})
        self.assertEqual(set(self._ids(self.db.search_archive(['recursion'], repo='app'))), {'s1', 's3'})
        self.assertEqual(self.db.search_archive(['recursion'], repo='app%'), [])
        self.assertEqual(self._ids(self.db.search_archive(['recursion'], repo='other', scope='metadata')), ['s2'])

    def test_folder_filter(self):
        self.assertEqual(set(self._ids(self.db.search_archive(['recursion'], folder='/w/app'))), {'s1', 's3'})

    def test_null_title_falls_back_to_first_user_message_80_chars(self):
        self.assertEqual(self.db.search_archive(['guard'], scope='text')[0]['title'], 'how do hooks work?')
        self.db.archive_session(self._conv('s5'), [self._m('assistant', 'zzq first'),
                                                   self._m('user', 'u' * 200)])
        self.assertEqual(self.db.search_archive(['zzq'], scope='text')[0]['title'], 'u' * 80)

    def test_existing_title_kept(self):
        res = self.db.search_archive(['recursion'])
        self.assertEqual({r['id']: r['title'] for r in res}['s2'], 'Other title')

    def test_forgotten_session_not_resurrected(self):
        with self.db.connect() as conn:
            conn.execute("INSERT INTO forgotten (id) VALUES ('s1')")
            conn.execute("DELETE FROM conversations WHERE id = 's1'")
        self.assertNotIn('s1', self._ids(self.db.search_archive(['guard'])))
        self.assertEqual(self.db.search_archive(['guard'], scope='text'), [])

    def test_limit(self):
        # limit caps text-only rows; both metadata hits (s2, s3) are kept
        self.assertEqual(set(self._ids(self.db.search_archive(['recursion'], limit=1))), {'s2', 's3', 's1'})

    def _with_failing_match(self, message):
        real_connect = Database.connect

        @contextlib.contextmanager
        def connect(db):
            with real_connect(db) as conn:
                yield _FailingMatchConn(conn, message)
        return unittest.mock.patch.object(Database, 'connect', connect)

    def test_other_operational_errors_propagate(self):
        with self._with_failing_match('database is locked'):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.search_archive(['guard'], scope='text')

    def test_fts_query_errors_return_empty(self):
        for msg in ('fts5: syntax error near "x"', 'unterminated string',
                    'no such column: foo', 'unknown special query: '):
            with self._with_failing_match(msg):
                self.assertEqual(self.db.search_archive(['guard'], scope='text'), [], msg)

    def test_non_fts_syntax_error_propagates(self):
        with self._with_failing_match('near "X": syntax error'):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.search_archive(['guard'], scope='text')

    def test_real_sqlite_fts_error_forms_are_recognised(self):
        # Guard against SQLite changing its messages: provoke each form unquoted.
        with self.db.connect() as conn:
            for bad in ('a AND', '"abc', 'foo:bar', '*'):
                with self.assertRaises(sqlite3.OperationalError) as cm:
                    conn.execute("SELECT 1 FROM messages_fts WHERE messages_fts MATCH ?", (bad,))
                self.assertTrue(is_fts_query_error(cm.exception), str(cm.exception))

    def test_limit_caps_only_text_only_rows(self):
        for i in range(5):
            self.db.upsert_conversation({
                'id': 'k%d' % i, 'folder': '/f', 'cwd': '/w/k', 'started_at': '2026-02-0%dT00:00:00Z' % (i + 1),
                'last_active': None, 'title': 't', 'summary': 's', 'topics': [], 'keywords': ['capkw']})
        for i in range(3):
            self.db.archive_session(self._conv('x%d' % i, started='2026-04-0%dT00:00:00Z' % (i + 1)),
                                    [self._m('user', 'q'), self._m('assistant', 'capkw text')])
        res = self.db.search_archive(['capkw'], limit=2)
        ids = self._ids(res)
        self.assertEqual(len([i for i in ids if i.startswith('k')]), 5)  # all metadata kept
        text_only = [i for i in ids if i.startswith('x')]
        self.assertEqual(len(text_only), 2)  # capped
        self.assertTrue(all(i.startswith('k') for i in ids[:5]))  # metadata tier first

    def test_metadata_overflow_plus_one_text_hit(self):
        for i in range(60):
            self.db.upsert_conversation({
                'id': 'm%02d' % i, 'folder': '/f', 'cwd': '/w/k', 'started_at': None,
                'last_active': None, 'title': 't', 'summary': 's', 'topics': [], 'keywords': ['overflowkw']})
        self.db.archive_session(self._conv('tx'), [self._m('user', 'q'),
                                                   self._m('assistant', 'overflowkw here')])
        res = self.db.search_archive(['overflowkw'])  # default limit 50
        self.assertEqual(len(res), 61)
        self.assertEqual(res[-1]['id'], 'tx')

    def test_ties_ordered_deterministically_by_started_at_then_id(self):
        for cid in ('t3', 't1', 't2'):
            self.db.upsert_conversation({
                'id': cid, 'folder': '/f', 'cwd': '/w/k', 'started_at': '2026-05-01T00:00:00Z',
                'last_active': None, 'title': 't', 'summary': 's', 'topics': [], 'keywords': ['tiekw']})
        first = self._ids(self.db.search_archive(['tiekw'], scope='metadata'))
        order = self._ids(self.db.search_archive(['tiekw']))
        self.assertEqual(order, ['t1', 't2', 't3'])
        self.assertEqual(sorted(first), ['t1', 't2', 't3'])

    def test_query_plan_uses_fts_index(self):
        sql, params = self.db._text_match_query(None, None)
        with self.db.connect() as conn:
            plan = ' '.join(r[3] for r in conn.execute(
                'EXPLAIN QUERY PLAN ' + sql, ['"guard"'] + params))
        self.assertIn('messages_fts', plan)
        self.assertNotRegex(plan, r'SCAN (TABLE )?m\b|SCAN TABLE messages\b')


# The catalog DDL as it existed before the archive work: no archive columns, no
# messages/messages_fts/forgotten/meta, user_version 0.
OLD_SCHEMA = """
CREATE TABLE conversations (
  id TEXT PRIMARY KEY, folder TEXT NOT NULL, cwd TEXT, started_at TEXT,
  last_active TEXT, title TEXT, summary TEXT, message_count INTEGER,
  indexed_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL COLLATE NOCASE);
CREATE TABLE conversation_topics (
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  PRIMARY KEY (conversation_id, topic_id));
CREATE TABLE keywords (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL COLLATE NOCASE);
CREATE TABLE conversation_keywords (
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
  PRIMARY KEY (conversation_id, keyword_id));
CREATE INDEX idx_conversations_started ON conversations(started_at DESC);
CREATE INDEX idx_conversations_cwd ON conversations(cwd);
CREATE INDEX idx_ct_topic ON conversation_topics(topic_id);
CREATE INDEX idx_ct_conv ON conversation_topics(conversation_id);
CREATE INDEX idx_ck_keyword ON conversation_keywords(keyword_id);
CREATE INDEX idx_ck_conv ON conversation_keywords(conversation_id);
INSERT INTO conversations (id, folder, cwd, title, summary, message_count)
  VALUES ('old-1', '/f', '/w/app', 'Old title', 'Old summary', 4);
INSERT INTO topics (name) VALUES ('legacy-topic');
INSERT INTO conversation_topics VALUES ('old-1', 1);
INSERT INTO keywords (name) VALUES ('legacy-kw');
INSERT INTO conversation_keywords VALUES ('old-1', 1);
"""


def build_old_schema_db(path):
    """Create a pre-archive catalog (mode 0600, user_version 0) with one row."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(OLD_SCHEMA)
    conn.close()
    os.chmod(path, 0o600)


class TestAutoMigration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = os.path.join(self.tmpdir, 'old.db')
        build_old_schema_db(self.db_path)
        self.db = Database(self.db_path)

    def _q(self, sql):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def _names(self):
        return {r[0] for r in self._q("SELECT name FROM sqlite_master")}

    def test_old_db_starts_at_version_zero(self):
        self.assertEqual(self.db.schema_version(), 0)
        self.assertNotIn('messages', self._names())

    def test_validate_migrates_old_db(self):
        before = self._q("SELECT * FROM conversations")
        self.db.validate()
        names = self._names()
        for n in ('messages', 'messages_fts', 'forgotten', 'meta', 'messages_ai',
                  'messages_ad', 'messages_au', 'idx_conversations_repo_key'):
            self.assertIn(n, names)
        cols = {r[1] for r in self._q("PRAGMA table_info(conversations)")}
        self.assertTrue({'tail_hash', 'source_path', 'archived',
                         'archived_message_count', 'repo_key'} <= cols)
        self.assertEqual(self.db.schema_version(), SCHEMA_VERSION)
        self.assertEqual(self._q("PRAGMA integrity_check"), [('ok',)])
        row = self._q("SELECT id, title, summary, message_count FROM conversations")
        self.assertEqual(row, [('old-1', 'Old title', 'Old summary', 4)])
        self.assertEqual(len(before), 1)
        self.assertEqual(self._q("SELECT conversation_id, topic_id FROM conversation_topics"),
                         [('old-1', 1)])

    def test_migration_does_not_change_permissions_or_print(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.db.validate()
        self.assertEqual(out.getvalue() + err.getvalue(), '')
        self.assertEqual(os.stat(self.db_path).st_mode & 0o777, 0o600)

    def test_current_db_does_not_migrate(self):
        self.db.validate()
        with unittest.mock.patch.object(Database, 'run_migrations') as mig:
            self.db.validate()
            Database(self.db_path).validate()
        mig.assert_not_called()

    def test_fresh_db_is_stamped_and_not_remigrated(self):
        fresh = Database(os.path.join(self.tmpdir, 'fresh.db'))
        fresh.create_schema()
        self.assertEqual(fresh.schema_version(), SCHEMA_VERSION)
        with unittest.mock.patch.object(Database, 'run_migrations') as mig:
            fresh.validate()
        mig.assert_not_called()

    def test_run_migrations_stamps_version(self):
        self.db.run_migrations()
        self.assertEqual(self.db.schema_version(), SCHEMA_VERSION)

    def test_newer_db_is_left_alone(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = %d" % (SCHEMA_VERSION + 5))
        conn.close()
        with unittest.mock.patch.object(Database, 'run_migrations') as mig:
            self.db.validate()
        mig.assert_not_called()
        self.assertEqual(self.db.schema_version(), SCHEMA_VERSION + 5)
        self.assertNotIn('messages', self._names())

    def test_run_migrations_never_downgrades_stamp(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = %d" % (SCHEMA_VERSION + 5))
        conn.close()
        self.db.run_migrations()
        self.assertEqual(self.db.schema_version(), SCHEMA_VERSION + 5)

    def _assert_not_migrated(self):
        self.assertEqual(self.db.schema_version(), 0)
        cols = {r[1] for r in self._q("PRAGMA table_info(conversations)")}
        self.assertNotIn('tail_hash', cols)  # earlier ALTERs rolled back too
        self.assertNotIn('zz', self._names())

    def test_failed_migration_propagates_and_leaves_version_unchanged(self):
        ddl = '\nCREATE TABLE zz(a);\nCREATE TABLE messages (;'
        with unittest.mock.patch.object(towit_db, 'ARCHIVE_DDL', ddl):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.validate()
        self._assert_not_migrated()

    @contextlib.contextmanager
    def _proxied_connect(self, execute=None, after_migration=None):
        """Patch Database.connect to hand out a wrapper around the real connection."""
        real_connect = Database.connect

        class Proxy:
            def __init__(self, conn):
                self._c = conn

            def __getattr__(self, name):
                return getattr(self._c, name)

            def execute(self, sql, *a):
                if execute:
                    execute(sql)
                return self._c.execute(sql, *a)

        @contextlib.contextmanager
        def fake(db):
            with real_connect(db) as conn:
                yield Proxy(conn)

        with unittest.mock.patch.object(Database, 'connect', fake):
            yield

    def test_non_duplicate_alter_error_propagates_and_is_not_stamped(self):
        def boom(sql):
            if 'ADD COLUMN source_path' in sql:
                raise sqlite3.OperationalError('disk I/O error')

        with self._proxied_connect(execute=boom):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.validate()
        self._assert_not_migrated()

    def test_transaction_lost_before_stamp_is_not_stamped(self):
        real = towit_db._execute_script

        def script_then_autorollback(conn, script):
            real(conn, script)
            if 'messages_fts' in script:  # the final step
                conn._c.rollback()  # what SQLite does itself on SQLITE_FULL / IOERR

        with unittest.mock.patch.object(towit_db, '_execute_script', script_then_autorollback):
            with self._proxied_connect():
                with self.assertRaises(RuntimeError):
                    self.db.validate()
        self._assert_not_migrated()

    def test_stale_recheck_under_lock_runs_no_ddl_on_stamped_db(self):
        self.db.validate()
        before = self._q("SELECT type, name, sql FROM sqlite_master ORDER BY name")
        with unittest.mock.patch.object(towit_db, '_execute_script') as script:
            def no_alter(sql):
                self.assertNotIn('ALTER', sql)
            with self._proxied_connect(execute=no_alter):
                self.db.run_migrations(only_if_stale=True)
        script.assert_not_called()
        self.assertEqual(self._q("SELECT type, name, sql FROM sqlite_master ORDER BY name"), before)
        self.assertEqual(self.db.schema_version(), SCHEMA_VERSION)

    def test_concurrent_validate_calls_both_succeed(self):
        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait()
                Database(self.db_path).validate()
            except BaseException as exc:  # noqa: BLE001 - surface any failure
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.db.schema_version(), SCHEMA_VERSION)
        self.assertEqual(self._q("PRAGMA integrity_check"), [('ok',)])
        self.assertIn('messages_fts', self._names())

    def test_missing_file_still_exits_without_creating_anything(self):
        missing = os.path.join(self.tmpdir, 'sub', 'nope.db')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                Database(missing).validate()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn('database not found', err.getvalue())
        self.assertFalse(os.path.exists(missing))
        self.assertFalse(os.path.exists(os.path.dirname(missing)))

    def test_archive_session_migrates_old_db(self):
        out = Database(self.db_path).archive_session(
            {'id': 'n-1', 'folder': '/f', 'cwd': '/w', 'started_at': None,
             'last_active': None, 'repo_key': '/w', 'source_path': None},
            [{'role': 'user', 'ts': None, 'text': 'hello zebra'},
             {'role': 'assistant', 'ts': None, 'text': 'hi'}])
        self.assertEqual(out, 'ingested')


class TestRepoKeyKeptOnReingest(unittest.TestCase):
    """repo_key is resolved once at first ingest; a later ingest must not replace it."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Database(os.path.join(self.tmpdir, 'catalog.db'))
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _conv(self, repo_key):
        return {'id': 'rk-session-1', 'folder': '/f', 'cwd': '/wt/feature',
                'started_at': None, 'last_active': None,
                'repo_key': repo_key, 'source_path': '/f/rk-session-1.jsonl'}

    def _msgs(self, n=2):
        return [{'role': 'user', 'ts': None, 'text': f'm{i}'} for i in range(n)]

    def _stored_key(self):
        with self.db.connect() as conn:
            return conn.execute("SELECT repo_key FROM conversations WHERE id = 'rk-session-1'"
                                ).fetchone()['repo_key']

    def test_reingest_keeps_stored_key(self):
        self.db.archive_session(self._conv('/repo/main'), self._msgs(2))
        self.db.archive_session(self._conv('/wt/feature'), self._msgs(3))  # worktree gone: fell back to cwd
        self.assertEqual(self._stored_key(), '/repo/main')

    def test_null_stored_key_is_filled(self):
        self.db.archive_session(self._conv(None), self._msgs(2))
        self.assertIsNone(self._stored_key())
        self.db.archive_session(self._conv('/repo/main'), self._msgs(2))
        self.assertEqual(self._stored_key(), '/repo/main')

    def test_empty_stored_key_is_filled(self):
        self.db.archive_session(self._conv(''), self._msgs(2))
        self.assertEqual(self._stored_key(), '')
        self.db.archive_session(self._conv('/repo/main'), self._msgs(2))
        self.assertEqual(self._stored_key(), '/repo/main')

    def test_get_repo_key(self):
        self.assertIsNone(self.db.get_repo_key('rk-session-1'))
        self.db.archive_session(self._conv('/repo/main'), self._msgs(2))
        self.assertEqual(self.db.get_repo_key('rk-session-1'), '/repo/main')

    def test_first_ingest_stores_given_key(self):
        self.db.archive_session(self._conv('/wt/feature'), self._msgs(2))
        self.assertEqual(self._stored_key(), '/wt/feature')


if __name__ == '__main__':
    unittest.main()
