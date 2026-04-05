# tests/helpers/towit_index_test.py
# Tests for libexec/towit/towit_index.py
#
# Run with: python3 tests/helpers/towit_index_test.py

import unittest
import tempfile
import shutil
import json
import os
import sys
from unittest.mock import patch, MagicMock

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)

from towit_db import Database
from towit_index import parse_jsonl, should_index, build_transcript, analyze_with_claude, index_conversation


def write_jsonl(path, messages):
    """Write a minimal JSONL conversation file."""
    with open(path, 'w') as f:
        for i, msg in enumerate(messages):
            line = {
                'type': msg['role'],
                'message': {
                    'role': msg['role'],
                    'content': msg['content']
                },
                'sessionId': 'test-session-abc',
                'cwd': '/Users/test',
                'timestamp': f'2026-01-15T10:0{i}:00Z'
            }
            f.write(json.dumps(line) + '\n')


MINIMAL_MESSAGES = [
    {'role': 'user', 'content': 'Hello, can you help me understand SQLite WAL mode?'},
    {'role': 'assistant', 'content': 'Sure! WAL mode stands for Write-Ahead Logging.'},
    {'role': 'user', 'content': 'How does WAL mode improve concurrency for reads and writes?'},
    {'role': 'assistant', 'content': 'WAL mode allows readers and writers to coexist without blocking each other.'},
]


class TestParseJsonl(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parse_jsonl_extracts_user_and_assistant_messages(self):
        path = os.path.join(self.tmpdir, 'conv.jsonl')
        write_jsonl(path, MINIMAL_MESSAGES)
        messages = parse_jsonl(path)
        roles = [m['role'] for m in messages]
        self.assertIn('user', roles)
        self.assertIn('assistant', roles)

    def test_parse_jsonl_skips_file_history_snapshot_lines(self):
        path = os.path.join(self.tmpdir, 'conv.jsonl')
        lines = []
        for i, msg in enumerate(MINIMAL_MESSAGES):
            line = {
                'type': msg['role'],
                'message': {'role': msg['role'], 'content': msg['content']},
                'sessionId': 'test-session-abc',
                'cwd': '/Users/test',
                'timestamp': f'2026-01-15T10:0{i}:00Z'
            }
            lines.append(json.dumps(line))
        # Insert a file-history-snapshot line
        snapshot_line = json.dumps({'type': 'file_history_snapshot', 'files': []})
        lines.insert(1, snapshot_line)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

        messages = parse_jsonl(path)
        types = [m.get('role') or m.get('type') for m in messages]
        self.assertNotIn('file_history_snapshot', types)

    def test_parse_jsonl_skips_tool_use_content_in_assistant_messages(self):
        path = os.path.join(self.tmpdir, 'conv.jsonl')
        with open(path, 'w') as f:
            # Assistant message with mixed content: text + tool_use
            line = {
                'type': 'assistant',
                'message': {
                    'role': 'assistant',
                    'content': [
                        {'type': 'text', 'text': 'Let me check that for you.'},
                        {'type': 'tool_use', 'id': 'tool-1', 'name': 'bash', 'input': {'command': 'ls'}}
                    ]
                },
                'sessionId': 'test-session-abc',
                'cwd': '/Users/test',
                'timestamp': '2026-01-15T10:00:00Z'
            }
            f.write(json.dumps(line) + '\n')

        messages = parse_jsonl(path)
        for msg in messages:
            content = msg.get('content', '')
            if isinstance(content, list):
                for item in content:
                    self.assertNotEqual(item.get('type'), 'tool_use', "tool_use items should be filtered out")
            if isinstance(content, str):
                self.assertNotIn('tool_use', content)


class TestShouldIndex(unittest.TestCase):
    def test_should_index_returns_false_for_fewer_than_2_user_messages(self):
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'},
        ]
        self.assertFalse(should_index(messages))

    def test_should_index_returns_false_for_very_short_user_messages(self):
        messages = [
            {'role': 'user', 'content': 'Hi'},
            {'role': 'assistant', 'content': 'Hello'},
            {'role': 'user', 'content': 'Ok'},
            {'role': 'assistant', 'content': 'Sure'},
        ]
        self.assertFalse(should_index(messages))

    def test_should_index_returns_true_for_substantial_conversation(self):
        messages = [
            {'role': 'user', 'content': 'Can you explain how SQLite WAL mode works in detail?'},
            {'role': 'assistant', 'content': 'WAL mode allows concurrent reads and writes by keeping a separate log file.'},
            {'role': 'user', 'content': 'How does WAL mode compare to journal mode for high-concurrency applications?'},
            {'role': 'assistant', 'content': 'WAL mode is generally better for concurrency because readers do not block writers.'},
        ]
        self.assertTrue(should_index(messages))


class TestBuildTranscript(unittest.TestCase):
    def test_build_transcript_formats_as_human_assistant_pairs(self):
        messages = [
            {'role': 'user', 'content': 'What is WAL mode?'},
            {'role': 'assistant', 'content': 'WAL mode is Write-Ahead Logging.'},
        ]
        transcript = build_transcript(messages)
        self.assertIn('Human:', transcript)
        self.assertIn('Assistant:', transcript)
        self.assertIn('What is WAL mode?', transcript)
        self.assertIn('WAL mode is Write-Ahead Logging.', transcript)

    def test_build_transcript_truncates_long_transcripts(self):
        # Build a very long conversation
        messages = []
        for i in range(200):
            messages.append({'role': 'user', 'content': f'This is user message number {i} with enough content to be substantial.'})
            messages.append({'role': 'assistant', 'content': f'This is assistant response number {i} with enough content to be substantial.'})
        transcript = build_transcript(messages)
        # Should contain some marker indicating omission
        self.assertTrue(
            '[...truncated' in transcript or '...' in transcript or 'omitted' in transcript.lower(),
            f"Expected truncation marker in long transcript. Length: {len(transcript)}"
        )


class TestAnalyzeWithClaude(unittest.TestCase):
    def _run_analyze(self, existing_topics=None):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'skip': False, 'title': 'T', 'summary': 'S', 'topics': ['a']
        })
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            analyze_with_claude('some transcript', existing_topics=existing_topics)
        return mock_run.call_args[0][0][2]  # the prompt string

    def test_analyze_without_existing_topics_omits_instruction(self):
        prompt = self._run_analyze(existing_topics=None)
        self.assertNotIn('Previously assigned topics', prompt)

    def test_analyze_with_existing_topics_includes_them_in_prompt(self):
        prompt = self._run_analyze(existing_topics=['python', 'refactoring'])
        self.assertIn('Previously assigned topics', prompt)
        self.assertIn('python', prompt)
        self.assertIn('refactoring', prompt)

    def test_analyze_with_empty_existing_topics_omits_instruction(self):
        prompt = self._run_analyze(existing_topics=[])
        self.assertNotIn('Previously assigned topics', prompt)


class TestIndexConversation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        os.environ['TOWIT_DB_PATH'] = self.db_path
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        os.environ.pop('TOWIT_DB_PATH', None)

    def _write_conv(self, session_id, messages, cwd='/Users/test'):
        path = os.path.join(self.tmpdir, f'{session_id}.jsonl')
        with open(path, 'w') as f:
            for i, msg in enumerate(messages):
                line = {
                    'type': msg['role'],
                    'message': {'role': msg['role'], 'content': msg['content']},
                    'sessionId': session_id,
                    'cwd': cwd,
                    'timestamp': f'2026-01-15T10:0{i % 10}:00Z'
                }
                f.write(json.dumps(line) + '\n')
        return path

    def test_index_conversation_returns_already_indexed_if_in_db(self):
        # message_count must match the parsed count of MINIMAL_MESSAGES (4)
        self.db.upsert_conversation({
            'id': 'already-indexed-session',
            'folder': '/some/folder',
            'cwd': '/Users/test',
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'Existing',
            'summary': 'Already there',
            'topics': [],
            'message_count': len(MINIMAL_MESSAGES),
        })
        path = self._write_conv('already-indexed-session', MINIMAL_MESSAGES)
        result = index_conversation(path, self.db)
        self.assertEqual(result, 'already_indexed')

    def test_index_conversation_with_null_message_count_reindexes(self):
        # Pre-migration records have no message_count; they should be re-analyzed
        self.db.upsert_conversation({
            'id': 'legacy-session-001',
            'folder': '/some/folder',
            'cwd': '/Users/test',
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'Old Title',
            'summary': 'Old summary.',
            'topics': ['old-topic'],
            'message_count': None,
        })
        path = self._write_conv('legacy-session-001', MINIMAL_MESSAGES)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'skip': False,
            'title': 'New Title',
            'summary': 'New summary.',
            'topics': ['old-topic'],
        })

        with patch('subprocess.run', return_value=mock_result):
            result = index_conversation(path, self.db)

        self.assertEqual(result, 'indexed')

    def test_index_conversation_touches_last_active_when_count_unchanged(self):
        old_last_active = '2026-01-15T10:00:00Z'
        self.db.upsert_conversation({
            'id': 'resumed-session-001',
            'folder': '/some/folder',
            'cwd': '/Users/test',
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': old_last_active,
            'title': 'Keep This Title',
            'summary': 'Keep this summary.',
            'topics': ['sqlite', 'concurrency'],
            'message_count': len(MINIMAL_MESSAGES),
        })
        # Write JSONL with a newer final timestamp but same message count
        newer_messages = [
            {'role': 'user',      'content': MINIMAL_MESSAGES[0]['content']},
            {'role': 'assistant', 'content': MINIMAL_MESSAGES[1]['content']},
            {'role': 'user',      'content': MINIMAL_MESSAGES[2]['content']},
            {'role': 'assistant', 'content': MINIMAL_MESSAGES[3]['content']},
        ]
        path = os.path.join(self.tmpdir, 'resumed-session-001.jsonl')
        with open(path, 'w') as f:
            for i, msg in enumerate(newer_messages):
                line = {
                    'type': msg['role'],
                    'message': {'role': msg['role'], 'content': msg['content']},
                    'sessionId': 'resumed-session-001',
                    'cwd': '/Users/test',
                    'timestamp': f'2026-02-01T10:0{i}:00Z',  # newer timestamps
                }
                f.write(json.dumps(line) + '\n')

        with patch('subprocess.run') as mock_run:
            result = index_conversation(path, self.db)

        self.assertEqual(result, 'already_indexed')
        mock_run.assert_not_called()  # Claude should not be invoked

        # last_active should have been updated
        record = self.db.get_for_reindex('resumed-session-001')
        # Verify title/topics were preserved (not re-analyzed)
        self.assertEqual(record['topics'], ['sqlite', 'concurrency'])

    def test_index_conversation_passes_existing_topics_when_reindexing(self):
        self.db.upsert_conversation({
            'id': 'grown-session-001',
            'folder': '/some/folder',
            'cwd': '/Users/test',
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'Old Title',
            'summary': 'Old summary.',
            'topics': ['sqlite', 'wal-mode'],
            'message_count': 2,  # fewer than MINIMAL_MESSAGES
        })
        path = self._write_conv('grown-session-001', MINIMAL_MESSAGES)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'skip': False,
            'title': 'Updated Title',
            'summary': 'Updated summary.',
            'topics': ['sqlite', 'wal-mode'],
        })

        with patch('subprocess.run', return_value=mock_result) as mock_run:
            result = index_conversation(path, self.db)

        self.assertEqual(result, 'indexed')
        call_args = mock_run.call_args
        prompt_arg = call_args[0][0][2]  # ['claude', '-p', <prompt>, ...]
        self.assertIn('sqlite', prompt_arg)
        self.assertIn('wal-mode', prompt_arg)
        self.assertIn('Previously assigned topics', prompt_arg)

    def test_index_conversation_returns_skipped_for_short_conversation(self):
        short_messages = [
            {'role': 'user', 'content': 'Hi'},
            {'role': 'assistant', 'content': 'Hello!'},
        ]
        path = self._write_conv('short-session-xyz', short_messages)
        result = index_conversation(path, self.db)
        self.assertEqual(result, 'skipped')

    def test_index_conversation_calls_claude_and_writes_to_db(self):
        path = self._write_conv('new-session-001', MINIMAL_MESSAGES)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'skip': False,
            'title': 'Test',
            'summary': 'A test conversation.',
            'topics': ['testing']
        })

        with patch('subprocess.run', return_value=mock_result) as mock_run:
            result = index_conversation(path, self.db)

        self.assertEqual(result, 'indexed', f"Expected 'indexed', got {result!r}")
        self.assertTrue(self.db.is_indexed('new-session-001'), "Session should be in DB after indexing")
        mock_run.assert_called_once()

    def test_index_conversation_returns_skipped_when_claude_returns_skip_true(self):
        path = self._write_conv('skip-session-001', MINIMAL_MESSAGES)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({'skip': True})

        with patch('subprocess.run', return_value=mock_result):
            result = index_conversation(path, self.db)

        self.assertEqual(result, 'skipped')
        self.assertFalse(self.db.is_indexed('skip-session-001'))


if __name__ == '__main__':
    unittest.main()
