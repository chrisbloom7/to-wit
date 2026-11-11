# tests/helpers/towit_resume_test.py
# Tests for libexec/towit/towit_resume.py
#
# Run with: python3 tests/helpers/towit_resume_test.py

import unittest
import tempfile
import shutil
import subprocess
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
RESUME_SCRIPT = os.path.join(HELPERS_DIR, 'towit_resume.py')

sys.path.insert(0, HELPERS_DIR)
from towit_db import Database


def write_config(tmpdir, db_path):
    """Write a minimal config.toml containing db_path. Returns config file path."""
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def marker_path(config_path):
    return os.path.join(os.path.dirname(config_path), 'claude-calls.txt')


def run_resume(config_path, args=None):
    """Run towit_resume.py as a subprocess that can only reach a stub `claude`.

    The stub is first on PATH, records its working directory and argv to a marker
    file in the test's temp dir, and exits 0. HOME is a temp dir, so the real
    ~/.claude is never touched.
    """
    tmpdir = os.path.dirname(config_path)
    stub_dir = os.path.join(tmpdir, 'stubbin')
    home = os.path.join(tmpdir, 'home')
    os.makedirs(stub_dir, exist_ok=True)
    os.makedirs(home, exist_ok=True)
    stub = os.path.join(stub_dir, 'claude')
    with open(stub, 'w') as f:
        f.write('#!/bin/sh\nprintf \'%s\\n\' "$PWD $*" >> "' + marker_path(config_path) + '"\nexit 0\n')
    os.chmod(stub, 0o755)
    return subprocess.run(
        ['python3', RESUME_SCRIPT] + (args or []),
        env={**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home,
             'PATH': stub_dir + os.pathsep + os.environ.get('PATH', '')},
        capture_output=True,
        text=True
    )


class TestTowitResume(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cwd_dir = os.path.join(self.tmpdir, 'myapp')
        os.makedirs(self.cwd_dir)

        # Simulate the ~/.claude/projects folder structure
        self.projects_dir = os.path.join(self.tmpdir, 'projects', '-Users-alice')
        os.makedirs(self.projects_dir)

        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
        db = Database(self.db_path)
        db.create_schema()
        db.upsert_conversation({
            'id': 'conv-a',
            'folder': self.projects_dir,
            'cwd': self.cwd_dir,
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:30:00Z',
            'title': 'SQLite WAL mode deep dive',
            'summary': 'Deep dive into SQLite WAL mode',
            'topics': ['SQLite', 'WAL mode']
        })
        db.upsert_conversation({
            'id': 'conv-no-cwd',
            'folder': self.projects_dir,
            'cwd': None,
            'started_at': '2026-01-16T09:00:00Z',
            'last_active': '2026-01-16T09:45:00Z',
            'title': 'No cwd conversation',
            'summary': '',
            'topics': []
        })

        # Write a real JSONL transcript for conv-a
        open(os.path.join(self.projects_dir, 'conv-a.jsonl'), 'w').close()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unknown_session_exits_1(self):
        result = run_resume(self.config_path, ['nonexistent-id'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('session not found', result.stderr)

    def test_missing_session_id_exits_nonzero(self):
        result = run_resume(self.config_path, [])
        self.assertNotEqual(result.returncode, 0)

    def test_cwd_missing_transcript_intact_without_force_exits_1(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.config_path, ['conv-a'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('working directory no longer exists', result.stderr)
        self.assertIn('--force', result.stderr)

    def test_cwd_missing_transcript_intact_without_force_mentions_manual_resume(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.config_path, ['conv-a'])
        self.assertIn('claude --resume', result.stderr)

    def test_cwd_missing_transcript_intact_without_force_suggests_resume_subcommand(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.config_path, ['conv-a'])
        self.assertIn('towit resume --force', result.stderr)

    def test_cwd_and_transcript_both_missing_exits_1(self):
        shutil.rmtree(self.cwd_dir)
        os.remove(os.path.join(self.projects_dir, 'conv-a.jsonl'))
        result = run_resume(self.config_path, ['conv-a'])
        self.assertEqual(result.returncode, 1)
        self.assertIn('no longer resumable', result.stderr)

    def test_cwd_missing_with_force_recreates_directory(self):
        shutil.rmtree(self.cwd_dir)
        run_resume(self.config_path, ['--force', 'conv-a'])
        self.assertTrue(os.path.isdir(self.cwd_dir))

    def test_cwd_missing_with_force_warns_about_recreation(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.config_path, ['--force', 'conv-a'])
        self.assertIn('recreated missing directory', result.stderr)

    def calls(self):
        try:
            with open(marker_path(self.config_path)) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def test_valid_session_execs_claude_resume_in_the_session_cwd(self):
        result = run_resume(self.config_path, ['conv-a'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(),
                         [os.path.realpath(self.cwd_dir) + ' --resume conv-a'])

    def test_force_execs_claude_resume_after_recreating_the_cwd(self):
        shutil.rmtree(self.cwd_dir)
        result = run_resume(self.config_path, ['--force', 'conv-a'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(),
                         [os.path.realpath(self.cwd_dir) + ' --resume conv-a'])

    def test_failures_never_reach_claude(self):
        shutil.rmtree(self.cwd_dir)
        run_resume(self.config_path, ['conv-a'])
        run_resume(self.config_path, ['nonexistent-id'])
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
