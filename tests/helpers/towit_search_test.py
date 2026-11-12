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
from towit_db import SCHEMA_VERSION, Database
from towit_db_test import build_old_schema_db


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
        result = run_search(self.config_path, ['SQLite', 'Rails', '--only', 'metadata'])
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
        result = run_search(self.config_path, ['burndown', '--only', 'metadata'])
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
        result = run_search(self.config_path, ['Velocity', '--only', 'metadata'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-d', result.stdout)

    def test_default_scope_matches_summary_only(self):
        result = run_search(self.config_path, ['burndown'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_default_scope_matches_title_only(self):
        result = run_search(self.config_path, ['Velocity'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-d', result.stdout)

    def test_default_scope_still_excludes_topic_only(self):
        result = run_search(self.config_path, ['activerecord'])
        self.assertNotIn('conv-b', result.stdout)

    def test_only_text_ignores_title_and_summary(self):
        for term in ('Velocity', 'burndown'):
            result = run_search(self.config_path, [term, '--only', 'text'])
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


class TestTowitSearchOnOldDatabase(unittest.TestCase):
    def test_search_migrates_old_db_on_first_use(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        db_path = os.path.join(tmpdir, 'old.db')
        build_old_schema_db(db_path)
        config_path = write_config(tmpdir, db_path)
        result = run_search(config_path, ['legacy-kw', '--format', 'json'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('old-1', result.stdout)
        self.assertEqual(result.stderr, '')
        self.assertEqual(Database(db_path).schema_version(), SCHEMA_VERSION)


class TestTowitSearchArchive(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        db.archive_session(
            {'id': 'arc-1', 'folder': '/f', 'cwd': '/w/app', 'started_at': '2026-02-01T00:00:00Z',
             'last_active': '2026-02-01T00:00:00Z', 'repo_key': '/src/app', 'source_path': None},
            [{'role': 'user', 'ts': None, 'text': 'what about the hook?'},
             {'role': 'assistant', 'ts': None, 'text': 'The recursion guard prevents loops.'}])
        db.archive_session(
            {'id': 'arc-2', 'folder': '/f', 'cwd': '/w/other', 'started_at': '2026-02-02T00:00:00Z',
             'last_active': '2026-02-02T00:00:00Z', 'repo_key': '/src/other', 'source_path': None},
            [{'role': 'user', 'ts': None, 'text': 'guard rails?'},
             {'role': 'assistant', 'ts': None, 'text': 'yes'}])
        db.upsert_conversation({
            'id': 'meta-1', 'folder': '/f', 'cwd': '/w/app', 'started_at': '2026-01-01T00:00:00Z',
            'last_active': '2026-01-01T00:00:00Z', 'title': 'Old', 'summary': 's',
            'topics': [], 'keywords': ['guard-rails']})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_table_has_msg_and_snippet_columns(self):
        r = run_search(self.config_path, ['recursion'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Msg', r.stdout)
        self.assertNotIn('Turn', r.stdout)
        self.assertIn('Snippet', r.stdout)
        self.assertIn('[recursion]', r.stdout)
        self.assertIn('what about the hook?', r.stdout)  # title fallback

    def test_table_metadata_hit_shows_keyword(self):
        r = run_search(self.config_path, ['guard'])
        self.assertIn('guard-rails', r.stdout)
        self.assertIn('arc-1', r.stdout)

    def test_json_entries_include_seq_snippet_score(self):
        import json
        r = run_search(self.config_path, ['recursion', '--format', 'json'])
        data = json.loads(r.stdout)
        self.assertEqual([d['id'] for d in data], ['arc-1'])
        self.assertEqual(data[0]['seq'], 1)
        self.assertIn('[recursion]', data[0]['snippet'])
        self.assertIsInstance(data[0]['score'], float)

    def test_json_metadata_hit_has_null_seq_and_score(self):
        import json
        r = run_search(self.config_path, ['guard-rails', '--format', 'json'])
        meta = next(d for d in json.loads(r.stdout) if d['id'] == 'meta-1')
        self.assertIsNone(meta['seq'])
        self.assertIsNone(meta['score'])
        self.assertEqual(meta['snippet'], '')

    def test_only_text_ignores_keywords(self):
        import json
        r = run_search(self.config_path, ['guard-rails', '--only', 'text', '--format', 'json'])
        self.assertEqual(json.loads(r.stdout), [])

    def test_only_metadata_ignores_message_text(self):
        import json
        r = run_search(self.config_path, ['recursion', '--only', 'metadata', '--format', 'json'])
        self.assertEqual(json.loads(r.stdout), [])
        r = run_search(self.config_path, ['guard-rails', '--only', 'metadata'])
        self.assertNotIn('Snippet', r.stdout)
        self.assertIn('Keywords', r.stdout)

    def test_only_rejects_bad_value(self):
        self.assertNotEqual(run_search(self.config_path, ['x', '--only', 'bogus']).returncode, 0)

    def test_repo_by_key_and_name(self):
        import json
        for repo in ('/src/other', 'other'):
            r = run_search(self.config_path, ['guard', '--repo', repo, '--format', 'json'])
            self.assertEqual([d['id'] for d in json.loads(r.stdout)], ['arc-2'], repo)

    def test_repo_name_matches_worktree_key_by_prefix(self):
        import json
        db = Database(self.db_path)
        for sid, key in (('wt-1', '/src/app.phase-2a'), ('wt-2', '/src/app2'),
                         ('wt-3', '/src/otherapp.x')):
            db.archive_session(
                {'id': sid, 'folder': '/f', 'cwd': '/w/wt', 'started_at': '2026-02-03T00:00:00Z',
                 'last_active': None, 'repo_key': key, 'source_path': None},
                [{'role': 'user', 'ts': None, 'text': 'prefixprobe here'},
                 {'role': 'assistant', 'ts': None, 'text': 'ok'}])
        r = run_search(self.config_path, ['prefixprobe', '--repo', 'app', '--format', 'json'])
        self.assertEqual([d['id'] for d in json.loads(r.stdout)], ['wt-1'])

    def test_hostile_term_does_not_crash(self):
        r = run_search(self.config_path, ['"', '--format', 'json'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '[]')

    def test_default_cli_returns_all_metadata_hits_past_50(self):
        import json
        db = Database(self.db_path)
        for i in range(55):
            db.upsert_conversation({
                'id': 'bulk-%02d' % i, 'folder': '/f', 'cwd': '/w/bulk',
                'started_at': '2026-03-01T00:%02d:00Z' % i, 'last_active': None,
                'title': 'Bulk %d' % i, 'summary': 's', 'topics': [], 'keywords': ['bulkkw']})
        r = run_search(self.config_path, ['bulkkw', '--format', 'json'])
        self.assertEqual(len(json.loads(r.stdout)), 55)

    def test_csv_includes_seq_and_snippet(self):
        r = run_search(self.config_path, ['recursion', '--format', 'csv'])
        header = next(csv.reader(io.StringIO(r.stdout)))
        self.assertIn('seq', header)
        self.assertIn('snippet', header)


    NOTICE = 'No results for all terms; showing results matching any term.'

    def test_or_fallback_when_all_terms_find_nothing(self):
        import json
        r = run_search(self.config_path, ['recursion', 'yes', '--format', 'json'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(d['id'] for d in json.loads(r.stdout)), ['arc-1', 'arc-2'])
        self.assertIn(self.NOTICE, r.stderr)
        self.assertNotIn(self.NOTICE, r.stdout)  # stdout stays parseable

    def test_or_fallback_notice_is_on_stderr_for_table_and_csv(self):
        for extra in ([], ['--format', 'csv']):
            r = run_search(self.config_path, ['recursion', 'yes'] + extra)
            self.assertIn(self.NOTICE, r.stderr, extra)
            self.assertNotIn(self.NOTICE, r.stdout, extra)
            self.assertIn('arc-1', r.stdout, extra)
        header = next(csv.reader(io.StringIO(r.stdout)))
        self.assertEqual(header[0], 'id')

    def test_or_fallback_applies_to_only_text(self):
        import json
        r = run_search(self.config_path, ['recursion', 'yes', '--only', 'text', '--format', 'json'])
        self.assertEqual(sorted(d['id'] for d in json.loads(r.stdout)), ['arc-1', 'arc-2'])
        self.assertIn(self.NOTICE, r.stderr)

    def test_no_fallback_when_all_terms_match(self):
        import json
        r = run_search(self.config_path, ['recursion', 'guard', '--format', 'json'])
        self.assertEqual([d['id'] for d in json.loads(r.stdout)], ['arc-1'])
        self.assertNotIn(self.NOTICE, r.stderr)

    def test_no_fallback_with_explicit_or(self):
        r = run_search(self.config_path, ['recursion', 'zzzmissing', '--or', '--format', 'json'])
        self.assertNotIn(self.NOTICE, r.stderr)
        self.assertIn('arc-1', r.stdout)

    def test_no_fallback_for_only_metadata(self):
        import json
        r = run_search(self.config_path, ['guard-rails', 'zzzmissing', '--only', 'metadata',
                                          '--format', 'json'])
        self.assertEqual(json.loads(r.stdout), [])
        self.assertNotIn(self.NOTICE, r.stderr)

    def test_no_fallback_for_a_single_term(self):
        r = run_search(self.config_path, ['zzzmissing'])
        self.assertNotIn(self.NOTICE, r.stderr)
        self.assertIn('No conversations found', r.stderr)

    def test_fallback_with_no_any_term_hits_prints_only_no_conversations(self):
        r = run_search(self.config_path, ['zzzmissing', 'qqqmissing'])
        self.assertNotIn(self.NOTICE, r.stderr)
        self.assertIn('No conversations found', r.stderr)

class TestTowitSearchSanitizesTable(unittest.TestCase):
    """Archived text can carry terminal escapes and newlines; table output must not."""
    EVIL = 'x\x1b[31mred\x1b[0m \x1b]0;pwned\x07 y\rz\x9b2J'

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        cwd = '/w/app' + '\x1b]0;cwdpwn\x07'
        db.archive_session(
            {'id': 'evil-1', 'folder': '/f', 'cwd': cwd, 'started_at': '2026-02-01T00:00:00Z',
             'last_active': '2026-02-01T00:00:00Z', 'repo_key': None, 'source_path': None},
            [{'role': 'user', 'ts': None, 'text': 'zorblat ' + self.EVIL + '\nsecond\tline of it'},
             {'role': 'assistant', 'ts': None, 'text': 'zorblat reply ' + self.EVIL}])
        db.upsert_conversation({
            'id': 'evil-2', 'folder': '/f', 'cwd': cwd, 'started_at': '2026-02-02T00:00:00Z',
            'last_active': '2026-02-02T00:00:00Z', 'title': 'zorblat title ' + self.EVIL + '\nmore',
            'summary': '', 'topics': [], 'keywords': ['zorblat-kw' + self.EVIL]})

    def assert_clean(self, out, expected_lines):
        for ch in out:
            if ch != '\n':
                self.assertGreaterEqual(ord(ch), 0x20, repr(ch))
                self.assertFalse(0x7f <= ord(ch) <= 0x9f, repr(ch))
        for leaked in ('[31m', 'pwned', 'cwdpwn', '[2J'):
            self.assertNotIn(leaked, out)
        self.assertEqual(len(out.splitlines()), expected_lines, out)

    def test_table_cells_and_cwd_header_are_clean(self):
        r = run_search(self.config_path, ['zorblat'])
        self.assertEqual(r.returncode, 0, r.stderr)
        # cwd header + column header + divider + two rows
        self.assert_clean(r.stdout, 5)
        self.assertIn('zorblat', r.stdout)

    def test_metadata_only_table_is_clean(self):
        r = run_search(self.config_path, ['zorblat', '--only', 'metadata'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_clean(r.stdout, 4)

    def test_json_still_ascii_escapes(self):
        r = run_search(self.config_path, ['zorblat', '--format', 'json'])
        self.assertNotIn('\x1b', r.stdout)
        self.assertNotIn('\x07', r.stdout)


class TestTowitSearchCsv(unittest.TestCase):
    """CSV output is machine-readable: values round-trip through a CSV parser as stored."""

    TEXT = 'He said "hi", then\nleft;\ttab =SUM(A1) café \U0001F600'

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 't.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        for cid, cwd, repo, title, text, keywords, topics in (
                ('a1', '/w/app, "q"', '/src/app', '=HYPERLINK("x")', 'needle ' + self.TEXT,
                 ['needle', 'k,w'], ['t,1', 't"2']),
                ('b2', '/w/other', '/src/other', 'Other', 'needle \x1b[31mred\x1b[0m', [], [])):
            started = '2026-01-01T00:00:00Z'
            db.archive_session(
                {'id': cid, 'folder': '/f', 'cwd': cwd, 'started_at': started,
                 'last_active': started, 'repo_key': repo, 'source_path': None},
                [{'role': 'user', 'ts': None, 'text': 'question'},
                 {'role': 'assistant', 'ts': None, 'text': text}])
            db.upsert_conversation({
                'id': cid, 'folder': '/f', 'cwd': cwd, 'started_at': started,
                'last_active': started, 'title': title, 'summary': 's',
                'topics': topics, 'keywords': keywords})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def rows(self, *args):
        r = run_search(self.config_path, ['needle', '--format', 'csv'] + list(args))
        self.assertEqual(r.returncode, 0, r.stderr)
        return list(csv.reader(io.StringIO(r.stdout, newline='')))

    def by_id(self, *args):
        rows = self.rows(*args)
        return rows[0], {row[0]: row for row in rows[1:]}

    def test_awkward_values_round_trip(self):
        header, rows = self.by_id('--only', 'text')
        row = dict(zip(header, rows['a1']))
        self.assertEqual(row['title'], '=HYPERLINK("x")')
        self.assertEqual(row['cwd'], '/w/app, "q"')
        self.assertEqual(row['keywords'], 'needle,k,w')
        self.assertEqual(row['topics'], 't,1,t"2')
        self.assertIn('He said "hi", then\nleft;\ttab =SUM(A1) café \U0001F600', row['snippet'])

    def test_cells_are_printed_as_stored(self):
        # Documented: no spreadsheet-formula or terminal-escape neutralizing in CSV.
        _, rows = self.by_id('--only', 'text')
        self.assertTrue(rows['a1'][1].startswith('='))
        self.assertIn('\x1b[31m', rows['b2'][7])

    def test_column_count_follows_scope(self):
        header, rows = self.by_id()
        self.assertEqual(header[-3:], ['seq', 'snippet', 'score'])
        self.assertEqual({len(r) for r in rows.values()}, {9})
        header, rows = self.by_id('--only', 'text')
        self.assertEqual(len(header), 9)
        self.assertEqual({len(r) for r in rows.values()}, {9})
        header, rows = self.by_id('--only', 'metadata')
        self.assertEqual(header, ['id', 'title', 'keywords', 'topics', 'cwd', 'date'])
        self.assertEqual({len(r) for r in rows.values()}, {6})

    def test_repo_and_folder_filter_csv_rows(self):
        _, rows = self.by_id('--only', 'text', '--repo', 'other')
        self.assertEqual(sorted(rows), ['b2'])
        _, rows = self.by_id('--only', 'text', '--folder', '/w/other')
        self.assertEqual(sorted(rows), ['b2'])

    def test_no_results_prints_no_header_and_a_stderr_notice(self):
        r = run_search(self.config_path, ['zzzmissing', '--format', 'csv'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, '')
        self.assertIn('No conversations found', r.stderr)


class TestTowitSearchClosedPipe(unittest.TestCase):
    def test_closed_pipe_exits_141_without_traceback(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        db_path = os.path.join(tmpdir, 'test.db')
        config_path = write_config(tmpdir, db_path)
        db = Database(db_path)
        db.create_schema()
        for i in range(400):
            db.upsert_conversation({
                'id': f'conv-{i:04d}', 'folder': '/f', 'cwd': '/work/proj',
                'started_at': '2026-01-15T10:00:00Z', 'last_active': '2026-01-15T10:30:00Z',
                'title': f'needle title {i}', 'summary': 'needle ' + 'padding ' * 30,
                'topics': ['demo'], 'keywords': ['needle'],
            })
        proc = subprocess.Popen(
            ['python3', SEARCH_SCRIPT] + ['needle', '--format', 'json'],
            env={**os.environ, 'TOWIT_CONFIG_PATH': config_path},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        proc.stdout.readline()
        proc.stdout.close()
        _, stderr = proc.communicate(timeout=60)
        self.assertNotIn('BrokenPipeError', stderr.decode())
        self.assertNotIn('Traceback', stderr.decode())
        self.assertEqual(proc.returncode, 141)


if __name__ == '__main__':
    unittest.main()
