# tests/helpers/towit_list_test.py
# Tests for libexec/towit/towit_list.py
#
# Run with: python3 tests/helpers/towit_list_test.py

import unittest
import tempfile
import shutil
import subprocess
import csv
import io
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
LIST_SCRIPT = os.path.join(HELPERS_DIR, 'towit_list.py')

sys.path.insert(0, HELPERS_DIR)
from towit_db import Database


def write_config(tmpdir, db_path):
    """Write a minimal config.toml containing db_path. Returns config file path."""
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_list(config_path, args=None):
    """Run towit_list.py as a subprocess."""
    return subprocess.run(
        ['python3', LIST_SCRIPT] + (args or []),
        env={**os.environ, 'TOWIT_CONFIG_PATH': config_path},
        capture_output=True,
        text=True
    )


class TestTowitList(unittest.TestCase):
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
            'keywords': ['sqlite', 'wal-mode', 'journal-mode'],
        })
        db.upsert_conversation({
            'id': 'conv-b',
            'folder': '/home/user/.claude/projects/-Users-alice',
            'cwd': self.otherapp_dir,
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'Rails migration strategies',
            'summary': 'Rails migration strategies',
            'topics': ['Rails', 'migrations'],
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

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ids_in_output(self, output):
        ids = set()
        for conv_id in ('conv-a', 'conv-b', 'conv-c'):
            if conv_id in output:
                ids.add(conv_id)
        return ids

    def test_list_returns_all_conversations(self):
        result = run_list(self.config_path)
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-b', ids)
        self.assertIn('conv-c', ids)

    def test_list_with_topic_returns_only_matching(self):
        result = run_list(self.config_path, ['--topic', 'SQLite'])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_list_with_folder_returns_only_matching_cwd(self):
        result = run_list(self.config_path, ['--folder', self.myapp_dir])
        self.assertEqual(result.returncode, 0)
        ids = self._ids_in_output(result.stdout)
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_list_with_format_csv_includes_header_and_all_rows(self):
        result = run_list(self.config_path, ['--format', 'csv'])
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.strip().splitlines()
        # At least header + 3 data rows
        self.assertGreaterEqual(len(lines), 4, f"Expected header + 3 rows, got {len(lines)} lines")
        # Header should contain a field name
        header = lines[0].lower()
        self.assertTrue(
            'id' in header or 'title' in header or 'session' in header,
            f"Unexpected CSV header: {header!r}"
        )
        # All CSV rows should parse cleanly
        reader = csv.reader(io.StringIO(result.stdout))
        rows = list(reader)
        self.assertGreaterEqual(len(rows), 4)

    def test_csv_flag_is_not_recognized(self):
        result = run_list(self.config_path, ['--csv'])
        self.assertNotEqual(result.returncode, 0)

    def test_list_with_nonexistent_folder_returns_no_results(self):
        result = run_list(self.config_path, ['--folder', '/nonexistent/path'])
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('conv-a', result.stdout)
        self.assertNotIn('conv-b', result.stdout)
        self.assertNotIn('conv-c', result.stdout)

    def test_empty_db_returns_exit_0(self):
        empty_db = os.path.join(self.tmpdir, 'empty.db')
        empty_config = write_config(self.tmpdir, empty_db)
        db = Database(empty_db)
        db.create_schema()
        result = run_list(empty_config)
        self.assertEqual(result.returncode, 0)

    def test_format_json_outputs_valid_json(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)

    def test_format_json_contains_all_conversations(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        ids = {row['id'] for row in data}
        self.assertIn('conv-a', ids)
        self.assertIn('conv-b', ids)
        self.assertIn('conv-c', ids)

    def test_format_json_includes_expected_fields(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        row = json.loads(result.stdout)[0]
        for field in ('id', 'title', 'topics', 'cwd', 'date'):
            self.assertIn(field, row, f"Missing field: {field}")

    def test_format_json_keys_are_exactly_the_documented_ones(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        for row in json.loads(result.stdout):
            self.assertEqual(list(row), ['id', 'title', 'keywords', 'topics', 'cwd', 'date'])

    def test_format_json_topics_is_list(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        conv_a = next(r for r in data if r['id'] == 'conv-a')
        self.assertIsInstance(conv_a['topics'], list)
        self.assertIn('SQLite', conv_a['topics'])

    def test_format_json_respects_topic_filter(self):
        import json
        result = run_list(self.config_path, ['--format', 'json', '--topic', 'SQLite'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        ids = {row['id'] for row in data}
        self.assertIn('conv-a', ids)
        self.assertIn('conv-c', ids)
        self.assertNotIn('conv-b', ids)

    def test_keyword_filter_returns_only_matching(self):
        result = run_list(self.config_path, ['--keyword', 'journal-mode'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-a', result.stdout)
        self.assertNotIn('conv-b', result.stdout)
        self.assertNotIn('conv-c', result.stdout)

    def test_keyword_filter_excludes_non_matching(self):
        result = run_list(self.config_path, ['--keyword', 'rollback'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('conv-b', result.stdout)
        self.assertNotIn('conv-a', result.stdout)

    def test_table_output_shows_keywords_column_header(self):
        result = run_list(self.config_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Keywords', result.stdout)
        self.assertNotIn('Topics', result.stdout)

    def test_format_json_includes_keywords_field(self):
        import json
        result = run_list(self.config_path, ['--format', 'json'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        conv_a = next(r for r in data if r['id'] == 'conv-a')
        self.assertIn('keywords', conv_a)
        self.assertIsInstance(conv_a['keywords'], list)

    def test_format_csv_includes_keywords_column(self):
        import csv, io
        result = run_list(self.config_path, ['--format', 'csv'])
        self.assertEqual(result.returncode, 0)
        reader = csv.DictReader(io.StringIO(result.stdout))
        self.assertIn('keywords', reader.fieldnames)

    def test_format_json_respects_keyword_filter(self):
        import json
        result = run_list(self.config_path, ['--format', 'json', '--keyword', 'rollback'])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        ids = {row['id'] for row in data}
        self.assertIn('conv-b', ids)
        self.assertNotIn('conv-a', ids)
        self.assertNotIn('conv-c', ids)


class TestTowitListSanitizesTable(unittest.TestCase):
    """Titles, keywords and cwd come from archived text; table output must be terminal-safe."""
    EVIL = 'x\x1b[31mred\x1b[0m \x1b]0;pwned\x07 y\rz\x9b2J'

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        cwd = '/w/app' + '\x1b]0;cwdpwn\x07'
        db.upsert_conversation({
            'id': 'evil-1', 'folder': '/f', 'cwd': cwd, 'started_at': '2026-02-01T00:00:00Z',
            'last_active': '2026-02-01T00:00:00Z', 'title': 'title ' + self.EVIL + '\nmore',
            'summary': '', 'topics': [], 'keywords': ['kw' + self.EVIL]})
        db.archive_session(
            {'id': 'evil-2', 'folder': '/f', 'cwd': cwd, 'started_at': '2026-02-02T00:00:00Z',
             'last_active': '2026-02-02T00:00:00Z', 'repo_key': None, 'source_path': None},
            [{'role': 'user', 'ts': None, 'text': 'first line ' + self.EVIL + '\nsecond line\there'},
             {'role': 'assistant', 'ts': None, 'text': 'ok'}])

    def test_table_cells_and_cwd_header_are_clean(self):
        r = run_list(self.config_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        for ch in r.stdout:
            if ch != '\n':
                self.assertGreaterEqual(ord(ch), 0x20, repr(ch))
                self.assertFalse(0x7f <= ord(ch) <= 0x9f, repr(ch))
        for leaked in ('[31m', 'pwned', 'cwdpwn', '[2J'):
            self.assertNotIn(leaked, r.stdout)
        self.assertEqual(len(r.stdout.splitlines()), 5, r.stdout)  # cwd, header, divider, 2 rows

    def test_json_still_ascii_escapes(self):
        r = run_list(self.config_path, ['--format', 'json'])
        self.assertNotIn('\x1b', r.stdout)
        self.assertNotIn('\x07', r.stdout)


class TestTowitListArchiveOnlyTitle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        db.archive_session(
            {'id': 'arc-only', 'folder': '/f', 'cwd': '/w/app', 'started_at': '2026-02-01T00:00:00Z',
             'last_active': '2026-02-01T00:00:00Z', 'repo_key': None, 'source_path': None},
            [{'role': 'user', 'ts': None, 'text': 'How do I tune the flux capacitor?'},
             {'role': 'assistant', 'ts': None, 'text': 'carefully'}])

    def test_table_shows_first_user_message_as_title(self):
        r = run_list(self.config_path)
        self.assertIn('How do I tune the flux capacitor?', r.stdout)

    def test_json_and_csv_use_the_same_fallback_title(self):
        import json
        data = json.loads(run_list(self.config_path, ['--format', 'json']).stdout)
        self.assertEqual(data[0]['title'], 'How do I tune the flux capacitor?')
        rows = list(csv.reader(io.StringIO(run_list(self.config_path, ['--format', 'csv']).stdout)))
        self.assertEqual(rows[1][1], 'How do I tune the flux capacitor?')


class TestTowitListCsv(unittest.TestCase):
    """CSV output round-trips awkward values as stored; an empty list prints no header."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 't.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_awkward_values_round_trip(self):
        self.db.upsert_conversation({
            'id': 'c1', 'folder': '/f', 'cwd': '/w/app, "q"', 'started_at': '2026-01-01T00:00:00Z',
            'last_active': None, 'title': '=HYPERLINK("x"), café\nnext', 'summary': 's',
            'topics': ['t,1', 't"2'], 'keywords': ['k,w']})
        r = run_list(self.config_path, ['--format', 'csv'])
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = list(csv.reader(io.StringIO(r.stdout, newline='')))
        self.assertEqual(rows[0], ['id', 'title', 'keywords', 'topics', 'cwd', 'date'])
        self.assertEqual(rows[1], ['c1', '=HYPERLINK("x"), café\nnext', 'k,w', 't,1,t"2',
                                   '/w/app, "q"', '2026-01-01'])

    def test_no_results_prints_no_header_and_a_stderr_notice(self):
        r = run_list(self.config_path, ['--format', 'csv'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, '')
        self.assertIn('No conversations found', r.stderr)


class TestTowitListClosedPipe(unittest.TestCase):
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
        # No reader at all: the first write fails with EPIPE whatever the output size
        read_end, write_end = os.pipe()
        os.close(read_end)
        proc = subprocess.Popen(
            ['python3', LIST_SCRIPT] + ['--format', 'json'],
            env={**os.environ, 'TOWIT_CONFIG_PATH': config_path},
            stdout=write_end, stderr=subprocess.PIPE,
        )
        os.close(write_end)
        _, stderr = proc.communicate(timeout=60)
        self.assertNotIn('BrokenPipeError', stderr.decode())
        self.assertNotIn('Traceback', stderr.decode())
        self.assertEqual(proc.returncode, 141)


class TestTowitListTableWidth(unittest.TestCase):
    """The text table must fit the terminal (COLUMNS) minus 4 whenever that is achievable."""
    ID = '0a1b2c3d-4e5f-6789-abcd-ef0123456789'
    TITLE = 'Designing exponential backoff with decorrelated jitter for the payments webhook'

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        self.add_conversation(self.ID, '/w/acme-api',
                              ['jitter-strategy', 'exponential-backoff', 'webhook-retries'])

    def add_conversation(self, conversation_id, cwd, keywords):
        Database(self.db_path).upsert_conversation({
            'id': conversation_id, 'folder': '/f', 'cwd': cwd, 'started_at': '2026-03-04T00:00:00Z',
            'last_active': '2026-03-04T00:00:00Z',
            'title': self.TITLE,
            'summary': 's', 'topics': [],
            'keywords': keywords})

    def run_at(self, columns, args=None):
        env = {**os.environ, 'TOWIT_CONFIG_PATH': self.config_path, 'COLUMNS': str(columns)}
        r = subprocess.run(['python3', LIST_SCRIPT] + (args or []), env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_no_line_exceeds_terminal_width_minus_4(self):
        for columns in (80, 100, 120, 160):
            out = self.run_at(columns)
            self.assertLessEqual(max(len(line) for line in out.splitlines()), columns - 4,
                                 f'{columns} columns:\n{out}')

    def test_full_id_and_date_survive_at_every_width(self):
        for columns in (80, 100, 120, 160):
            row = next(line for line in self.run_at(columns).splitlines() if self.ID in line)
            self.assertIn('2026-03-04', row, columns)

    def test_keywords_dropped_only_when_shrinking_is_not_enough(self):
        narrow = self.run_at(60)
        self.assertNotIn('Keywords', narrow)
        self.assertIn(self.ID, narrow)
        self.assertIn('Title', narrow)
        self.assertIn('Keywords', self.run_at(100))

    def test_empty_keywords_leave_room_for_the_full_title(self):
        self.add_conversation('conv-unindexed', '/w/unindexed', [])
        header, divider, row = self.run_at(115, ['--folder', '/w/unindexed']).splitlines()
        self.assertEqual(header.split(), ['ID', 'Title', 'Date'])
        self.assertEqual(len(divider.split()), 3)
        self.assertIn(self.TITLE, row)
        self.assertLessEqual(len(row), 111)

    def test_keywords_remain_in_all_groups_when_one_row_has_keywords(self):
        self.add_conversation('conv-unindexed', '/w/unindexed', [])
        out = self.run_at(400)
        headers = [line.split() for line in out.splitlines() if line.lstrip().startswith('ID ')]
        self.assertEqual(headers, [['ID', 'Title', 'Keywords', 'Date']] * 2)
        self.assertIn('jitter-strategy', out)
        self.assertIn('conv-unindexed', out)

    def test_table_unchanged_when_it_fits(self):
        wide = self.run_at(400)
        self.assertIn('Designing exponential backoff with decorrelated jitter for the payments webhook', wide)
        self.assertIn('jitter-strategy,exponential-backoff,webhook-retries', wide)

    def test_ungrouped_table_fits_too(self):
        out = self.run_at(80, ['--folder', '/w/acme-api'])
        self.assertLessEqual(max(len(line) for line in out.splitlines()), 76, out)


class TestTowitListWideCharacters(unittest.TestCase):
    """CJK and emoji titles take two cells each; columns must still line up and fit the terminal.

    The expected output is hard-coded rather than measured, so the test does not share the width
    calculation it checks. The header and the ASCII row are plain ASCII, so their string offsets
    are their cell offsets. The wide-title row is compared as a whole: each CJK character and 🚀
    takes two cells and `…` one, so every row below takes as many cells as the header above it.
    """
    WIDE_ID = '1a1b2c3d-4e5f-6789-abcd-ef0123456789'
    ASCII_ID = '2a1b2c3d-4e5f-6789-abcd-ef0123456789'

    # COLUMNS -> (offset of Date in the header, the wide-title row exactly as printed)
    EXPECTED = {
        60: (48, '1a1b2c3d-4e5f-6789-abcd-ef0123456789  支付回…   2026-03-04'),
        80: (66, '1a1b2c3d-4e5f-6789-abcd-ef0123456789  支付回调的指数…   重试,退…  2026-03-04'),
        100: (86, '1a1b2c3d-4e5f-6789-abcd-ef0123456789  支付回调的指数退避重试设计 🚀 与抖…  '
                  '重试,退避  2026-03-04'),
        120: (91, '1a1b2c3d-4e5f-6789-abcd-ef0123456789  支付回调的指数退避重试设计 🚀 与抖动策略  '
                  '重试,退避  2026-03-04'),
        400: (91, '1a1b2c3d-4e5f-6789-abcd-ef0123456789  支付回调的指数退避重试设计 🚀 与抖动策略  '
                  '重试,退避  2026-03-04'),
    }

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        for cid, title, keywords, day in (
                (self.WIDE_ID, '支付回调的指数退避重试设计 🚀 与抖动策略', ['重试', '退避'], '04'),
                (self.ASCII_ID, 'Plain ASCII title', ['retry'], '05')):
            db.upsert_conversation({
                'id': cid, 'folder': '/f', 'cwd': '/w/acme-api', 'started_at': f'2026-03-{day}T00:00:00Z',
                'last_active': f'2026-03-{day}T00:00:00Z', 'title': title, 'summary': 's',
                'topics': [], 'keywords': keywords})

    def run_at(self, columns):
        env = {**os.environ, 'TOWIT_CONFIG_PATH': self.config_path, 'COLUMNS': str(columns)}
        r = subprocess.run(['python3', LIST_SCRIPT, '--folder', '/w/acme-api'], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def split_rows(self, lines):
        """Return (header, ASCII-title row, wide-title row)."""
        header = next(line for line in lines if 'Date' in line)
        ascii_row = next(line for line in lines if line.startswith(self.ASCII_ID))
        wide_row = next(line for line in lines if line.startswith(self.WIDE_ID))
        return header, ascii_row, wide_row

    def test_date_column_lines_up_with_header(self):
        for columns, (date_offset, wide_row) in self.EXPECTED.items():
            lines = self.run_at(columns)
            msg = f'{columns} columns:\n' + '\n'.join(lines)
            header, ascii_row, actual_wide_row = self.split_rows(lines)
            self.assertEqual(header.index('Date'), date_offset, msg)
            self.assertEqual(ascii_row.index('2026-03-05'), date_offset, msg)
            self.assertEqual(actual_wide_row, wide_row, msg)

    def test_no_line_exceeds_terminal_width_minus_4(self):
        for columns in (80, 100, 120):
            lines = self.run_at(columns)
            msg = f'{columns} columns:\n' + '\n'.join(lines)
            # Every line but the wide-title row is ASCII, so len() is its width in cells
            ascii_lines = [line for line in lines if not line.startswith(self.WIDE_ID)]
            self.assertLessEqual(max(len(line) for line in ascii_lines), columns - 4, msg)
            # The wide-title row takes as many cells as the header (see the class docstring)
            self.assertEqual(self.split_rows(lines)[2], self.EXPECTED[columns][1], msg)

    def test_wide_title_shown_whole_when_it_fits(self):
        self.assertTrue(any('支付回调的指数退避重试设计 🚀 与抖动策略' in line for line in self.run_at(400)))


if __name__ == '__main__':
    unittest.main()
