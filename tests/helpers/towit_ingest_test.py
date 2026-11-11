# tests/helpers/towit_ingest_test.py
# Tests for libexec/towit/towit_ingest.py
#
# Run with: python3 tests/helpers/towit_ingest_test.py

import json
import os
import shutil
import sys
import tempfile
import unittest

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)

import towit_ingest
from towit_ingest import MAX_MESSAGE_CHARS, parse_transcript


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


if __name__ == '__main__':
    unittest.main()
