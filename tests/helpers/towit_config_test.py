# tests/helpers/towit_config_test.py
# Tests for libexec/towit/towit_config.py
#
# Run with: python3 tests/helpers/towit_config_test.py

import io
import os
import sys
import tempfile
import unittest
import unittest.mock

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)

import towit_config
from towit_config import Config, _DEFAULT_DB_PATH


def write_config(tmpdir, content):
    """Write content to a temp config.toml and return its path."""
    path = os.path.join(tmpdir, 'config.toml')
    with open(path, 'w') as f:
        f.write(content)
    return path


class TestConfigNoFile(unittest.TestCase):
    def test_missing_file_returns_default_db_path(self):
        cfg = Config(path='/nonexistent/config.toml')
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cfg.db_path, _DEFAULT_DB_PATH)

    def test_missing_file_produces_no_warnings(self):
        cfg = Config(path='/nonexistent/config.toml')
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
                _ = cfg.db_path
                self.assertEqual(mock_err.getvalue(), '')


class TestConfigValidToml(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reads_database_path(self):
        path = write_config(self.tmpdir, '[database]\npath = "/tmp/custom.db"\n')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cfg.db_path, '/tmp/custom.db')

    def test_expands_tilde_in_database_path(self):
        path = write_config(self.tmpdir, '[database]\npath = "~/.towit/custom.db"\n')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cfg.db_path, os.path.expanduser('~/.towit/custom.db'))

    def test_empty_config_returns_defaults(self):
        path = write_config(self.tmpdir, '')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cfg.db_path, _DEFAULT_DB_PATH)


class TestConfigBadToml(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bad_toml_warns_to_stderr(self):
        path = write_config(self.tmpdir, 'this is not [ valid toml !!!')
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            cfg = Config(path=path)
            self.assertIn('Warning', mock_err.getvalue())

    def test_bad_toml_returns_default_db_path(self):
        path = write_config(self.tmpdir, 'this is not [ valid toml !!!')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cfg.db_path, _DEFAULT_DB_PATH)


class TestConfigUnknownKeys(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unknown_section_warns(self):
        path = write_config(self.tmpdir, '[future_feature]\nsome_key = "value"\n')
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            cfg = Config(path=path)
            self.assertIn('Warning', mock_err.getvalue())

    def test_unknown_key_in_known_section_warns(self):
        path = write_config(self.tmpdir, '[database]\npath = "/tmp/ok.db"\nunknown_key = true\n')
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            cfg = Config(path=path)
            self.assertIn('Warning', mock_err.getvalue())

    def test_known_keys_still_work_after_unknown_key_warning(self):
        path = write_config(self.tmpdir, '[database]\npath = "/tmp/ok.db"\nunknown_key = true\n')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cfg.db_path, '/tmp/ok.db')


class TestConfigWrongType(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_wrong_type_for_database_path_warns(self):
        path = write_config(self.tmpdir, '[database]\npath = 42\n')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
                _ = cfg.db_path
                self.assertIn('Warning', mock_err.getvalue())

    def test_wrong_type_for_database_path_uses_default(self):
        path = write_config(self.tmpdir, '[database]\npath = 42\n')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cfg.db_path, _DEFAULT_DB_PATH)


class TestConfigDeprecatedEnvVar(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_towit_db_path_env_emits_deprecation_warning(self):
        cfg = Config(path='/nonexistent/config.toml')
        with unittest.mock.patch.dict(os.environ, {'TOWIT_DB_PATH': '/tmp/legacy.db'}):
            with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
                _ = cfg.db_path
                self.assertIn('deprecated', mock_err.getvalue().lower())

    def test_towit_db_path_env_value_is_used(self):
        cfg = Config(path='/nonexistent/config.toml')
        with unittest.mock.patch.dict(os.environ, {'TOWIT_DB_PATH': '/tmp/legacy.db'}):
            self.assertEqual(cfg.db_path, '/tmp/legacy.db')

    def test_towit_db_path_env_takes_precedence_over_config(self):
        path = write_config(self.tmpdir, '[database]\npath = "/tmp/from_config.db"\n')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {'TOWIT_DB_PATH': '/tmp/from_env.db'}):
            self.assertEqual(cfg.db_path, '/tmp/from_env.db')


if __name__ == '__main__':
    unittest.main()
