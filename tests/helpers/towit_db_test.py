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
    'topics': ['SQLite', 'WAL mode', 'database concurrency']
}

SAMPLE_CONV_B = {
    'id': 'test-session-002',
    'folder': '/home/user/.claude/projects/-Users-alice',
    'cwd': '/Users/alice/src/otherapp',
    'started_at': '2026-01-16T09:00:00Z',
    'last_active': '2026-01-16T09:45:00Z',
    'title': 'Rails migration strategies',
    'summary': 'Discussed various Rails migration strategies.',
    'topics': ['Rails', 'migrations']
}

# Has a unique word only in summary/title, and a hyphenated topic for stem-match testing
SAMPLE_CONV_C = {
    'id': 'test-session-003',
    'folder': '/home/user/.claude/projects/-Users-alice',
    'cwd': '/Users/alice/src/otherapp',
    'started_at': '2026-01-17T08:00:00Z',
    'last_active': '2026-01-17T08:30:00Z',
    'title': 'Velocity estimation for Q2',
    'summary': 'Reviewed burndown charts and story-point estimation for the quarter.',
    'topics': ['project-estimation', 'agile']
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
        # Only one unique (case-insensitive) topic entry expected
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

    def test_search_default_does_not_match_summary_only(self):
        # "burndown" appears only in SAMPLE_CONV_C's summary, not in any topic
        results = self.db.search(['burndown'], mode='and')
        self.assertEqual(results, [])

    def test_search_default_does_not_match_title_only(self):
        # "Velocity" appears only in SAMPLE_CONV_C's title, not in any topic
        results = self.db.search(['Velocity'], mode='and')
        self.assertEqual(results, [])

    def test_search_include_summary_finds_summary_match(self):
        results = self.db.search(['burndown'], mode='and', include_summary=True)
        self.assertIn(SAMPLE_CONV_C['id'], self._ids(results))

    def test_search_include_title_finds_title_match(self):
        results = self.db.search(['Velocity'], mode='and', include_title=True)
        self.assertIn(SAMPLE_CONV_C['id'], self._ids(results))

    def test_search_stem_matches_hyphenated_topic(self):
        # "estimate" (stem "estimat") should match topic "project-estimation"
        results = self.db.search(['estimate'], mode='and')
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


if __name__ == '__main__':
    unittest.main()
