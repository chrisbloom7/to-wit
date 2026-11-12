# tests/helpers/towit_show_test.py
# Tests for libexec/towit/towit_show.py and Database.get_messages
#
# Run with: python3 tests/helpers/towit_show_test.py

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
SHOW_SCRIPT = os.path.join(HELPERS_DIR, 'towit_show.py')

sys.path.insert(0, HELPERS_DIR)
from towit_db import Database

CONV = {
    'id': 'conv-show', 'folder': '/f', 'cwd': '/work/proj',
    'started_at': '2026-01-15T10:00:00Z', 'last_active': '2026-01-15T11:00:00Z',
    'repo_key': 'proj', 'source_path': '/f/conv-show.jsonl',
}


def make_messages(n):
    return [{'role': 'user' if i % 2 == 0 else 'assistant',
             'ts': f'2026-01-15T10:{i:02d}:00Z', 'text': f'message number {i}'}
            for i in range(n)]


class ShowTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = os.path.join(self.tmpdir, 'config.toml')
        with open(self.config_path, 'w') as f:
            f.write(f'[database]\npath = "{self.db_path}"\n')
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def archive(self, messages, conv_id='conv-show', **overrides):
        self.db.archive_session({**CONV, 'id': conv_id, **overrides}, messages)

    def run_show(self, args):
        return subprocess.run(
            ['python3', SHOW_SCRIPT] + args,
            env={**os.environ, 'TOWIT_CONFIG_PATH': self.config_path},
            capture_output=True, text=True,
        )


class TestGetMessages(ShowTestBase):
    def setUp(self):
        super().setUp()
        self.archive(make_messages(20))

    def seqs(self, **kw):
        return [m['seq'] for m in self.db.get_messages('conv-show', **kw)]

    def test_all_messages_in_seq_order(self):
        msgs = self.db.get_messages('conv-show')
        self.assertEqual([m['seq'] for m in msgs], list(range(20)))
        self.assertEqual(set(msgs[0]), {'seq', 'role', 'ts', 'text'})
        self.assertEqual(msgs[3]['text'], 'message number 3')

    def test_around_with_context(self):
        self.assertEqual(self.seqs(around=10, context=2), [8, 9, 10, 11, 12])

    def test_default_context_is_five(self):
        self.assertEqual(self.seqs(around=10), list(range(5, 16)))

    def test_clamps_at_start(self):
        self.assertEqual(self.seqs(around=1, context=3), [0, 1, 2, 3, 4])

    def test_clamps_at_end(self):
        self.assertEqual(self.seqs(around=18, context=3), [15, 16, 17, 18, 19])

    def test_around_beyond_end_partial_window(self):
        self.assertEqual(self.seqs(around=22, context=3), [19])

    def test_window_entirely_out_of_range_is_empty(self):
        self.assertEqual(self.seqs(around=40, context=2), [])

    def test_context_zero_returns_only_target(self):
        self.assertEqual(self.seqs(around=7, context=0), [7])

    def test_unknown_conversation_is_empty(self):
        self.assertEqual(self.db.get_messages('nope'), [])

    def test_other_conversations_not_mixed_in(self):
        self.archive(make_messages(3), conv_id='other')
        self.assertEqual(len(self.db.get_messages('conv-show')), 20)

    def test_show_header_unknown_is_none(self):
        self.assertIsNone(self.db.get_show_header('nope'))

    def test_show_header_title_falls_back_to_first_user_message(self):
        header = self.db.get_show_header('conv-show')
        self.assertEqual(header['title'], 'message number 0')
        self.assertTrue(header['archived'])
        self.assertEqual(header['repo_key'], 'proj')


class TestShowCli(ShowTestBase):
    def test_full_conversation_human_output(self):
        self.archive(make_messages(4))
        r = self.run_show(['conv-show'])
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertIn('conv-show', lines[0])
        self.assertIn('message number 0', lines[0])  # title fallback
        self.assertIn('proj', lines[0])
        self.assertIn('2026-01-15', lines[0])
        self.assertIn('[0] user (2026-01-15T10:00:00Z)', r.stdout)
        self.assertIn('[3] assistant (2026-01-15T10:03:00Z)', r.stdout)
        self.assertLess(r.stdout.index('[0]'), r.stdout.index('[3]'))
        self.assertNotIn('>>', r.stdout)

    def test_around_marks_target(self):
        self.archive(make_messages(20))
        r = self.run_show(['conv-show', '--around', '10', '--context', '1'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('>> [10]', r.stdout)
        self.assertIn('[9] ', r.stdout)
        self.assertIn('[11] ', r.stdout)
        self.assertNotIn('[8] ', r.stdout)
        self.assertNotIn('[12] ', r.stdout)
        self.assertEqual(r.stdout.count('>>'), 1)

    def test_json_is_valid_array(self):
        self.archive(make_messages(4))
        r = self.run_show(['conv-show', '--format', 'json'])
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual([m['seq'] for m in data], [0, 1, 2, 3])
        self.assertEqual(set(data[0]), {'seq', 'role', 'ts', 'text'})

    def test_json_around(self):
        self.archive(make_messages(20))
        r = self.run_show(['conv-show', '--around', '10', '--context', '2', '--format', 'json'])
        self.assertEqual([m['seq'] for m in json.loads(r.stdout)], [8, 9, 10, 11, 12])

    def test_unknown_id_not_found(self):
        r = self.run_show(['nope'])
        self.assertEqual(r.returncode, 1)
        self.assertIn('not found', r.stderr)

    def test_known_id_without_archive_points_to_backfill(self):
        self.db.upsert_conversation({
            'id': 'legacy', 'folder': '/f', 'cwd': '/x', 'started_at': '2026-01-01T00:00:00Z',
            'last_active': '2026-01-01T00:00:00Z', 'title': 'Legacy', 'summary': 's',
            'topics': [], 'keywords': [],
        })
        r = self.run_show(['legacy'])
        self.assertEqual(r.returncode, 1)
        self.assertIn('towit backfill', r.stderr)
        self.assertNotIn('not found', r.stderr)

    def test_around_out_of_range_exits_1(self):
        self.archive(make_messages(3))
        r = self.run_show(['conv-show', '--around', '50', '--context', '1'])
        self.assertEqual(r.returncode, 1)
        self.assertIn('50', r.stderr)

    def test_bad_around_values_exit_1(self):
        self.archive(make_messages(3))
        for bad in ('-1', 'abc', '1.5'):
            r = self.run_show(['conv-show', '--around', bad])
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn('--around', r.stderr)

    def test_bad_context_values_exit_1(self):
        self.archive(make_messages(3))
        for bad in ('-1', 'x'):
            r = self.run_show(['conv-show', '--around', '1', '--context', bad])
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn('--context', r.stderr)

    def test_context_without_around_is_ignored(self):
        self.archive(make_messages(4))
        r = self.run_show(['conv-show', '--context', '1'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('[0] ', r.stdout)
        self.assertIn('[3] ', r.stdout)

    def test_human_output_strips_terminal_escapes(self):
        evil = ('plain \x1b[31mred\x1b[0m \x1b]0;pwned title\x07 \x1b]8;;http://x\x1b\\link\x1b]8;;\x1b\\ '
                'bell\x07 nul\x00 bs\x08 cr\rX c1\x9b31m \x85 ok\tTab\nline2 \x1bP dcs\x1b\\ end')
        self.archive([{'role': 'user', 'ts': '2026-01-15T10:00:00Z\x1b[2J', 'text': evil},
                      {'role': 'assistant', 'ts': None, 'text': 'fine'}])
        r = self.run_show(['conv-show'])
        self.assertEqual(r.returncode, 0, r.stderr)
        for ch in r.stdout:
            if ch not in '\n\t':
                self.assertGreaterEqual(ord(ch), 0x20, repr(ch))
                self.assertFalse(0x7f <= ord(ch) <= 0x9f, repr(ch))
        for leaked in ('[31m', '[0m', 'pwned', ']8;;', '[2J'):
            self.assertNotIn(leaked, r.stdout)
        self.assertIn('plain red', r.stdout)
        self.assertIn('ok\tTab\nline2', r.stdout)
        self.assertIn('link', r.stdout)

    def test_json_preserves_exact_text(self):
        evil = 'a \x1b[31mred\x1b[0m \x07 b'
        self.archive([{'role': 'user', 'ts': None, 'text': evil},
                      {'role': 'assistant', 'ts': None, 'text': 'x'}])
        r = self.run_show(['conv-show', '--format', 'json'])
        self.assertEqual(json.loads(r.stdout)[0]['text'], evil)
        self.assertNotIn('\x1b', r.stdout)  # json.dumps escapes it

    def test_header_is_fully_sanitized(self):
        self.archive(make_messages(2), started_at='\x1b[2Jabcdefgh', last_active='\x1b]0;x\x07zzzzzzzzzzzz',
                     folder='/f\x1b[31m', cwd='/w\x1b[2J', repo_key=None)
        with self.db.connect() as conn:
            conn.execute("UPDATE conversations SET title = ? WHERE id = 'conv-show'", ('t\x1b[31mitle\x9b',))
        r = self.run_show(['conv-show'])
        self.assertEqual(r.returncode, 0, r.stderr)
        header = r.stdout.splitlines()[0]
        self.assertNotIn('\x1b', header)
        self.assertFalse([c for c in header if ord(c) < 0x20 or 0x7f <= ord(c) <= 0x9f])
        self.assertIn('title', header)

    def test_huge_numbers_rejected_cleanly(self):
        self.archive(make_messages(3))
        for flag, val in (('--around', '9223372036854775808'), ('--around', '9223372036854775807'),
                          ('--context', '99999999999999999999')):
            r = self.run_show(['conv-show', '--around', '1', flag, val] if flag == '--context'
                              else ['conv-show', flag, val])
            self.assertEqual(r.returncode, 1, (flag, val))
            self.assertIn('between 0 and 4611686018427387904', r.stderr)
            self.assertNotIn('Traceback', r.stderr)

    def test_json_ascii_escapes_dangerous_characters(self):
        text = 'a\x9bb\x7fc\u202ed'
        self.archive([{'role': 'user', 'ts': None, 'text': text}, {'role': 'assistant', 'ts': None, 'text': 'x'}])
        r = self.run_show(['conv-show', '--format', 'json'])
        for ch in ('\x9b', '\x7f', '\u202e'):
            self.assertNotIn(ch, r.stdout)
        self.assertEqual(json.loads(r.stdout)[0]['text'], text)

    def test_text_strips_bidi_controls(self):
        self.archive([{'role': 'user', 'ts': None, 'text': 'a\u202eb\u2066c\u2069d\u202ae'},
                      {'role': 'assistant', 'ts': None, 'text': 'x'}])
        r = self.run_show(['conv-show'])
        self.assertIn('abcde', r.stdout)

    def test_help_mentions_context_requires_around(self):
        r = self.run_show(['--help'])
        self.assertRegex(' '.join(r.stdout.split()), r'only (applies|used|has effect).*--around')


class TestGetMessagesHugeInts(ShowTestBase):
    def test_huge_values_do_not_raise(self):
        self.archive(make_messages(10))
        self.assertEqual(len(self.db.get_messages('conv-show', around=2**70, context=2**70)), 10)
        self.assertEqual([m['seq'] for m in self.db.get_messages('conv-show', around=5, context=2**70)],
                         list(range(10)))
        self.assertEqual(self.db.get_messages('conv-show', around=2**70, context=1), [])


class TestShowClosedPipe(ShowTestBase):
    def test_closed_pipe_exits_141_without_traceback(self):
        self.archive(make_messages(400))
        # No reader at all: the first write fails with EPIPE whatever the output size
        read_end, write_end = os.pipe()
        os.close(read_end)
        proc = subprocess.Popen(
            ['python3', SHOW_SCRIPT, 'conv-show'],
            env={**os.environ, 'TOWIT_CONFIG_PATH': self.config_path},
            stdout=write_end, stderr=subprocess.PIPE,
        )
        os.close(write_end)
        _, stderr = proc.communicate(timeout=60)
        self.assertNotIn('BrokenPipeError', stderr.decode())
        self.assertNotIn('Traceback', stderr.decode())
        self.assertEqual(proc.returncode, 141)


if __name__ == '__main__':
    unittest.main()
