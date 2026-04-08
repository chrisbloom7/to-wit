# Indexing Cost Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add nine `[indexing]` config settings that let users control Claude API spend: model selection, reindex exchange delta, min/max topics, min/max keywords, min/max summary sentences, and transcript character cap.

**Architecture:** Extend `towit_config.py` with an `[indexing]` section and nine typed property accessors; thread config values into `towit_index.py` (imported at module level as `_config`) so `build_transcript`, `analyze_with_claude`, and `index_conversation` all respect user settings; update the generated config template in `towit_setup.py`; document everything in `README.md` with cost estimates. Tests patch `towit_index._config` directly — no module reloading.

**Tech Stack:** Python 3.11+, `tomllib`, `subprocess`, `unittest`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `libexec/towit/towit_config.py` | Modify | Add `[indexing]` to `_KNOWN_KEYS`; add 9 property accessors with cross-field min/max validation |
| `libexec/towit/towit_index.py` | Modify | Import config as `_config`; inject settings into prompt template, model flag, delta check, transcript cap |
| `libexec/towit/towit_setup.py` | Modify | Extend `_CONFIG_TEMPLATE` with commented-out `[indexing]` section |
| `tests/helpers/towit_config_test.py` | Modify | Add tests for all 9 new `[indexing]` properties, including min > max validation |
| `tests/helpers/towit_index_test.py` | Modify | Add tests for model flag, delta short-circuit, prompt ranges, transcript cap passthrough |
| `README.md` | Modify | Add "Configuration" section with settings table and cost estimates |

---

### Task 1: Add `[indexing]` config properties

**Files:**
- Modify: `libexec/towit/towit_config.py`
- Test: `tests/helpers/towit_config_test.py`

- [ ] **Step 1: Write failing tests for the 9 new indexing properties**

Append this new test class to `tests/helpers/towit_config_test.py` (before the `if __name__ == '__main__':` line):

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
./run-tests tests/helpers/towit_config_test.py
```

Expected: FAIL — `Config` has no `indexing_model`, `indexing_reindex_delta`, etc.

- [ ] **Step 3: Implement the 9 new properties in `towit_config.py`**

**3a.** Replace the `_KNOWN_KEYS` dict:

```python
_KNOWN_KEYS = {
    'database': {'path'},
    'indexing': {
        'model', 'reindex_delta',
        'min_topics', 'max_topics',
        'min_keywords', 'max_keywords',
        'min_summary_sentences', 'max_summary_sentences',
        'transcript_max_chars',
    },
}
```

**3b.** Add a private helper for cross-field min/max validation, then add the 9 properties to the `Config` class after `db_path`:

```python
def _get_range(self, section, min_key, max_key, default_min, default_max):
    """
    Return (min_val, max_val) for a paired min/max config entry.
    If either value has the wrong type or min > max, emits a warning and
    returns the defaults for both.
    """
    raw_min = self._get(section, min_key, default_min, int)
    raw_max = self._get(section, max_key, default_max, int)
    if raw_min > raw_max:
        print(
            f"Warning: config [{section}] {min_key!r} ({raw_min}) must not exceed "
            f"{max_key!r} ({raw_max}); using defaults "
            f"({default_min}, {default_max}).",
            file=sys.stderr,
        )
        return default_min, default_max
    return raw_min, raw_max

@property
def indexing_model(self) -> str:
    """Model passed to `claude -p`. 'default' uses the user's configured default."""
    return self._get('indexing', 'model', 'haiku', str)

@property
def indexing_reindex_delta(self) -> int:
    """Exchanges (user+assistant pairs) between re-analyses of a growing session."""
    return self._get('indexing', 'reindex_delta', 2, int)

@property
def indexing_min_topics(self) -> int:
    return self._get_range('indexing', 'min_topics', 'max_topics', 1, 5)[0]

@property
def indexing_max_topics(self) -> int:
    return self._get_range('indexing', 'min_topics', 'max_topics', 1, 5)[1]

@property
def indexing_min_keywords(self) -> int:
    return self._get_range('indexing', 'min_keywords', 'max_keywords', 15, 30)[0]

@property
def indexing_max_keywords(self) -> int:
    return self._get_range('indexing', 'min_keywords', 'max_keywords', 15, 30)[1]

@property
def indexing_min_summary_sentences(self) -> int:
    return self._get_range('indexing', 'min_summary_sentences', 'max_summary_sentences', 3, 6)[0]

@property
def indexing_max_summary_sentences(self) -> int:
    return self._get_range('indexing', 'min_summary_sentences', 'max_summary_sentences', 3, 6)[1]

@property
def indexing_transcript_max_chars(self) -> int:
    """Character cap applied to the transcript before sending to Claude."""
    return self._get('indexing', 'transcript_max_chars', 8000, int)
```

> **Note:** `_get_range` is called twice for each min/max pair (once per property). That means two warning prints if both values fail the range check. Since the invalid config is a programmer mistake, this is acceptable — but if it becomes noisy, cache the result in `__init__` later.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
./run-tests tests/helpers/towit_config_test.py
```

Expected: all tests pass, including the ~28 new ones.

- [ ] **Step 5: Commit**

```bash
git add libexec/towit/towit_config.py tests/helpers/towit_config_test.py
git commit -m "feat: add [indexing] config section with 9 cost-control settings"
```

---

### Task 2: Thread config into `towit_index.py`

**Files:**
- Modify: `libexec/towit/towit_index.py`
- Test: `tests/helpers/towit_index_test.py`

- [ ] **Step 1: Write failing tests for the new index behavior**

Add `import towit_index` to the imports at the top of `tests/helpers/towit_index_test.py` (the existing import `from towit_index import ...` stays; add the module-level import alongside it so `patch('towit_index._config', ...)` resolves correctly):

```python
import towit_index
```

Then append these test classes before `if __name__ == '__main__':`:

```python
def _make_mock_cfg(**overrides):
    """Return a MagicMock config with sensible indexing defaults, allowing overrides."""
    defaults = dict(
        indexing_model='default',
        indexing_reindex_delta=2,
        indexing_min_topics=1,
        indexing_max_topics=5,
        indexing_min_keywords=15,
        indexing_max_keywords=30,
        indexing_min_summary_sentences=3,
        indexing_max_summary_sentences=6,
        indexing_transcript_max_chars=8000,
    )
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


class TestAnalyzeWithClaudeModel(unittest.TestCase):
    def _run_and_get_cmd(self, model_value):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            'skip': False, 'title': 'T', 'summary': 'S',
            'topics': ['a'], 'keywords': ['x'],
        })
        mock_cfg = _make_mock_cfg(indexing_model=model_value)
        with patch('towit_index._config', mock_cfg):
            with patch('subprocess.run', return_value=mock_result) as mock_run:
                analyze_with_claude('transcript')
        return mock_run.call_args[0][0]

    def test_haiku_model_adds_model_flag(self):
        cmd = self._run_and_get_cmd('haiku')
        self.assertIn('--model', cmd)
        self.assertEqual(cmd[cmd.index('--model') + 1], 'haiku')

    def test_default_model_omits_model_flag(self):
        cmd = self._run_and_get_cmd('default')
        self.assertNotIn('--model', cmd)

    def test_explicit_full_model_id_passes_through(self):
        cmd = self._run_and_get_cmd('claude-sonnet-4-6')
        self.assertIn('--model', cmd)
        self.assertEqual(cmd[cmd.index('--model') + 1], 'claude-sonnet-4-6')


class TestAnalyzeWithClaudePromptRanges(unittest.TestCase):
    def _prompt_for(self, **cfg_overrides):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({'skip': False, 'title': 'T', 'summary': 'S', 'topics': [], 'keywords': []})
        mock_cfg = _make_mock_cfg(**cfg_overrides)
        with patch('towit_index._config', mock_cfg):
            with patch('subprocess.run', return_value=mock_result) as mock_run:
                analyze_with_claude('transcript')
        return mock_run.call_args[0][0][2]  # the prompt string

    def test_prompt_uses_min_and_max_topics(self):
        prompt = self._prompt_for(indexing_min_topics=2, indexing_max_topics=4)
        self.assertIn('2-4', prompt)

    def test_prompt_uses_min_and_max_keywords(self):
        prompt = self._prompt_for(indexing_min_keywords=5, indexing_max_keywords=10)
        self.assertIn('5-10', prompt)

    def test_prompt_uses_min_and_max_summary_sentences(self):
        prompt = self._prompt_for(indexing_min_summary_sentences=2, indexing_max_summary_sentences=4)
        self.assertIn('2-4', prompt)

    def test_prompt_defaults_produce_original_ranges(self):
        prompt = self._prompt_for()
        self.assertIn('1-5', prompt)    # topics
        self.assertIn('15-30', prompt)  # keywords
        self.assertIn('3-6', prompt)    # sentences


class TestIndexConversationReindexDelta(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_conv(self, session_id, messages):
        path = os.path.join(self.tmpdir, f'{session_id}.jsonl')
        with open(path, 'w') as f:
            for i, msg in enumerate(messages):
                line = {
                    'type': msg['role'],
                    'message': {'role': msg['role'], 'content': msg['content']},
                    'sessionId': session_id,
                    'cwd': '/Users/test',
                    'timestamp': f'2026-01-15T10:{i:02d}:00Z',
                }
                f.write(json.dumps(line) + '\n')
        return path

    def _seed_db(self, session_id, message_count):
        self.db.upsert_conversation({
            'id': session_id,
            'folder': self.tmpdir,
            'cwd': '/Users/test',
            'started_at': '2026-01-15T10:00:00Z',
            'last_active': '2026-01-15T10:00:00Z',
            'title': 'Old',
            'summary': 'Old summary.',
            'topics': ['test'],
            'keywords': ['test'],
            'message_count': message_count,
        })

    def test_growth_below_delta_skips_claude(self):
        # stored=4 messages, current=6 messages (1 new exchange = 2 messages)
        # delta=2 exchanges = 4 messages required; growth of 2 < 4 → skip
        self._seed_db('delta-001', 4)
        six_msgs = MINIMAL_MESSAGES + [
            {'role': 'user',      'content': 'One more question about WAL mode checkpointing.'},
            {'role': 'assistant', 'content': 'Checkpointing copies WAL records back to the main db file.'},
        ]
        path = self._write_conv('delta-001', six_msgs)
        mock_cfg = _make_mock_cfg(indexing_reindex_delta=2)  # 2 exchanges = 4 messages
        with patch('towit_index._config', mock_cfg):
            with patch('subprocess.run') as mock_run:
                result = index_conversation(path, self.db)
        self.assertEqual(result, 'already_indexed')
        mock_run.assert_not_called()

    def test_growth_at_delta_triggers_reindex(self):
        # stored=2 messages, current=6 messages, growth=4 = 2 exchanges = delta → reindex
        self._seed_db('delta-002', 2)
        path = self._write_conv('delta-002', MINIMAL_MESSAGES)  # 4 messages
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({'skip': False, 'title': 'T', 'summary': 'S', 'topics': [], 'keywords': []})
        mock_cfg = _make_mock_cfg(indexing_reindex_delta=2)  # 2 exchanges = 4 messages
        with patch('towit_index._config', mock_cfg):
            with patch('subprocess.run', return_value=mock_result) as mock_run:
                result = index_conversation(path, self.db)
        self.assertEqual(result, 'indexed')
        mock_run.assert_called_once()

    def test_zero_growth_always_skips_regardless_of_delta(self):
        self._seed_db('delta-003', len(MINIMAL_MESSAGES))
        path = self._write_conv('delta-003', MINIMAL_MESSAGES)
        mock_cfg = _make_mock_cfg(indexing_reindex_delta=0)
        with patch('towit_index._config', mock_cfg):
            with patch('subprocess.run') as mock_run:
                result = index_conversation(path, self.db)
        self.assertEqual(result, 'already_indexed')
        mock_run.assert_not_called()

    def test_delta_1_reindexes_after_single_exchange(self):
        # stored=4, current=6, growth=2 = 1 exchange >= delta=1 → reindex
        self._seed_db('delta-004', 4)
        six_msgs = MINIMAL_MESSAGES + [
            {'role': 'user',      'content': 'One more question about WAL mode checkpointing.'},
            {'role': 'assistant', 'content': 'Checkpointing copies WAL records back to the main db file.'},
        ]
        path = self._write_conv('delta-004', six_msgs)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({'skip': False, 'title': 'T', 'summary': 'S', 'topics': [], 'keywords': []})
        mock_cfg = _make_mock_cfg(indexing_reindex_delta=1)
        with patch('towit_index._config', mock_cfg):
            with patch('subprocess.run', return_value=mock_result) as mock_run:
                result = index_conversation(path, self.db)
        self.assertEqual(result, 'indexed')
        mock_run.assert_called_once()


class TestIndexConversationTranscriptCap(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.db = Database(self.db_path)
        self.db.create_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_index_conversation_passes_transcript_max_chars_to_build_transcript(self):
        path = os.path.join(self.tmpdir, 'cap-session-001.jsonl')
        with open(path, 'w') as f:
            for i, msg in enumerate(MINIMAL_MESSAGES):
                f.write(json.dumps({
                    'type': msg['role'],
                    'message': {'role': msg['role'], 'content': msg['content']},
                    'sessionId': 'cap-session-001',
                    'cwd': '/Users/test',
                    'timestamp': f'2026-01-15T10:{i:02d}:00Z',
                }) + '\n')

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({'skip': False, 'title': 'T', 'summary': 'S', 'topics': [], 'keywords': []})
        mock_cfg = _make_mock_cfg(indexing_transcript_max_chars=1234)

        with patch('towit_index._config', mock_cfg):
            with patch('towit_index.build_transcript', wraps=towit_index.build_transcript) as mock_bt:
                with patch('subprocess.run', return_value=mock_result):
                    index_conversation(path, self.db)

        mock_bt.assert_called_once()
        call_kwargs = mock_bt.call_args
        # build_transcript is called as build_transcript(messages, max_chars=N)
        actual_max_chars = call_kwargs[1].get('max_chars') if call_kwargs[1] else call_kwargs[0][1]
        self.assertEqual(actual_max_chars, 1234)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
./run-tests tests/helpers/towit_index_test.py
```

Expected: FAIL — `analyze_with_claude` and `index_conversation` don't read from `_config` yet.

- [ ] **Step 3: Add the config import to `towit_index.py`**

After the existing `from towit_db import Database` line, add:

```python
from towit_config import config as _config
```

- [ ] **Step 4: Update `_ANALYSIS_PROMPT_TEMPLATE` to use range variables**

Replace the hardcoded counts in the three bullet lines:

```
- "summary": A 3-{max_sentences} sentence summary of what was discussed and accomplished. For wide-ranging \
conversations, capture the key threads rather than just the final outcome. Include notable \
context, decisions, and domain-specific details.
- "keywords": A list of {min_keywords}-{max_keywords} specific terms drawn from the conversation content: identifiers, \
class/method/variable names, error messages, domain terminology, proper nouns, formula \
components, filenames, plan names, and other specific details worth finding later. Prefer \
specific over generic. Use lowercase with hyphens for multi-word terms.{existing_keywords_instruction}
- "topics": A list of {min_topics}-{max_topics} short topic tags (e.g. ["python", "refactoring", "git"]){existing_topics_instruction}
```

(The `{min_sentences}` variable is included in the `3-{max_sentences}` pattern — replace the full line so it becomes `{min_sentences}-{max_sentences}`.)

Full replacement for those three bullet lines:

```
- "summary": A {min_sentences}-{max_sentences} sentence summary of what was discussed and accomplished. For wide-ranging \
conversations, capture the key threads rather than just the final outcome. Include notable \
context, decisions, and domain-specific details.
- "keywords": A list of {min_keywords}-{max_keywords} specific terms drawn from the conversation content: identifiers, \
class/method/variable names, error messages, domain terminology, proper nouns, formula \
components, filenames, plan names, and other specific details worth finding later. Prefer \
specific over generic. Use lowercase with hyphens for multi-word terms.{existing_keywords_instruction}
- "topics": A list of {min_topics}-{max_topics} short topic tags (e.g. ["python", "refactoring", "git"]){existing_topics_instruction}
```

- [ ] **Step 5: Update `analyze_with_claude` to read config and build the model flag**

Replace the body of `analyze_with_claude` with:

```python
def analyze_with_claude(transcript: str, existing_topics: list = None,
                        existing_keywords: list = None) -> dict:
    """
    Call Claude to produce a title, summary, keywords, and topics for a conversation.
    Returns a dict with keys: title, summary, keywords, topics, skip.
    On any error returns {'skip': True}.
    """
    topics_instruction = ''
    if existing_topics:
        topics_instruction = _EXISTING_TOPICS_INSTRUCTION.format(
            topics=json.dumps(existing_topics)
        )
    keywords_instruction = ''
    if existing_keywords:
        keywords_instruction = _EXISTING_KEYWORDS_INSTRUCTION.format(
            keywords=json.dumps(existing_keywords)
        )
    prompt = _ANALYSIS_PROMPT_TEMPLATE.format(
        transcript=transcript,
        existing_topics_instruction=topics_instruction,
        existing_keywords_instruction=keywords_instruction,
        min_sentences=_config.indexing_min_summary_sentences,
        max_sentences=_config.indexing_max_summary_sentences,
        min_keywords=_config.indexing_min_keywords,
        max_keywords=_config.indexing_max_keywords,
        min_topics=_config.indexing_min_topics,
        max_topics=_config.indexing_max_topics,
    )

    _PASS_THROUGH_PREFIXES = (
        'HOME', 'PATH', 'USER', 'TMPDIR', 'TERM', 'LANG', 'LC_',
        'CLAUDE_', 'ANTHROPIC_',
    )
    safe_env = {
        k: v for k, v in os.environ.items()
        if any(k.startswith(p) for p in _PASS_THROUGH_PREFIXES)
    }
    safe_env['TOWIT_INDEXING'] = '1'

    cmd = ['claude', '-p', prompt, '--output-format', 'text']
    model = _config.indexing_model
    if model and model != 'default':
        cmd += ['--model', model]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=60,
            env=safe_env,
        )
    except subprocess.TimeoutExpired:
        return {'skip': True}

    if result.returncode != 0:
        return {'skip': True}

    output = result.stdout.strip()

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        match = re.search(r'\{.*?\}', output, re.DOTALL)
        if not match:
            return {'skip': True}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {'skip': True}

    if not isinstance(data, dict):
        return {'skip': True}

    return data
```

- [ ] **Step 6: Update `index_conversation` — delta check and transcript cap**

Replace the staleness-detection block (the `if existing is not None:` section that currently checks `stored_count == current_count`):

```python
    if existing is not None:
        stored_count = existing.get('message_count')
        if stored_count is not None:
            growth = current_count - stored_count
            # Convert exchange delta to message delta (each exchange = 2 messages).
            # Floor at 2 so zero growth never triggers a re-analysis.
            delta_messages = max(2, _config.indexing_reindex_delta * 2)
            if growth < delta_messages:
                timestamps = [m['timestamp'] for m in messages if m.get('timestamp')]
                last_active = timestamps[-1] if timestamps else None
                if last_active:
                    db.touch_last_active(session_id, last_active)
                return 'already_indexed'
        # stored_count is None (pre-migration record) or growth meets delta — fall through
```

Replace the `build_transcript` call:

```python
    transcript = build_transcript(messages, max_chars=_config.indexing_transcript_max_chars)
```

- [ ] **Step 7: Run tests to confirm they pass**

```bash
./run-tests tests/helpers/towit_index_test.py
```

Expected: all tests pass including the ~15 new ones.

- [ ] **Step 8: Run the full test suite**

```bash
./run-tests
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add libexec/towit/towit_index.py tests/helpers/towit_index_test.py
git commit -m "feat: thread indexing config into analyze_with_claude and index_conversation"
```

---

### Task 3: Update the generated config template

**Files:**
- Modify: `libexec/towit/towit_setup.py`

No new tests needed — the template is a string constant. The existing BATS integration tests for `setup --config` will catch breakage.

- [ ] **Step 1: Extend `_CONFIG_TEMPLATE` with the `[indexing]` section**

Replace the `_CONFIG_TEMPLATE` string:

```python
_CONFIG_TEMPLATE = """\
# To Wit configuration
# https://github.com/chrisbloom7/to-wit
#
# Generated by: towit setup --config
# Edit this file to customize To Wit's behavior.

[database]
# Database file path. Default: ~/.towit/catalog.db
# path = "~/.towit/catalog.db"

[indexing]
# Model used for analysis. Use "default" to inherit your Claude Code default model,
# or any alias ("sonnet", "opus") or full model ID ("claude-sonnet-4-6").
# Haiku is fast and inexpensive; Sonnet/Opus are more capable but cost significantly more.
# Default: "haiku"
# model = "haiku"

# How many exchanges (user + assistant pairs) must occur before a resumed session
# is re-analyzed. The stop hook fires after every response; this prevents unnecessary
# API calls mid-conversation. Set to 1 to re-analyze after every exchange.
# Default: 2
# reindex_delta = 2

# Range of topic tags Claude should assign per conversation (min must be <= max).
# Default: 1–5
# min_topics = 1
# max_topics = 5

# Range of keywords Claude should extract per conversation (min must be <= max).
# Default: 15–30
# min_keywords = 15
# max_keywords = 30

# Range of sentences for the generated summary (min must be <= max).
# Default: 3–6
# min_summary_sentences = 3
# max_summary_sentences = 6

# Maximum characters of transcript text sent to Claude for analysis.
# Longer transcripts cost more; the excerpt always keeps the first 30% and last 70%.
# Default: 8000
# transcript_max_chars = 8000
"""
```

- [ ] **Step 2: Run the full test suite**

```bash
./run-tests
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add libexec/towit/towit_setup.py
git commit -m "docs: add [indexing] section to generated config template"
```

---

### Task 4: Document in README with cost estimates

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Configuration" section to `README.md`**

Insert the following after the `## How it works` section (before `## Uninstalling`):

````markdown
## Configuration

To Wit is configured via `~/.towit/config.toml`. Generate a starter file with all settings commented out:

```bash
towit setup --config
```

### `[indexing]` settings

These settings control how To Wit calls the Claude API during indexing and directly affect API spend.

| Key | Default | Description |
|---|---|---|
| `model` | `"haiku"` | Model passed to `claude -p`. Use `"default"` to inherit your Claude Code default, or any alias (`"sonnet"`, `"opus"`) or full model ID (`"claude-sonnet-4-6"`). |
| `reindex_delta` | `2` | Exchanges (user+assistant pairs) that must occur before a resumed session is re-analyzed. The stop hook fires after every response; this prevents re-indexing on every turn. Set to `1` for original behavior. |
| `min_topics` | `1` | Minimum topic tags Claude should assign per conversation. |
| `max_topics` | `5` | Maximum topic tags Claude should assign per conversation. |
| `min_keywords` | `15` | Minimum keywords Claude should extract per conversation. |
| `max_keywords` | `30` | Maximum keywords Claude should extract per conversation. |
| `min_summary_sentences` | `3` | Minimum sentences in the generated summary. |
| `max_summary_sentences` | `6` | Maximum sentences in the generated summary. |
| `transcript_max_chars` | `8000` | Character cap on the transcript excerpt sent to Claude. The excerpt always keeps the first 30% and last 70% of the conversation. |

**Example:**

```toml
[indexing]
model = "haiku"
reindex_delta = 2
min_topics = 1
max_topics = 5
min_keywords = 10
max_keywords = 20
min_summary_sentences = 2
max_summary_sentences = 4
transcript_max_chars = 8000
```

### Cost estimates

Each indexing call sends roughly **2,000–4,000 input tokens** depending on transcript length and content (code-heavy conversations tokenize more densely than prose) plus prompt overhead of ~200 tokens. Output is roughly **300 tokens** (title + summary + keywords + topics JSON). The estimates below use a mid-range of ~2,200 input / 300 output tokens.

The stop hook fires after every Claude response. With `reindex_delta = 2` (default), a 10-exchange conversation triggers ~5 indexing calls instead of 10.

**Estimated cost — 100 conversations, 10 exchanges each:**

| Model | `reindex_delta = 1` (1,000 calls) | `reindex_delta = 2` (~500 calls) |
|---|---|---|
| Haiku 4.5 | ~$2.96 | ~$1.48 |
| Sonnet 4.6 | ~$11.10 | ~$5.55 |
| Opus 4.6 | ~$55.50 | ~$27.75 |

Pricing based on Anthropic's published rates as of April 2026: Haiku 4.5 at $0.80/$4.00 per million input/output tokens; Sonnet 4.6 at $3.00/$15.00; Opus 4.6 at $15.00/$75.00. Actual costs will vary.
````

- [ ] **Step 2: Verify the section landed correctly**

```bash
grep -n "Configuration\|reindex_delta\|Cost estimates\|Actual costs" README.md
```

Expected output includes lines for `## Configuration`, `reindex_delta`, `### Cost estimates`, and `Actual costs will vary.`

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add Configuration section to README with indexing settings and cost estimates"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| `indexing_model` with `"haiku"` default; `"default"` omits `--model` flag | Task 1 + Task 2 |
| `reindex_delta` in exchanges, default 2 | Task 1 + Task 2 |
| `min_topics`/`max_topics`, defaults 1/5 | Task 1 + Task 2 |
| `min_keywords`/`max_keywords`, defaults 15/30 | Task 1 + Task 2 |
| `min_summary_sentences`/`max_summary_sentences`, defaults 3/6 | Task 1 + Task 2 |
| `transcript_max_chars` default 8000 | Task 1 + Task 2 |
| Config template updated | Task 3 |
| README docs + cost estimates by model | Task 4 |
| min > max validation with warning + defaults | Task 1 |

**No gaps found.**

**Placeholder scan:** All code blocks are complete. No TBD or "similar to above" references.

**Type consistency:** All `_config.indexing_*` names defined in Task 1 match exactly how they're accessed in Task 2. `_make_mock_cfg()` helper sets every property used in tests. `build_transcript(messages, max_chars=N)` — keyword arg, matches existing signature.

**Known limitation documented:** `_get_range` is called twice per min/max pair (once per property), so a bad range emits two warnings instead of one. Acceptable for now; a caching fix can be added later if it becomes noisy.
