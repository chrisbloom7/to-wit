# tests/helpers/towit_hook_test.py
# Tests for libexec/towit/towit_hook.py
#
# Run with: python3 tests/helpers/towit_hook_test.py

import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)


class TestHook(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects = os.path.join(self.tmpdir, '.claude', 'projects', '-work-proj')
        os.makedirs(self.projects)
        self.transcript = os.path.join(self.projects, 'session-abc-123.jsonl')
        with open(self.transcript, 'w') as fh:
            fh.write('{}\n')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_hook(self, payload, popen_side_effect=None):
        """Run towit_hook.main() with HOME isolated; return (exit_code, Popen mock)."""
        with patch.dict(os.environ, {'HOME': self.tmpdir}):
            os.environ.pop('TOWIT_INDEXING', None)
            import towit_hook
            towit_hook = importlib.reload(towit_hook)
            with patch('sys.stdin', io.StringIO(json.dumps(payload))), \
                 patch('subprocess.Popen', side_effect=popen_side_effect) as popen:
                with self.assertRaises(SystemExit) as cm:
                    towit_hook.main()
        return cm.exception.code, popen

    def test_spawns_ingest_with_validated_path(self):
        code, popen = self._run_hook({'session_id': 'session-abc-123',
                                      'transcript_path': self.transcript})
        self.assertEqual(code, 0)
        popen.assert_called_once()
        argv = popen.call_args[0][0]
        self.assertEqual(os.path.basename(argv[1]), 'towit_ingest.py')
        self.assertEqual(argv[2], os.path.realpath(self.transcript))

    def test_exits_zero_when_spawn_raises(self):
        code, popen = self._run_hook({'transcript_path': self.transcript},
                                     popen_side_effect=OSError('boom'))
        self.assertEqual(code, 0)
        popen.assert_called_once()

    def test_path_outside_projects_root_not_spawned(self):
        outside = os.path.join(self.tmpdir, 'elsewhere.jsonl')
        with open(outside, 'w') as fh:
            fh.write('{}\n')
        code, popen = self._run_hook({'transcript_path': outside})
        self.assertEqual(code, 0)
        popen.assert_not_called()

    def test_recursion_guard_exits_before_reading_config(self):
        sys.modules.pop('towit_hook', None)
        with patch.dict(os.environ, {'HOME': self.tmpdir, 'TOWIT_INDEXING': '1'}), \
             patch('subprocess.Popen') as popen:
            with self.assertRaises(SystemExit) as cm:
                import towit_hook  # noqa: F401
        self.assertEqual(cm.exception.code, 0)
        popen.assert_not_called()
        self.assertNotIn('towit_hook', sys.modules)


if __name__ == '__main__':
    unittest.main()
