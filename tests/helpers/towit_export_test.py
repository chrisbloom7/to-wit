# tests/helpers/towit_export_test.py
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit')))
import towit_export
from towit_config import config
from towit_db import Database


class TestCallClaudeEnvironment(unittest.TestCase):
    def test_claude_subprocess_env_is_scoped_to_the_allowlist(self):
        completed = MagicMock(returncode=0, stdout='summary\n', stderr='')
        with patch.dict(os.environ, {'UNRELATED_SECRET_TOKEN': 'hunter2', 'ANTHROPIC_API_KEY': 'kept'}), \
             patch('towit_export.subprocess.run', return_value=completed) as run:
            self.assertEqual(towit_export._call_claude('prompt'), 'summary')
        env = run.call_args.kwargs['env']
        self.assertTrue('UNRELATED_SECRET_TOKEN' not in env, 'non-allowlisted variable leaked to claude')
        self.assertEqual(env.get('ANTHROPIC_API_KEY'), 'kept')
        self.assertEqual(env.get('TOWIT_INDEXING'), '1')
        self.assertTrue('PATH' in env, 'PATH missing from claude env')


# Fake secrets are assembled from pieces so no scanner sees a literal token in this file.
FAKE_KEY = 'sk-' + 'ant-' + 'api03-' + 'A1b2C3d4E5f6G7h8I9j0'
EXTRA_SECRET = 'ZQX' + '-internal-' + 'codeword'


class TestSummarizeRedaction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = Database(os.path.join(self.tmp, 'catalog.db'))
        self.db.create_schema()
        self.completed = MagicMock(returncode=0, stdout='summary\n', stderr='')

    def patch_config(self, redact=True, extra=()):
        for name, value in (('ingest_redact', redact), ('ingest_extra_patterns', list(extra))):
            patcher = patch.object(type(config), name, new_callable=unittest.mock.PropertyMock,
                                   return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_session(self, sid, texts, summary='s', title='t'):
        path = os.path.join(self.tmp, sid + '.jsonl')
        with open(path, 'w', encoding='utf-8') as fh:
            for i, text in enumerate(texts):
                role = 'user' if i % 2 == 0 else 'assistant'
                fh.write(json.dumps({'type': 'message',
                                     'message': {'role': role, 'content': text}}) + '\n')
        self.db.upsert_conversation({
            'id': sid, 'folder': self.tmp, 'cwd': '/w', 'started_at': '2026-01-01T00:00:00Z',
            'last_active': None, 'title': title, 'summary': summary, 'topics': ['demo'],
            'keywords': []})

    def sent_prompt(self, run):
        self.assertEqual(run.call_count, 1)
        return run.call_args.args[0][2]

    def test_single_summarize_redacts_transcript_before_claude(self):
        self.patch_config()
        self.add_session('sess-0001', ['my key is ' + FAKE_KEY, 'noted', 'and ' + EXTRA_SECRET])
        with patch('towit_export.subprocess.run', return_value=self.completed) as run, \
             patch('builtins.print'):
            towit_export.export_single(self.db, 'sess-0001', 'md', True)
        prompt = self.sent_prompt(run)
        self.assertNotIn(FAKE_KEY, prompt)
        self.assertIn('[REDACTED:anthropic_key]', prompt)
        self.assertIn('my key is', prompt)

    def test_single_summarize_honors_extra_patterns(self):
        self.patch_config(extra=[EXTRA_SECRET])
        self.add_session('sess-0001', ['one ' + EXTRA_SECRET, 'two'])
        with patch('towit_export.subprocess.run', return_value=self.completed) as run, \
             patch('builtins.print'):
            towit_export.export_single(self.db, 'sess-0001', 'md', True)
        self.assertNotIn(EXTRA_SECRET, self.sent_prompt(run))

    def test_single_summarize_unchanged_when_ingest_redact_is_off(self):
        self.patch_config(redact=False)
        self.add_session('sess-0001', ['my key is ' + FAKE_KEY, 'noted'])
        with patch('towit_export.subprocess.run', return_value=self.completed) as run, \
             patch('builtins.print'):
            towit_export.export_single(self.db, 'sess-0001', 'md', True)
        self.assertIn(FAKE_KEY, self.sent_prompt(run))

    def test_topic_summarize_redacts_stored_summaries(self):
        self.patch_config()
        self.add_session('sess-0001', ['a', 'b'], summary='leaked ' + FAKE_KEY)
        with patch('towit_export.subprocess.run', return_value=self.completed) as run, \
             patch('builtins.print'):
            towit_export.export_topic(self.db, 'demo', 'md', True)
        prompt = self.sent_prompt(run)
        self.assertNotIn(FAKE_KEY, prompt)
        self.assertIn('[REDACTED:anthropic_key]', prompt)

    def test_topic_summarize_unchanged_when_ingest_redact_is_off(self):
        self.patch_config(redact=False)
        self.add_session('sess-0001', ['a', 'b'], summary='leaked ' + FAKE_KEY)
        with patch('towit_export.subprocess.run', return_value=self.completed) as run, \
             patch('builtins.print'):
            towit_export.export_topic(self.db, 'demo', 'md', True)
        self.assertIn(FAKE_KEY, self.sent_prompt(run))

    def test_non_summarize_export_is_not_redacted(self):
        self.patch_config()
        self.add_session('sess-0001', ['my key is ' + FAKE_KEY, 'noted'])
        with patch('towit_export.subprocess.run') as run, patch('builtins.print') as pr:
            towit_export.export_single(self.db, 'sess-0001', 'md', False)
        run.assert_not_called()
        self.assertIn(FAKE_KEY, pr.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
