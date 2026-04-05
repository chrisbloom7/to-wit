# tests/helpers/towit_setup_test.py
# Tests for libexec/towit/towit_setup.py
#
# Run with: python3 tests/helpers/towit_setup_test.py

import unittest
import tempfile
import shutil
import sqlite3
import subprocess
import os
import sys

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
SETUP_SCRIPT = os.path.join(HELPERS_DIR, 'towit_setup.py')


def run_setup(db_path):
    """Run towit_setup.py as a subprocess with the given DB path."""
    return subprocess.run(
        ['python3', SETUP_SCRIPT],
        env={**os.environ, 'TOWIT_DB_PATH': db_path},
        capture_output=True,
        text=True
    )


class TestClaudecatSetup(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_db_file_at_towit_db_path(self):
        self.assertFalse(os.path.exists(self.db_path))
        result = run_setup(self.db_path)
        self.assertEqual(result.returncode, 0, f"setup exited {result.returncode}: {result.stderr}")
        self.assertTrue(os.path.exists(self.db_path), f"DB file not created at {self.db_path}")

    def test_prints_success_message_containing_path(self):
        result = run_setup(self.db_path)
        self.assertEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn(self.db_path, combined, f"Expected path in output, got: {combined!r}")

    def test_creates_parent_directory_if_missing(self):
        nested_path = os.path.join(self.tmpdir, 'subdir', 'nested', 'catalog.db')
        self.assertFalse(os.path.exists(os.path.dirname(nested_path)))
        result = run_setup(nested_path)
        self.assertEqual(result.returncode, 0, f"setup failed: {result.stderr}")
        self.assertTrue(os.path.exists(nested_path), f"DB file not created at {nested_path}")

    def test_does_not_overwrite_existing_db(self):
        # First run
        run_setup(self.db_path)
        mtime_after_first = os.path.getmtime(self.db_path)

        # Second run
        import time
        time.sleep(0.05)
        result = run_setup(self.db_path)
        self.assertEqual(result.returncode, 0, f"Second setup failed: {result.stderr}")

        mtime_after_second = os.path.getmtime(self.db_path)
        self.assertEqual(
            mtime_after_first, mtime_after_second,
            "DB file was modified on second setup — it should not be overwritten"
        )

    def test_second_run_prints_already_initialized(self):
        run_setup(self.db_path)
        result = run_setup(self.db_path)
        self.assertEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn('already', combined.lower(), f"Expected 'already' in output, got: {combined!r}")

    def test_db_contains_expected_tables_after_setup(self):
        run_setup(self.db_path)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        self.assertIn('conversations', tables, f"conversations table missing; found: {tables}")
        self.assertIn('topics', tables, f"topics table missing; found: {tables}")
        self.assertIn('conversation_topics', tables, f"conversation_topics table missing; found: {tables}")


if __name__ == '__main__':
    unittest.main()
