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


class TestIndexingConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- model ---

    def test_indexing_model_defaults_to_haiku(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_model, 'haiku')

    def test_indexing_model_reads_from_config(self):
        path = write_config(self.tmpdir, '[indexing]\nmodel = "sonnet"\n')
        cfg = Config(path=path)
        self.assertEqual(cfg.indexing_model, 'sonnet')

    def test_indexing_model_accepts_default_string(self):
        path = write_config(self.tmpdir, '[indexing]\nmodel = "default"\n')
        cfg = Config(path=path)
        self.assertEqual(cfg.indexing_model, 'default')

    def test_indexing_model_wrong_type_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[indexing]\nmodel = 42\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            result = cfg.indexing_model
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(result, 'haiku')

    # --- reindex_delta (in exchanges) ---

    def test_reindex_delta_defaults_to_2(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_reindex_delta, 2)

    def test_reindex_delta_reads_from_config(self):
        path = write_config(self.tmpdir, '[indexing]\nreindex_delta = 5\n')
        cfg = Config(path=path)
        self.assertEqual(cfg.indexing_reindex_delta, 5)

    def test_reindex_delta_wrong_type_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[indexing]\nreindex_delta = "two"\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            result = cfg.indexing_reindex_delta
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(result, 2)

    # --- topics ---

    def test_min_topics_defaults_to_1(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_min_topics, 1)

    def test_max_topics_defaults_to_5(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_max_topics, 5)

    def test_topics_reads_from_config(self):
        path = write_config(self.tmpdir, '[indexing]\nmin_topics = 2\nmax_topics = 4\n')
        cfg = Config(path=path)
        self.assertEqual(cfg.indexing_min_topics, 2)
        self.assertEqual(cfg.indexing_max_topics, 4)

    def test_topics_min_greater_than_max_warns_and_uses_defaults(self):
        path = write_config(self.tmpdir, '[indexing]\nmin_topics = 8\nmax_topics = 3\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            min_val = cfg.indexing_min_topics
            max_val = cfg.indexing_max_topics
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(min_val, 1)
        self.assertEqual(max_val, 5)

    def test_max_topics_wrong_type_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[indexing]\nmax_topics = "five"\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            result = cfg.indexing_max_topics
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(result, 5)

    # --- keywords ---

    def test_min_keywords_defaults_to_15(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_min_keywords, 15)

    def test_max_keywords_defaults_to_30(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_max_keywords, 30)

    def test_keywords_reads_from_config(self):
        path = write_config(self.tmpdir, '[indexing]\nmin_keywords = 5\nmax_keywords = 15\n')
        cfg = Config(path=path)
        self.assertEqual(cfg.indexing_min_keywords, 5)
        self.assertEqual(cfg.indexing_max_keywords, 15)

    def test_keywords_min_greater_than_max_warns_and_uses_defaults(self):
        path = write_config(self.tmpdir, '[indexing]\nmin_keywords = 20\nmax_keywords = 10\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            min_val = cfg.indexing_min_keywords
            max_val = cfg.indexing_max_keywords
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(min_val, 15)
        self.assertEqual(max_val, 30)

    def test_max_keywords_wrong_type_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[indexing]\nmax_keywords = true\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            result = cfg.indexing_max_keywords
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(result, 30)

    # --- summary sentences ---

    def test_min_summary_sentences_defaults_to_3(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_min_summary_sentences, 3)

    def test_max_summary_sentences_defaults_to_6(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_max_summary_sentences, 6)

    def test_summary_sentences_reads_from_config(self):
        path = write_config(self.tmpdir, '[indexing]\nmin_summary_sentences = 2\nmax_summary_sentences = 4\n')
        cfg = Config(path=path)
        self.assertEqual(cfg.indexing_min_summary_sentences, 2)
        self.assertEqual(cfg.indexing_max_summary_sentences, 4)

    def test_summary_sentences_min_greater_than_max_warns_and_uses_defaults(self):
        path = write_config(self.tmpdir, '[indexing]\nmin_summary_sentences = 5\nmax_summary_sentences = 2\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            min_val = cfg.indexing_min_summary_sentences
            max_val = cfg.indexing_max_summary_sentences
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(min_val, 3)
        self.assertEqual(max_val, 6)

    def test_max_summary_sentences_wrong_type_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[indexing]\nmax_summary_sentences = 3.5\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            result = cfg.indexing_max_summary_sentences
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(result, 6)

    # --- transcript_max_chars ---

    def test_transcript_max_chars_defaults_to_8000(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertEqual(cfg.indexing_transcript_max_chars, 8000)

    def test_transcript_max_chars_reads_from_config(self):
        path = write_config(self.tmpdir, '[indexing]\ntranscript_max_chars = 4000\n')
        cfg = Config(path=path)
        self.assertEqual(cfg.indexing_transcript_max_chars, 4000)

    def test_transcript_max_chars_wrong_type_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[indexing]\ntranscript_max_chars = "8k"\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            result = cfg.indexing_transcript_max_chars
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(result, 8000)

    # --- unknown key warning ---

    def test_unknown_key_in_indexing_section_warns(self):
        path = write_config(self.tmpdir, '[indexing]\nfuture_param = true\n')
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            cfg = Config(path=path)
            self.assertIn('Warning', mock_err.getvalue())


if __name__ == '__main__':
    unittest.main()
