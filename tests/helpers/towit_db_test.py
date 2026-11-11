# tests/helpers/towit_db_test.py
# Tests for libexec/towit/towit_db.py
#
# Run with: python3 tests/helpers/towit_db_test.py

import unittest
import unittest.mock
import tempfile
import shutil
import sqlite3
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)

from towit_db import Database

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


if __name__ == '__main__':
    unittest.main()
