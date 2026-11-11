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
import unittest.mock
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

    def test_stop_and_session_end_spawn_detached_ingest(self):
        for event in ('Stop', 'SessionEnd'):
            code, popen = self._run_hook({'hook_event_name': event,
                                          'transcript_path': self.transcript})
            self.assertEqual(code, 0, event)
            popen.assert_called_once()
            argv = popen.call_args[0][0]
            self.assertEqual(os.path.basename(argv[1]), 'towit_ingest.py')
            self.assertEqual(argv[2], os.path.realpath(self.transcript))
            self.assertTrue(popen.call_args[1]['start_new_session'])

    def test_session_start_spawns_catch_up_without_transcript(self):
        code, popen = self._run_hook({'hook_event_name': 'SessionStart', 'source': 'startup'})
        self.assertEqual(code, 0)
        popen.assert_called_once()
        argv = popen.call_args[0][0]
        self.assertEqual(os.path.basename(argv[1]), 'towit_ingest.py')
        self.assertEqual(argv[2:], ['--catch-up'])
        self.assertTrue(popen.call_args[1]['start_new_session'])

    def test_unknown_event_spawns_nothing(self):
        code, popen = self._run_hook({'hook_event_name': 'PreToolUse',
                                      'transcript_path': self.transcript})
        self.assertEqual(code, 0)
        popen.assert_not_called()

    def test_invalid_transcript_for_session_end_spawns_nothing(self):
        outside = os.path.join(self.tmpdir, 'elsewhere.jsonl')
        with open(outside, 'w') as fh:
            fh.write('{}\n')
        for event, path in (('SessionEnd', outside), ('Stop', outside),
                            ('SessionEnd', '../../etc/passwd'), ('Stop', '')):
            code, popen = self._run_hook({'hook_event_name': event, 'transcript_path': path})
            self.assertEqual(code, 0)
            popen.assert_not_called()

    def test_exception_is_logged_and_exit_is_zero(self):
        with patch.dict(os.environ, {'HOME': self.tmpdir}):
            os.environ.pop('TOWIT_INDEXING', None)
            import towit_hook
            towit_hook = importlib.reload(towit_hook)
            logger = unittest.mock.MagicMock()
            with patch('sys.stdin', io.StringIO('{not json')), \
                 patch.object(towit_hook, 'get_error_logger', return_value=logger), \
                 patch('subprocess.Popen') as popen:
                with self.assertRaises(SystemExit) as cm:
                    towit_hook.main()
        self.assertEqual(cm.exception.code, 0)
        logger.exception.assert_called_once()
        popen.assert_not_called()

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
        saved = {k: sys.modules.pop(k, None) for k in ('towit_hook', 'towit_config')}
        try:
            with patch.dict(os.environ, {'HOME': self.tmpdir, 'TOWIT_INDEXING': '1'}), \
                 patch('subprocess.Popen') as popen:
                with self.assertRaises(SystemExit) as cm:
                    import towit_hook  # noqa: F401
            self.assertEqual(cm.exception.code, 0)
            popen.assert_not_called()
            self.assertNotIn('towit_hook', sys.modules)
            self.assertNotIn('towit_config', sys.modules)
        finally:
            for k, v in saved.items():
                sys.modules.pop(k, None)
                if v is not None:
                    sys.modules[k] = v


if __name__ == '__main__':
    unittest.main()
