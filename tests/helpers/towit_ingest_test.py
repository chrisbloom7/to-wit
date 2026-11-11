# tests/helpers/towit_ingest_test.py
# Tests for libexec/towit/towit_ingest.py
#
# Run with: python3 tests/helpers/towit_ingest_test.py

import json
import os
import shutil
import sys
import subprocess
import tempfile
import time
from datetime import datetime
import threading
import unittest
import unittest.mock

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)

import towit_ingest
from towit_db import Database
from towit_ingest import (MAX_MESSAGE_CHARS, ingest_transcript, parse_transcript,
                          resolve_repo_key)


def _write_jsonl(path, entries):
    """Write entries (dicts, or raw strings written verbatim) one per line."""
    with open(path, 'w', encoding='utf-8') as fh:
        for e in entries:
            fh.write(e if isinstance(e, str) else json.dumps(e))
            fh.write('\n')


def _entry(role, content, ts='2026-01-01T00:00:00Z', cwd='/work/proj'):
    return {'type': role, 'timestamp': ts, 'cwd': cwd, 'sessionId': 'sid',
            'message': {'role': role, 'content': content}}


class TestParseTranscript(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, 'abc-123.jsonl')

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _parse(self, entries):
        _write_jsonl(self.path, entries)
        return parse_transcript(self.path)

    def test_text_and_tool_stub_in_order(self):
        parsed = self._parse([_entry('assistant', [
            {'type': 'text', 'text': 'Running tests'},
            {'type': 'tool_use', 'name': 'Bash',
             'input': {'description': 'Run tests', 'command': 'pytest'}},
        ])])
        self.assertEqual(len(parsed.messages), 1)
        self.assertEqual(parsed.messages[0].text, 'Running tests\n[Bash] Run tests')
        self.assertEqual(parsed.messages[0].role, 'assistant')

    def test_bash_falls_back_to_command(self):
        parsed = self._parse([_entry('assistant', [
            {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'pytest -x'}},
        ])])
        self.assertEqual(parsed.messages[0].text, '[Bash] pytest -x')

    def test_stub_value_capped_at_200(self):
        parsed = self._parse([_entry('assistant', [
            {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': '/a' * 250}},
        ])])
        self.assertEqual(len(parsed.messages[0].text), len('[Edit] ') + 200)

    def test_error_result_truncated_to_300(self):
        parsed = self._parse([_entry('user', [
            {'type': 'tool_result', 'is_error': True, 'content': 'x' * 500},
        ])])
        self.assertEqual(parsed.messages[0].text, '[error] ' + 'x' * 300)

    def test_error_result_with_list_content(self):
        parsed = self._parse([_entry('user', [
            {'type': 'tool_result', 'is_error': True,
             'content': [{'type': 'text', 'text': 'boom'}]},
        ])])
        self.assertEqual(parsed.messages[0].text, '[error] boom')

    def test_non_error_results_and_thinking_ignored(self):
        parsed = self._parse([
            _entry('user', [{'type': 'tool_result', 'content': 'fine'}]),
            _entry('assistant', [{'type': 'thinking', 'thinking': 'hmm'}]),
        ])
        self.assertEqual(parsed.messages, [])

    def test_partial_last_line_is_ignored(self):
        parsed = self._parse([
            _entry('user', 'hello'),
            '{"type": "assi',
        ])
        self.assertEqual([m.text for m in parsed.messages], ['hello'])

    def test_oversized_message_truncated_with_marker(self):
        parsed = self._parse([_entry('user', 'a' * 120_000)])
        text = parsed.messages[0].text
        self.assertLessEqual(len(text), MAX_MESSAGE_CHARS + 60)
        self.assertTrue(text.endswith('chars truncated ...]'))
        self.assertTrue(text.endswith('\n[... %d chars truncated ...]' % (120_000 - MAX_MESSAGE_CHARS)))

    def test_metadata_fields(self):
        parsed = self._parse([
            {'type': 'summary', 'summary': 'x'},
            _entry('user', 'one', ts='2026-01-01T00:00:00Z', cwd='/work/proj'),
            _entry('assistant', 'two', ts='2026-01-01T00:05:00Z', cwd='/other'),
        ])
        self.assertEqual(parsed.session_id, 'abc-123')
        self.assertEqual(parsed.cwd, '/work/proj')
        self.assertEqual(parsed.started_at, '2026-01-01T00:00:00Z')
        self.assertEqual(parsed.last_active, '2026-01-01T00:05:00Z')

    def test_missing_file_returns_empty_transcript(self):
        missing = os.path.join(self.tmpdir, 'nope-1.jsonl')
        parsed = parse_transcript(missing)
        self.assertEqual(parsed.session_id, 'nope-1')
        self.assertEqual(parsed.messages, [])
        self.assertEqual(parsed.cwd, '')
        self.assertIsNone(parsed.started_at)
        self.assertIsNone(parsed.last_active)

    def test_directory_path_returns_empty_transcript(self):
        d = os.path.join(self.tmpdir, 'dir-1.jsonl')
        os.mkdir(d)
        parsed = parse_transcript(d)
        self.assertEqual(parsed.session_id, 'dir-1')
        self.assertEqual(parsed.messages, [])

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'root ignores file mode 000')
    def test_unreadable_file_returns_empty_transcript(self):
        _write_jsonl(self.path, [_entry('user', 'hello')])
        os.chmod(self.path, 0)
        try:
            parsed = parse_transcript(self.path)
        finally:
            os.chmod(self.path, 0o600)
        self.assertEqual(parsed.session_id, 'abc-123')
        self.assertEqual(parsed.messages, [])


class TestResolveRepoKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_real_git_repo_returns_its_root(self):
        subprocess.run(['git', 'init', '-q', self.tmp], check=True)
        self.assertEqual(resolve_repo_key(self.tmp), os.path.realpath(self.tmp))

    def test_linked_worktree_maps_to_main_repo(self):
        fake = unittest.mock.MagicMock(returncode=0, stdout='/repo/.git\n')
        with unittest.mock.patch('subprocess.run', return_value=fake):
            self.assertEqual(resolve_repo_key(self.tmp), '/repo')

    def test_relative_result_resolved_against_cwd(self):
        fake = unittest.mock.MagicMock(returncode=0, stdout='.git\n')
        with unittest.mock.patch('subprocess.run', return_value=fake):
            self.assertEqual(resolve_repo_key(self.tmp), os.path.realpath(self.tmp))

    def test_bare_repo_returns_common_dir(self):
        fake = unittest.mock.MagicMock(returncode=0, stdout='/srv/repo.git\n')
        with unittest.mock.patch('subprocess.run', return_value=fake):
            self.assertEqual(resolve_repo_key(self.tmp), '/srv/repo.git')

    def test_non_git_dir_returns_cwd(self):
        self.assertEqual(resolve_repo_key(self.tmp), self.tmp)

    def test_nonexistent_path_returns_path(self):
        missing = os.path.join(self.tmp, 'nope')
        self.assertEqual(resolve_repo_key(missing), missing)

    def test_git_missing_returns_cwd(self):
        with unittest.mock.patch('subprocess.run', side_effect=FileNotFoundError):
            self.assertEqual(resolve_repo_key(self.tmp), self.tmp)

    def test_timeout_returns_cwd(self):
        with unittest.mock.patch('subprocess.run',
                                 side_effect=subprocess.TimeoutExpired('git', 5)):
            self.assertEqual(resolve_repo_key(self.tmp), self.tmp)

    def test_empty_cwd_returns_empty(self):
        self.assertEqual(resolve_repo_key(''), '')


class TestIngestTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.folder = os.path.join(self.tmp, 'projects', '-work-Robinina')
        os.makedirs(self.folder)
        self.path = os.path.join(self.folder, 'sess-0001.jsonl')
        self.db = Database(os.path.join(self.tmp, 'catalog.db'))
        self.db.create_schema()
        self._turns = [_entry('user', 'first question'),
                       _entry('assistant', 'an answer'),
                       _entry('user', 'second question')]
        _write_jsonl(self.path, self._turns)
        for name, value in (('ingest_redact', True), ('ingest_extra_patterns', []),
                            ('ingest_include_subagents', False), ('ingest_folders', [])):
            patcher = unittest.mock.patch.object(
                type(towit_ingest.config), name, new_callable=unittest.mock.PropertyMock,
                return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def _rows(self, conv_id='sess-0001'):
        with self.db.connect() as conn:
            return conn.execute(
                'SELECT seq, role, text FROM messages WHERE conversation_id = ? ORDER BY seq',
                (conv_id,)).fetchall()

    def _conv(self, conv_id='sess-0001'):
        with self.db.connect() as conn:
            return conn.execute('SELECT * FROM conversations WHERE id = ?',
                                (conv_id,)).fetchone()

    def test_fresh_transcript_ingested_with_repo_key_and_folder(self):
        with unittest.mock.patch.object(towit_ingest, 'resolve_repo_key',
                                        return_value='/repo/root'):
            self.assertEqual(ingest_transcript(self.path, self.db), 'ingested')
        conv = self._conv()
        self.assertEqual(conv['repo_key'], '/repo/root')
        self.assertEqual(conv['folder'], self.folder)
        self.assertEqual(conv['cwd'], '/work/proj')
        self.assertEqual(len(self._rows()), 3)

    def test_second_call_unchanged_then_appended(self):
        self.assertEqual(ingest_transcript(self.path, self.db), 'ingested')
        self.assertEqual(ingest_transcript(self.path, self.db), 'unchanged')
        _write_jsonl(self.path, self._turns + [_entry('assistant', 'more')])
        self.assertEqual(ingest_transcript(self.path, self.db), 'appended')
        self.assertEqual(len(self._rows()), 4)

    def test_fewer_than_two_user_messages_skipped(self):
        _write_jsonl(self.path, [_entry('user', 'only one'), _entry('assistant', 'a'),
                                 _entry('assistant', 'b')])
        self.assertEqual(ingest_transcript(self.path, self.db), 'skipped')
        self.assertEqual(self._rows(), [])
        self.assertIsNone(self._conv())

    def test_missing_file_skipped(self):
        missing = os.path.join(self.folder, 'nope.jsonl')
        self.assertEqual(ingest_transcript(missing, self.db), 'skipped')

    def test_empty_parse_never_calls_archive_session(self):
        _write_jsonl(self.path, [])
        with unittest.mock.patch.object(Database, 'archive_session') as archive:
            self.assertEqual(ingest_transcript(self.path, self.db), 'skipped')
        archive.assert_not_called()

    def test_subagent_path_skipped_unless_included(self):
        sub = os.path.join(self.folder, 'sess-0001', 'subagents')
        os.makedirs(sub)
        sub_path = os.path.join(sub, 'agent-0001.jsonl')
        _write_jsonl(sub_path, self._turns)
        self.assertEqual(ingest_transcript(sub_path, self.db), 'skipped')
        self.assertEqual(self._rows('agent-0001'), [])
        self.ingest_include_subagents.return_value = True
        self.assertEqual(ingest_transcript(sub_path, self.db), 'ingested')
        self.assertEqual(len(self._rows('agent-0001')), 3)

    def test_symlinked_transcript_skipped(self):
        link = os.path.join(self.folder, 'linked-session.jsonl')
        os.symlink(self.path, link)
        self.assertEqual(ingest_transcript(link, self.db), 'skipped')
        self.assertEqual(self._rows('linked-session'), [])

    def test_forgotten_session_returns_forgotten(self):
        with self.db.connect() as conn:
            conn.execute('INSERT INTO forgotten (id) VALUES (?)', ('sess-0001',))
        self.assertEqual(ingest_transcript(self.path, self.db), 'forgotten')
        self.assertEqual(self._rows(), [])

    def test_folder_filter(self):
        self.ingest_folders.return_value = ['*Other*']
        self.assertEqual(ingest_transcript(self.path, self.db), 'skipped')
        self.assertEqual(self._rows(), [])
        self.ingest_folders.return_value = ['*Robinina*']
        self.assertEqual(ingest_transcript(self.path, self.db), 'ingested')
        self.assertEqual(len(self._rows()), 3)

    def test_secret_redacted_by_default(self):
        secret = 'AKIA' + 'A' * 16
        _write_jsonl(self.path, [_entry('user', f'key {secret}'), _entry('assistant', 'ok'),
                                 _entry('user', 'again')])
        ingest_transcript(self.path, self.db)
        text = self._rows()[0]['text']
        self.assertNotIn(secret, text)
        self.assertIn('[REDACTED:', text)

    def test_secret_stored_raw_when_redact_disabled(self):
        secret = 'AKIA' + 'A' * 16
        self.ingest_redact.return_value = False
        _write_jsonl(self.path, [_entry('user', f'key {secret}'), _entry('assistant', 'ok'),
                                 _entry('user', 'again')])
        ingest_transcript(self.path, self.db)
        self.assertIn(secret, self._rows()[0]['text'])

    def test_extra_patterns_passed_to_redact(self):
        self.ingest_extra_patterns.return_value = [r'hunter\d+']
        _write_jsonl(self.path, [_entry('user', 'pw hunter42'), _entry('assistant', 'ok'),
                                 _entry('user', 'again')])
        ingest_transcript(self.path, self.db)
        self.assertNotIn('hunter42', self._rows()[0]['text'])

    def test_lone_surrogate_message_ingests(self):
        raw = ('{"type":"user","timestamp":"2026-01-01T00:00:00Z","cwd":"/w",'
               '"message":{"role":"user","content":"bad \\ud800 char"}}')
        _write_jsonl(self.path, [raw, _entry('assistant', 'ok'), _entry('user', 'again')])
        self.assertEqual(ingest_transcript(self.path, self.db), 'ingested')
        self.assertIn('bad', self._rows()[0]['text'])
        self.assertEqual(ingest_transcript(self.path, self.db), 'unchanged')

    def test_invalid_session_id_skipped(self):
        for stem in ('bad id!', 'short'):
            bad = os.path.join(self.folder, stem + '.jsonl')
            _write_jsonl(bad, self._turns)
            with unittest.mock.patch.object(towit_ingest, 'parse_transcript') as parse:
                self.assertEqual(ingest_transcript(bad, self.db), 'skipped')
            parse.assert_not_called()
            self.assertEqual(self._rows(stem), [])
            self.assertIsNone(self._conv(stem))

    def test_forgotten_race_after_early_check(self):
        with self.db.connect() as conn:
            conn.execute('INSERT INTO forgotten (id) VALUES (?)', ('sess-0001',))
        with unittest.mock.patch.object(Database, 'is_forgotten', return_value=False):
            self.assertEqual(ingest_transcript(self.path, self.db), 'forgotten')
        self.assertEqual(self._rows(), [])
        self.assertIsNone(self._conv())

    def test_concurrent_ingest_of_same_file(self):
        dbs = [Database(self.db.db_path), Database(self.db.db_path)]
        results, errors = [], []

        def run(db):
            try:
                results.append(ingest_transcript(self.path, db))
            except Exception as exc:  # surfaced via the assertion below
                errors.append(exc)

        barrier = threading.Barrier(2)
        real_archive = Database.archive_session

        def synced(db_self, conv, messages):
            barrier.wait(timeout=10)  # both threads reach the transaction together
            return real_archive(db_self, conv, messages)

        threads = [threading.Thread(target=run, args=(d,)) for d in dbs]
        with unittest.mock.patch.object(Database, 'archive_session', synced):
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), ['ingested', 'unchanged'])
        self.assertEqual(len(self._rows()), len(parse_transcript(self.path).messages))


class TestCatchUp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = os.path.join(self.tmp, 'projects')
        self.folder = os.path.join(self.root, '-work-proj')
        os.makedirs(self.folder)
        self.db = Database(os.path.join(self.tmp, 'catalog.db'))
        self.db.create_schema()
        self.paths = {}
        for sid in ('sess-0001', 'sess-0002'):
            p = os.path.join(self.folder, sid + '.jsonl')
            _write_jsonl(p, [_entry('user', 'q one ' + sid), _entry('assistant', 'a'),
                             _entry('user', 'q two')])
            self.paths[sid] = p
        for name, value in (('ingest_redact', True), ('ingest_extra_patterns', []),
                            ('ingest_include_subagents', False), ('ingest_folders', [])):
            patcher = unittest.mock.patch.object(
                type(towit_ingest.config), name, new_callable=unittest.mock.PropertyMock,
                return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = unittest.mock.patch.object(towit_ingest, 'index_conversation')
        self.index = patcher.start()
        self.addCleanup(patcher.stop)

    def _catch_up(self):
        counts = towit_ingest.catch_up(root=self.root, db=self.db)
        self.index.assert_not_called()
        return counts

    def test_first_run_ingests_everything_and_stamps(self):
        self.assertIsNone(self.db.get_meta('last_catch_up'))
        counts = self._catch_up()
        self.assertEqual(counts, {'ingested': 2})
        stamp = self.db.get_meta('last_catch_up')
        self.assertIsNotNone(stamp)
        self.assertEqual(datetime.fromisoformat(stamp).utcoffset().total_seconds(), 0)

    def test_second_run_processes_nothing(self):
        self._catch_up()
        # make mtimes clearly older than the stamp minus slack
        old = time.time() - 3600
        for p in self.paths.values():
            os.utime(p, (old, old))
        counts = self._catch_up()
        self.assertEqual(counts.get('ingested', 0) + counts.get('appended', 0), 0)
        self.assertEqual(counts, {})

    def test_immediate_second_run_without_aging_is_all_unchanged(self):
        self._catch_up()
        counts = self._catch_up()  # mtimes fall inside the 60 s slack: rechecked, not rewritten
        self.assertEqual(counts, {'unchanged': 2})
        self.assertEqual(counts.get('ingested', 0) + counts.get('appended', 0), 0)

    def test_touched_file_reprocessed_alone(self):
        self._catch_up()
        old = time.time() - 3600
        for p in self.paths.values():
            os.utime(p, (old, old))
        with open(self.paths['sess-0002'], 'a') as fh:
            fh.write(json.dumps(_entry('assistant', 'more')) + '\n')
        counts = self._catch_up()
        self.assertEqual(counts, {'appended': 1})

    def test_mtime_within_slack_is_rechecked(self):
        self._catch_up()
        stamp = datetime.fromisoformat(self.db.get_meta('last_catch_up')).timestamp()
        os.utime(self.paths['sess-0001'], (stamp - 30, stamp - 30))
        old = stamp - 3600
        os.utime(self.paths['sess-0002'], (old, old))
        self.assertEqual(self._catch_up(), {'unchanged': 1})

    def test_subagent_and_symlink_files_skipped(self):
        sub = os.path.join(self.folder, 'sess-0001', 'subagents')
        os.makedirs(sub)
        _write_jsonl(os.path.join(sub, 'agent-x.jsonl'),
                     [_entry('user', 'a'), _entry('assistant', 'b'), _entry('user', 'c')])
        outside = os.path.join(self.tmp, 'real.jsonl')
        _write_jsonl(outside, [_entry('user', 'a'), _entry('assistant', 'b'), _entry('user', 'c')])
        os.symlink(outside, os.path.join(self.folder, 'linked-0003.jsonl'))
        counts = self._catch_up()
        self.assertEqual(counts.get('ingested'), 2)
        self.assertEqual(sum(counts.values()), 2)

    def test_one_bad_file_does_not_abort_scan(self):
        real = towit_ingest.ingest_transcript

        def flaky(path, db=None):
            if path.endswith('sess-0001.jsonl'):
                raise RuntimeError('boom')
            return real(path, db)

        with unittest.mock.patch.object(towit_ingest, 'ingest_transcript', side_effect=flaky):
            counts = towit_ingest.catch_up(root=self.root, db=self.db)
        self.assertEqual(counts, {'error': 1, 'ingested': 1})
        self.assertIsNotNone(self.db.get_meta('last_catch_up'))

    def test_missing_root_returns_empty(self):
        self.assertEqual(towit_ingest.catch_up(root=os.path.join(self.tmp, 'nope'), db=self.db), {})

    def test_missing_db_raises_systemexit_and_sets_no_stamp(self):
        db = Database(os.path.join(self.tmp, 'absent.db'))
        with self.assertRaises(SystemExit):
            towit_ingest.catch_up(root=self.root, db=db)


class TestCatchUpMain(unittest.TestCase):
    def setUp(self):
        os.environ.pop('TOWIT_INDEXING', None)

    def _main(self, side_effect=None):
        with unittest.mock.patch.object(towit_ingest, 'catch_up', side_effect=side_effect) as cu, \
             unittest.mock.patch.object(towit_ingest, 'ingest_transcript') as ing, \
             unittest.mock.patch('sys.argv', ['towit_ingest.py', '--catch-up']):
            towit_ingest.main()
        return cu, ing

    def test_catch_up_flag_runs_catch_up(self):
        cu, ing = self._main()
        cu.assert_called_once_with()
        ing.assert_not_called()

    def test_catch_up_systemexit_and_exception_swallowed(self):
        for exc in (SystemExit(1), RuntimeError('x')):
            with unittest.mock.patch.object(towit_ingest, 'get_error_logger') as lg:
                self._main(side_effect=exc)
            lg.return_value.exception.assert_called_once()

    def test_catch_up_honors_indexing_guard(self):
        with unittest.mock.patch.dict(os.environ, {'TOWIT_INDEXING': '1'}):
            cu, _ = self._main()
        cu.assert_not_called()


class TestIngestMain(unittest.TestCase):
    """towit_ingest.main(): the detached process spawned by the stop hook."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects = os.path.join(self.tmpdir, '.claude', 'projects', '-work-proj')
        os.makedirs(self.projects)
        self.path = os.path.join(self.projects, 'session-abc-123.jsonl')
        with open(self.path, 'w') as fh:
            fh.write('{}\n')
        self.env = unittest.mock.patch.dict(os.environ, {'HOME': self.tmpdir})
        self.env.start()
        os.environ.pop('TOWIT_INDEXING', None)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _main(self, argv=None, ingest='ingested', enabled=True):
        argv = [self.path] if argv is None else argv
        ingest_mock = unittest.mock.MagicMock(side_effect=ingest) \
            if isinstance(ingest, BaseException) else unittest.mock.MagicMock(return_value=ingest)
        with unittest.mock.patch.object(towit_ingest, 'ingest_transcript', ingest_mock), \
             unittest.mock.patch.object(towit_ingest, 'index_conversation') as index, \
             unittest.mock.patch.object(towit_ingest.config.__class__, 'indexing_enabled',
                                        new_callable=unittest.mock.PropertyMock,
                                        return_value=enabled), \
             unittest.mock.patch('sys.argv', ['towit_ingest.py'] + argv):
            towit_ingest.main()
        return ingest_mock, index

    def test_indexes_after_ingest(self):
        ingest, index = self._main()
        ingest.assert_called_once()
        index.assert_called_once_with(os.path.realpath(self.path))

    def test_indexing_disabled_never_indexes(self):
        ingest, index = self._main(enabled=False)
        ingest.assert_called_once()
        index.assert_not_called()

    def test_forgotten_and_skipped_never_index(self):
        for status in ('forgotten', 'skipped'):
            _, index = self._main(ingest=status)
            index.assert_not_called()

    def test_ingest_systemexit_is_swallowed_and_not_indexed(self):
        _, index = self._main(ingest=SystemExit(1))
        index.assert_not_called()

    def test_ingest_db_error_is_swallowed_and_not_indexed(self):
        import sqlite3
        _, index = self._main(ingest=sqlite3.OperationalError('database is locked'))
        index.assert_not_called()

    def test_index_error_is_swallowed(self):
        with unittest.mock.patch.object(towit_ingest.config.__class__, 'indexing_enabled',
                                        new_callable=unittest.mock.PropertyMock,
                                        return_value=True), \
             unittest.mock.patch.object(towit_ingest, 'index_conversation',
                                        side_effect=RuntimeError('boom')) as index, \
             unittest.mock.patch.object(towit_ingest, 'ingest_transcript',
                                        return_value='ingested'), \
             unittest.mock.patch('sys.argv', ['towit_ingest.py', self.path]):
            towit_ingest.main()  # must not raise
        index.assert_called_once()

    def test_subagent_transcript_is_archived_but_not_indexed(self):
        sub = os.path.join(self.projects, 'subagents')
        os.makedirs(sub)
        path = os.path.join(sub, 'agent-abc-123.jsonl')
        with open(path, 'w') as fh:
            fh.write('{}\n')
        with unittest.mock.patch.object(towit_ingest.config.__class__, 'ingest_include_subagents',
                                        new_callable=unittest.mock.PropertyMock,
                                        return_value=True):
            ingest, index = self._main(argv=[path])
        ingest.assert_called_once()
        index.assert_not_called()

    def test_path_outside_projects_root_is_ignored(self):
        outside = os.path.join(self.tmpdir, 'x.jsonl')
        ingest, index = self._main(argv=[outside])
        ingest.assert_not_called()
        index.assert_not_called()

    def test_recursion_guard(self):
        with unittest.mock.patch.dict(os.environ, {'TOWIT_INDEXING': '1'}):
            ingest, index = self._main()
        ingest.assert_not_called()
        index.assert_not_called()

    def test_missing_argument_is_ignored(self):
        ingest, index = self._main(argv=[], enabled=True)
        ingest.assert_not_called()
        index.assert_not_called()


if __name__ == '__main__':
    unittest.main()
