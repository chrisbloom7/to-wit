# tests/helpers/towit_export_test.py
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit')))
import towit_export


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


if __name__ == '__main__':
    unittest.main()
