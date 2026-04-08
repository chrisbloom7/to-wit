# tests/helpers/towit_search_test.py
# Tests for libexec/towit/towit_search.py
#
# Run with: python3 tests/helpers/towit_search_test.py

import unittest
import tempfile
import shutil
import subprocess
import csv
import io
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
SEARCH_SCRIPT = os.path.join(HELPERS_DIR, 'towit_search.py')

sys.path.insert(0, HELPERS_DIR)
from towit_db import Database


def write_config(tmpdir, db_path):
    """Write a minimal config.toml containing db_path. Returns config file path."""
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_search(config_path, args):
    return subprocess.run(
        ['python3', SEARCH_SCRIPT] + args,
        env={**os.environ, 'TOWIT_CONFIG_PATH': config_path},
        capture_output=True,
        text=True
    )


class TestTowitSearch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.myapp_dir = os.path.join(self.tmpdir, 'myapp')
        self.otherapp_dir = os.path.join(self.tmpdir, 'otherapp')
        os.makedirs(self.myapp_dir)
        os.makedirs(self.otherapp_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        db.upsert_conversation({
            'id': 'conv-a',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.myapp_dir,
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'SQLite WAL mode deep dive',
            'summary': 'Deep dive into SQLite WAL mode',
            'topics': ['SQLite', 'WAL mode'],
            'keywords': ['sqlite', 'wal-mode', 'write-ahead-log', 'journal-mode'],
        })
        db.upsert_conversation({
            'id': 'conv-b',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.otherapp_dir,
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'Rails migration strategies',
            'summary': 'Rails migration strategies',
            'topics': ['Rails', 'migrations', 'activerecord'],
            # 'activerecord' is topic-only (not in keywords) for default-scope testing
            'keywords': ['rails', 'schema-changes', 'rollback'],
        })
        db.upsert_conversation({
            'id': 'conv-c',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.myapp_dir,
            'started_at': '2026-01-17T08:00:00Z',
            'last_active': '2026-01-17T08:30:00Z',
            'title': 'SQLite index optimization',
            'summary': 'SQLite index optimization techniques',
            'topics': ['SQLite', 'indexes'],
            'keywords': ['sqlite', 'index-optimization', 'query-performance'],
        })
        # 'burndown' is summary-only (not a keyword) to preserve that test coverage.
        # 'activerecord' is topic-only on conv-b for default-scope testing.
        db.upsert_conversation({
            'id': 'conv-d',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.otherapp_dir,
            'started_at': '2026-01-18T07:00:00Z',
            'last_active': '2026-01-18T07:45:00Z',
            'title': 'Velocity estimation for Q2',
            'summary': 'Reviewed burndown charts and story-point estimation for the quarter.',
            'topics': ['project-estimation', 'agile'],
            'keywords': ['sprint-planning', 'story-points', 'quarterly-review'],
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ids_in_output(self, output):
        ids = set()
        for conv_id in ('conv-a', 'conv-b', 'conv-c'):
            if conv_id in output:
                ids.add(conv_id)
        return ids

    def test_search_sqlite_returns_a_and_c(self):
        result = run_search(self.config_path, ['SQLite'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_search_sqlite_wal_and_mode_returns_only_a(self):
        result = run_search(self.config_path, ['SQLite', 'WAL'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertNotIn('conv-b', ids)
        self.assertNotIn('conv-c', ids)

    def test_search_sqlite_rails_or_mode_returns_all(self):
        result = run_search(self.config_path, ['SQLite', 'Rails', '--or'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-b', ids)
        self.assertIn('conv-c', ids)

    def test_search_sqlite_rails_and_mode_returns_nothing(self):
        result = run_search(self.config_path, ['SQLite', 'Rails'])
        # exit 0 with no results is acceptable; no conv IDs in output
        ids = self._ids_in_output(result.stdout)
        self.assertEqual(ids, set())

    def test_search_with_format_csv_includes_header_row(self):
        result = run_search(self.config_path, ['SQLite', '--format', 'csv'])
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.strip().splitlines()
        self.assertTrue(len(lines) >= 1, "Expected at least a header line")
        header = lines[0].lower()
        self.assertTrue(
            'id' in header or 'title' in header or 'session' in header,
            f"Unexpected CSV header: {header!r}"
        )

    def test_search_with_format_csv_output_is_valid_csv(self):
        result = run_search(self.config_path, ['SQLite', '--format', 'csv'])
        self.assertEqual(result.returncode, 0)
        reader = csv.reader(io.StringIO(result.stdout))
        rows = list(reader)
        self.assertTrue(len(rows) >= 1, "Expected at least a header row in CSV output")

    def test_csv_flag_is_not_recognized(self):
        result = run_search(self.config_path, ['SQLite', '--csv'])
        self.assertNotEqual(result.returncode, 0)

    def test_search_with_folder_scoped_to_cwd(self):
        result = run_search(self.config_path, ['SQLite', '--folder', self.myapp_dir])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_search_with_nonexistent_folder_returns_no_results(self):
        result = run_search(self.config_path, ['SQLite', '--folder', '/nonexistent/path'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-a', result.stdout)
        self.assertNotIn('conv-b', result.stdout)
        self.assertNotIn('conv-c', result.stdout)

    def test_no_results_exits_0(self):
        result = run_search(self.config_path, ['absolutelyunknownterm'])
        self.assertEqual(result.returncode, 0)

    def test_missing_terms_exits_nonzero(self):
        result = run_search(self.config_path, [])
        self.assertNotEqual(result.returncode, 0)

    def test_default_does_not_match_summary_only(self):
        # "burndown" is only in conv-d's summary, not any topic
        result = run_search(self.config_path, ['burndown'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-d', result.stdout)

    def test_summary_flag_finds_summary_match(self):
        result = run_search(self.config_path, ['burndown', '--summary'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_title_flag_finds_title_match(self):
        # "Velocity" is only in conv-d's title, not any topic
        result = run_search(self.config_path, ['Velocity', '--title'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_default_does_not_match_title_only(self):
        result = run_search(self.config_path, ['Velocity'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-d', result.stdout)

    def test_stem_matches_hyphenated_topic_with_topic_flag(self):
        # "estimate" (stem "estimat") should match topic "project-estimation" when --topic included
        result = run_search(self.config_path, ['estimate', '--topic'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_default_does_not_match_topic_only(self):
        # "activerecord" is a topic on conv-b but not a keyword
        result = run_search(self.config_path, ['activerecord'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-b', result.stdout)

    def test_topic_flag_finds_topic_only_match(self):
        result = run_search(self.config_path, ['activerecord', '--topic'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-b', result.stdout)

    def test_all_flag_finds_keyword_match(self):
        result = run_search(self.config_path, ['journal-mode', '--all'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-a', result.stdout)

    def test_all_flag_finds_topic_only_match(self):
        result = run_search(self.config_path, ['activerecord', '--all'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-b', result.stdout)

    def test_table_output_shows_keywords_column_header(self):
        result = run_search(self.config_path, ['sqlite'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('Keywords', result.stdout)
        self.assertNotIn('Topics', result.stdout)

    def test_format_json_includes_keywords_field(self):
        import json
        result = run_search(self.config_path, ['sqlite', '--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        conv_a = next(r for r in data if r['id'] == 'conv-a')
        self.assertIn('keywords', conv_a)
        self.assertIsInstance(conv_a['keywords'], list)

    def test_format_csv_includes_keywords_column(self):
        import csv, io
        result = run_search(self.config_path, ['sqlite', '--format', 'csv'])
        self.assertEqual(result.returncode, 0)
        reader = csv.DictReader(io.StringIO(result.stdout))
        self.assertIn('keywords', reader.fieldnames)

    def test_all_flag_finds_summary_only_match(self):
        # "burndown" is only in conv-d's summary
        result = run_search(self.config_path, ['burndown', '--all'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_all_flag_finds_title_only_match(self):
        # "Velocity" is only in conv-d's title
        result = run_search(self.config_path, ['Velocity', '--all'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_all_flag_still_finds_topic_match(self):
        result = run_search(self.config_path, ['SQLite', '--all'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-a', result.stdout)
        self.assertIn('conv-c', result.stdout)

    def test_all_flag_is_exclusive_of_summary_and_title(self):
        # --all should be mutually exclusive with --summary and --title
        result = run_search(self.config_path, ['SQLite', '--all', '--summary'])
        self.assertNotEqual(result.returncode, 0)

    def test_all_flag_is_exclusive_of_title(self):
        result = run_search(self.config_path, ['SQLite', '--all', '--title'])
        self.assertNotEqual(result.returncode, 0)

    def test_format_json_outputs_valid_json(self):
        import json
        result = run_search(self.config_path, ['SQLite', '--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)

    def test_format_json_contains_matching_conversations(self):
        import json
        result = run_search(self.config_path, ['SQLite', '--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        ids = {row['id'] for row in data}
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_format_json_includes_expected_fields(self):
        import json
        result = run_search(self.config_path, ['SQLite', '--format', 'json'])
        self.assertEqual(result.returncode, 0)
        row = json.loads(result.stdout)[0]
        for field in ('id', 'title', 'topics', 'cwd', 'date'):
            self.assertIn(field, row, f"Missing field: {field}")

    def test_format_json_topics_is_list(self):
        import json
        result = run_search(self.config_path, ['SQLite', '--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        conv_a = next(r for r in data if r['id'] == 'conv-a')
        self.assertIsInstance(conv_a['topics'], list)
        self.assertIn('SQLite', conv_a['topics'])

    def test_format_json_no_results_outputs_empty_array(self):
        import json
        result = run_search(self.config_path, ['absolutelyunknownterm', '--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data, [])


if __name__ == '__main__':
    unittest.main()
