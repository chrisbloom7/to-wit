# tests/helpers/towit_pipe_test.py
# Tests for libexec/towit/towit_pipe.py (quiet exit when stdout is a closed pipe)
#
# Run with: python3 tests/helpers/towit_pipe_test.py

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))

# A script that runs `body` (the text of a main() function) through run_cli
SCRIPT = '''
import sys
sys.path.insert(0, {helpers!r})
from towit_pipe import run_cli, quiet_broken_pipe

def main():
{body}

run_cli(main)
'''


class PipeTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def write_script(self, body, template=SCRIPT):
        path = os.path.join(self.tmpdir, 'script.py')
        indented = '\n'.join('    ' + line for line in body.strip('\n').splitlines())
        with open(path, 'w') as f:
            f.write(template.format(helpers=HELPERS_DIR, body=indented))
        return path

    def run_script(self, body, template=SCRIPT):
        return subprocess.run(['python3', self.write_script(body, template)],
                              capture_output=True, text=True)

    def run_closed_early(self, body, template=SCRIPT):
        """Run the script, read one line, close the pipe, and return (returncode, stderr)."""
        proc = subprocess.Popen(['python3', self.write_script(body, template)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.stdout.readline()
        proc.stdout.close()
        _, stderr = proc.communicate(timeout=30)
        return proc.returncode, stderr.decode()


class TestRunCli(PipeTestBase):
    def test_large_output_with_reader_closing_early_exits_141_quietly(self):
        code, stderr = self.run_closed_early("for i in range(5000):\n    print('x' * 100)")
        self.assertEqual(code, 141)
        self.assertEqual(stderr, '')

    def test_short_output_failing_only_at_final_flush_exits_141_quietly(self):
        # The reader is gone before the script prints anything, so the write is only
        # buffered and the error would surface at interpreter shutdown without run_cli.
        body = "import time\ntime.sleep(0.5)\nprint('late line')"
        proc = subprocess.Popen(['python3', self.write_script(body)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.stdout.close()
        _, stderr = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 141)
        self.assertEqual(stderr.decode(), '')

    def test_other_exceptions_still_traceback_and_exit_nonzero(self):
        result = self.run_script("raise ValueError('boom')")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Traceback', result.stderr)
        self.assertIn('ValueError: boom', result.stderr)

    def test_system_exit_code_passes_through(self):
        result = self.run_script("sys.exit(3)")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stderr, '')

    def test_success_returns_normally_and_output_is_written(self):
        result = self.run_script("print('hello')")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'hello\n')
        self.assertEqual(result.stderr, '')


# Uses the context manager around the print site only
CM_SCRIPT = '''
import sys
sys.path.insert(0, {helpers!r})
from towit_pipe import quiet_broken_pipe

def main():
{body}

main()
'''


class TestQuietBrokenPipe(PipeTestBase):
    def test_broken_pipe_inside_block_exits_141_quietly(self):
        body = "with quiet_broken_pipe():\n    for i in range(5000):\n        print('x' * 100)"
        code, stderr = self.run_closed_early(body, CM_SCRIPT)
        self.assertEqual(code, 141)
        self.assertEqual(stderr, '')

    def test_broken_pipe_from_elsewhere_is_not_swallowed(self):
        # A BrokenPipeError raised outside the wrapped block (for example by a child
        # process) must not be mistaken for a closed stdout.
        body = "raise BrokenPipeError('from a child')\nwith quiet_broken_pipe():\n    print('unused')"
        result = self.run_script(body, CM_SCRIPT)
        self.assertNotEqual(result.returncode, 141)
        self.assertIn('BrokenPipeError', result.stderr)

    def test_other_exceptions_inside_block_propagate(self):
        body = "with quiet_broken_pipe():\n    raise ValueError('boom')"
        result = self.run_script(body, CM_SCRIPT)
        self.assertIn('ValueError: boom', result.stderr)

    def test_clean_block_returns_normally(self):
        result = self.run_script("with quiet_broken_pipe():\n    print('ok')", CM_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'ok\n')


if __name__ == '__main__':
    unittest.main()
