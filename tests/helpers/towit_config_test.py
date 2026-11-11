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
from towit_config import Config, _DEFAULT_DB_PATH, is_valid_session_id


def _run_logger(home, code, config_path='default', umask=None):
    """Run code in a subprocess with a temp HOME; config_path=None leaves TOWIT_CONFIG_PATH unset."""
    import subprocess
    env = {'HOME': home, 'PATH': os.environ.get('PATH', '')}
    if config_path != 'default' and config_path is not None:
        env['TOWIT_CONFIG_PATH'] = config_path
    prefix = 'import os; os.umask(0o%o)\n' % umask if umask is not None else ''
    return subprocess.run(
        [sys.executable, '-c', prefix + 'import towit_config\n' + code],
        cwd=HELPERS_DIR, capture_output=True, text=True, env=env)


def _mode(path):
    return os.stat(path).st_mode & 0o777


class TestIsSubagentPath(unittest.TestCase):
    def _fn(self):
        fn = getattr(towit_config, 'is_subagent_path', None)
        self.assertIsNotNone(fn, 'towit_config.is_subagent_path does not exist yet')
        return fn

    def test_true_for_path_under_subagents_dir(self):
        self.assertIs(self._fn()('/home/u/.claude/projects/-w/sess-1/subagents/agent-1.jsonl'), True)

    def test_false_for_normal_path(self):
        self.assertIs(self._fn()('/home/u/.claude/projects/-w/sess-1.jsonl'), False)

    def test_false_when_subagents_lacks_surrounding_slashes(self):
        fn = self._fn()
        self.assertIs(fn('/x/mysubagents/y.jsonl'), False)
        self.assertIs(fn('/x/subagentsy/y.jsonl'), False)

    def test_relative_path_is_made_absolute_first(self):
        fn = self._fn()
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'subagents'))
            old = os.getcwd()
            os.chdir(tmp)
            try:
                self.assertIs(fn(os.path.join('subagents', 'a.jsonl')), True)
                self.assertIs(fn('a.jsonl'), False)
            finally:
                os.chdir(old)


class TestErrorLoggerDirectory(unittest.TestCase):
    def test_error_log_dir_created_owner_only(self):
        with tempfile.TemporaryDirectory() as home:
            cfgdir = os.path.join(home, 'cfgdir')
            result = _run_logger(home, "towit_config.get_error_logger()",
                                 os.path.join(cfgdir, 'config.toml'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(_mode(cfgdir), 0o700)

    def test_log_follows_config_dir_and_creates_it(self):
        with tempfile.TemporaryDirectory() as home:
            cfgdir = os.path.join(home, 'cfgdir')
            result = _run_logger(home, "towit_config.get_error_logger().error('boom')",
                                 os.path.join(cfgdir, 'config.toml'), umask=0o022)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = os.path.join(cfgdir, 'errors.log')
            self.assertTrue(os.path.exists(log), 'errors.log missing in config dir')
            with open(log) as fh:
                self.assertIn('boom', fh.read())
            self.assertEqual(_mode(cfgdir), 0o700)
            self.assertEqual(_mode(log), 0o600)
            self.assertFalse(os.path.exists(os.path.join(home, '.towit')))

    def test_existing_config_dir_left_as_is(self):
        with tempfile.TemporaryDirectory() as home:
            cfgdir = os.path.join(home, 'cfgdir')
            os.makedirs(cfgdir)
            os.chmod(cfgdir, 0o755)
            result = _run_logger(home, "towit_config.get_error_logger().error('boom')",
                                 os.path.join(cfgdir, 'config.toml'), umask=0o022)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = os.path.join(cfgdir, 'errors.log')
            self.assertTrue(os.path.exists(log), 'errors.log missing in config dir')
            self.assertEqual(_mode(cfgdir), 0o755)
            self.assertEqual(_mode(log), 0o600)

    def test_default_location_unchanged_without_config_env(self):
        with tempfile.TemporaryDirectory() as home:
            result = _run_logger(home, "towit_config.get_error_logger().error('boom')",
                                 config_path=None, umask=0o022)
            self.assertEqual(result.returncode, 0, result.stderr)
            towit_dir = os.path.join(home, '.towit')
            log = os.path.join(towit_dir, 'errors.log')
            with open(log) as fh:
                self.assertIn('boom', fh.read())
            self.assertEqual(_mode(towit_dir), 0o700)
            self.assertEqual(_mode(log), 0o600)

    def test_broken_config_does_not_stop_logging(self):
        with tempfile.TemporaryDirectory() as home:
            cfgdir = os.path.join(home, 'cfgdir')
            os.makedirs(cfgdir, mode=0o700)
            cfg = os.path.join(cfgdir, 'config.toml')
            with open(cfg, 'w') as fh:
                fh.write('[[[ not toml')
            result = _run_logger(home, "towit_config.get_error_logger().error('boom')", cfg)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = os.path.join(cfgdir, 'errors.log')
            self.assertTrue(os.path.exists(log), 'errors.log missing in config dir')
            with open(log) as fh:
                self.assertIn('boom', fh.read())
            self.assertFalse(os.path.exists(os.path.join(home, '.towit')))


class TestErrorLogPermissions(unittest.TestCase):
    """Log files live in the config file's directory (<home>/cfgdir here)."""

    def _cfgdir(self, home):
        return os.path.join(home, 'cfgdir')

    def _run(self, home, code):
        result = _run_logger(home, code, os.path.join(self._cfgdir(home), 'config.toml'), umask=0o022)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _mode(self, home, name='errors.log'):
        return _mode(os.path.join(self._cfgdir(home), name))

    def test_new_error_log_is_owner_only(self):
        with tempfile.TemporaryDirectory() as home:
            self._run(home, "towit_config.get_error_logger().error('boom')")
            self.assertEqual(self._mode(home), 0o600)

    def test_existing_loose_log_is_tightened(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(self._cfgdir(home), mode=0o700)
            for name in ('errors.log', 'errors.log.1'):
                path = os.path.join(self._cfgdir(home), name)
                with open(path, 'w') as fh:
                    fh.write('old\n')
                os.chmod(path, 0o644)
            self._run(home, "towit_config.get_error_logger()")
            self.assertEqual(self._mode(home), 0o600)
            self.assertEqual(self._mode(home, 'errors.log.1'), 0o600)

    def test_rotated_logs_stay_owner_only(self):
        with tempfile.TemporaryDirectory() as home:
            self._run(home, "lg = towit_config.get_error_logger()\n"
                            "for _ in range(5): lg.error('x' * 60000)")
            self.assertTrue(os.path.exists(os.path.join(self._cfgdir(home), 'errors.log.1')))
            for name in ('errors.log', 'errors.log.1'):
                self.assertEqual(self._mode(home, name), 0o600, name)


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
            warning = mock_err.getvalue()
            self.assertIn('Warning', warning)
            self.assertIn('max_keywords', warning)
        self.assertEqual(result, 30)

    def test_bool_for_int_field_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[indexing]\nmin_keywords = true\n')
        cfg = Config(path=path)
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            result = cfg.indexing_min_keywords
            self.assertIn('Warning', mock_err.getvalue())
        self.assertEqual(result, 15)

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


class TestConfigIngest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _warnings(self, cfg, attr):
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            result = getattr(cfg, attr)
        return result, mock_err.getvalue()

    def test_defaults(self):
        cfg = Config(path='/nonexistent/config.toml')
        self.assertIs(cfg.ingest_redact, True)
        self.assertEqual(cfg.ingest_extra_patterns, [])
        self.assertIs(cfg.ingest_include_subagents, False)
        self.assertEqual(cfg.ingest_folders, [])
        self.assertIs(cfg.indexing_enabled, True)

    def test_values_read_from_config(self):
        path = write_config(self.tmpdir, (
            '[ingest]\n'
            'redact = false\n'
            'extra_patterns = ["foo[0-9]+", "bar"]\n'
            'include_subagents = true\n'
            'folders = ["/a", "/b"]\n'
            '[indexing]\nenabled = false\n'
        ))
        cfg = Config(path=path)
        self.assertIs(cfg.ingest_redact, False)
        self.assertEqual(cfg.ingest_extra_patterns, ['foo[0-9]+', 'bar'])
        self.assertIs(cfg.ingest_include_subagents, True)
        self.assertEqual(cfg.ingest_folders, ['/a', '/b'])
        self.assertIs(cfg.indexing_enabled, False)

    def test_redact_wrong_type_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[ingest]\nredact = "yes"\n')
        result, err = self._warnings(Config(path=path), 'ingest_redact')
        self.assertIs(result, True)
        self.assertIn('Warning', err)

    def test_indexing_enabled_wrong_type_warns_and_uses_default(self):
        path = write_config(self.tmpdir, '[indexing]\nenabled = 1\n')
        result, err = self._warnings(Config(path=path), 'indexing_enabled')
        self.assertIs(result, True)
        self.assertIn('Warning', err)

    def test_bool_still_rejected_where_int_expected(self):
        path = write_config(self.tmpdir, '[indexing]\nreindex_delta = true\n')
        result, err = self._warnings(Config(path=path), 'indexing_reindex_delta')
        self.assertEqual(result, 2)
        self.assertIn('Warning', err)

    def test_bool_still_rejected_where_str_expected(self):
        path = write_config(self.tmpdir, '[indexing]\nmodel = true\n')
        result, err = self._warnings(Config(path=path), 'indexing_model')
        self.assertEqual(result, 'haiku')
        self.assertIn('Warning', err)

    def test_unknown_ingest_key_warns(self):
        path = write_config(self.tmpdir, '[ingest]\nbogus = 1\n')
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            Config(path=path)
        self.assertIn('bogus', mock_err.getvalue())

    def test_known_ingest_keys_do_not_warn(self):
        path = write_config(self.tmpdir, '[ingest]\nredact = true\n[indexing]\nenabled = true\n')
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
            Config(path=path)
        self.assertEqual(mock_err.getvalue(), '')

    def test_folders_not_a_list_warns_and_returns_empty(self):
        path = write_config(self.tmpdir, '[ingest]\nfolders = "x"\n')
        result, err = self._warnings(Config(path=path), 'ingest_folders')
        self.assertEqual(result, [])
        self.assertIn('Warning', err)

    def test_extra_patterns_with_non_str_element_warns_and_returns_empty(self):
        path = write_config(self.tmpdir, '[ingest]\nextra_patterns = ["ok", 3]\n')
        result, err = self._warnings(Config(path=path), 'ingest_extra_patterns')
        self.assertEqual(result, [])
        self.assertIn('Warning', err)


class TestIsValidSessionId(unittest.TestCase):
    def test_valid(self):
        for sid in ('abc-1234', 'a_b-C9d8e7f6', '0123456789abcdef'):
            self.assertTrue(is_valid_session_id(sid), sid)

    def test_invalid(self):
        for sid in ('', 'short', 'bad id!!!', '../../etc/passwd', 'abc-1234\n'):
            self.assertFalse(is_valid_session_id(sid), repr(sid))


class TestSafeSubprocessEnv(unittest.TestCase):
    def test_drops_secrets_and_keeps_allowlisted(self):
        fake = {'AWS_SECRET_ACCESS_KEY': 'x', 'PATH': '/bin', 'CLAUDE_X': '1', 'LC_ALL': 'C'}
        with unittest.mock.patch.dict(os.environ, fake, clear=True):
            env = towit_config.safe_subprocess_env()
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', env)
        self.assertEqual(env['PATH'], '/bin')
        self.assertEqual(env['CLAUDE_X'], '1')
        self.assertEqual(env['LC_ALL'], 'C')

    def test_extra_is_merged(self):
        with unittest.mock.patch.dict(os.environ, {'PATH': '/bin'}, clear=True):
            env = towit_config.safe_subprocess_env({'TOWIT_INDEXING': '1'})
        self.assertEqual(env['TOWIT_INDEXING'], '1')
        self.assertEqual(env['PATH'], '/bin')


if __name__ == '__main__':
    unittest.main()
