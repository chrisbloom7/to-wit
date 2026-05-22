# `towit doctor` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `towit doctor` subcommand that verifies setup correctness and prints plain-text results with remediation hints — no automatic fixes, no JSON/CSV output, only `--help` accepted.

**Architecture:** A single new module `towit_doctor.py` runs a fixed sequence of checks. Each check returns a `CheckResult` dataclass (status, label, remediation). `main()` prints results, prints a summary line, and exits 0 if no failures, 1 if any failed. The dispatcher in `bin/towit` gets one new `doctor` case.

**Tech Stack:** Python 3.11+ stdlib only (`os`, `sqlite3`, `shutil`, `subprocess`, `argparse`, `dataclasses`, `tomllib`); BATS 1.5+ for CLI integration tests; `unittest` for unit tests.

---

## Files

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `libexec/towit/towit_doctor.py` | All check logic + `main()` |
| Modify | `bin/towit` | Add `doctor` case to dispatcher + usage comment |
| Create | `tests/helpers/towit_doctor_test.py` | Unit tests for check functions |
| Modify | `tests/bin/towit.bats` | CLI integration tests for `doctor` subcommand |

---

## Checks (in order)

| # | Label | Status if bad |
|---|-------|---------------|
| 1 | Python ≥ 3.11 | FAIL |
| 2 | `claude` CLI on PATH | FAIL |
| 3 | Config file exists | WARN (optional; defaults apply) |
| 4 | Config file is valid TOML | FAIL (only if file exists) |
| 5 | No unknown config keys/sections | WARN (only if file is valid) |
| 6 | `TOWIT_DB_PATH` env var set (deprecated) | WARN |
| 7 | Database file exists | FAIL |
| 8 | Database file permissions are 0600 | WARN |
| 9 | Database directory permissions are 0700 | WARN |
| 10 | Database is readable and writable | FAIL |
| 11 | Required tables present | FAIL |
| 12 | Schema is current (message_count + keywords tables) | WARN |
| 13 | `~/.claude/settings.json` exists | WARN |
| 14 | Stop hook entry present in settings.json | FAIL |
| 15 | Hook script path on disk exists | FAIL (only if entry found) |

**Exit codes:** 0 = all PASS/WARN; 1 = any FAIL.

**Output format:**

```
[PASS] Python 3.13.2 (≥3.11 required for TOML support)
[WARN] Config file not found at /Users/you/.towit/config.toml
       → Run 'towit setup --config' to generate a starter config. Defaults apply until then.
[FAIL] Database not found at /Users/you/.towit/catalog.db
       → Run 'towit setup' to initialize the database.
...
1 warning(s), 1 failure(s).
```

When all checks pass: `All checks passed.`

---

## Task 1: `CheckResult` dataclass and output formatter

**Files:**
- Create: `libexec/towit/towit_doctor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/helpers/towit_doctor_test.py
import unittest
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit')))
from towit_doctor import CheckResult, format_result, summarise

class TestCheckResult(unittest.TestCase):
    def test_pass_has_no_remediation_line(self):
        r = CheckResult('PASS', 'Something works')
        lines = format_result(r)
        self.assertEqual(lines, ['[PASS] Something works'])

    def test_warn_includes_remediation_indented(self):
        r = CheckResult('WARN', 'Something is off', remediation='Fix it with foo')
        lines = format_result(r)
        self.assertEqual(lines, ['[WARN] Something is off', "       \u2192 Fix it with foo"])

    def test_fail_includes_remediation_indented(self):
        r = CheckResult('FAIL', 'Something is broken', remediation='Run bar')
        lines = format_result(r)
        self.assertEqual(lines, ['[FAIL] Something is broken', "       \u2192 Run bar"])

    def test_summarise_all_pass(self):
        results = [CheckResult('PASS', 'a'), CheckResult('PASS', 'b')]
        msg, code = summarise(results)
        self.assertEqual(msg, 'All checks passed.')
        self.assertEqual(code, 0)

    def test_summarise_with_warn_only(self):
        results = [CheckResult('PASS', 'a'), CheckResult('WARN', 'b')]
        msg, code = summarise(results)
        self.assertIn('1 warning', msg)
        self.assertIn('0 failure', msg)
        self.assertEqual(code, 0)

    def test_summarise_with_fail(self):
        results = [CheckResult('WARN', 'a'), CheckResult('FAIL', 'b')]
        msg, code = summarise(results)
        self.assertIn('1 warning', msg)
        self.assertIn('1 failure', msg)
        self.assertEqual(code, 1)

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `ModuleNotFoundError: No module named 'towit_doctor'`

- [ ] **Step 3: Create `towit_doctor.py` with `CheckResult`, `format_result`, and `summarise`**

```python
#!/usr/bin/env python3
"""
towit_doctor — Verify that To Wit's setup is complete and correct.

Prints a plain-text health report and exits 0 if all checks pass (or only
warnings), 1 if any check fails.  Never performs automatic remediation.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    status: str          # 'PASS', 'WARN', or 'FAIL'
    label: str           # one-line description shown after the status tag
    remediation: str = ''  # shown indented below for WARN/FAIL


def format_result(result: CheckResult) -> list:
    """Return a list of output lines for one CheckResult."""
    lines = [f'[{result.status}] {result.label}']
    if result.remediation and result.status in ('WARN', 'FAIL'):
        lines.append(f'       \u2192 {result.remediation}')
    return lines


def summarise(results: list) -> tuple:
    """Return (summary_line, exit_code) for a list of CheckResults."""
    warns = sum(1 for r in results if r.status == 'WARN')
    fails = sum(1 for r in results if r.status == 'FAIL')
    if warns == 0 and fails == 0:
        return 'All checks passed.', 0
    parts = [f'{warns} warning(s)', f'{fails} failure(s)']
    return ', '.join(parts) + '.', (1 if fails else 0)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `OK (6 tests)`

- [ ] **Step 5: Commit**

```bash
git add libexec/towit/towit_doctor.py tests/helpers/towit_doctor_test.py
git commit -m "feat: add towit_doctor module scaffold with CheckResult and formatter"
```

---

## Task 2: Python and `claude` CLI checks

**Files:**
- Modify: `libexec/towit/towit_doctor.py`
- Modify: `tests/helpers/towit_doctor_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/helpers/towit_doctor_test.py`:

```python
import shutil
from unittest.mock import patch
from towit_doctor import check_python_version, check_claude_cli

class TestChecks(unittest.TestCase):
    def test_python_version_pass_on_current_interpreter(self):
        # This test runs on Python 3.11+, so it must pass
        result = check_python_version()
        self.assertEqual(result.status, 'PASS')
        self.assertIn('3.', result.label)

    def test_python_version_fail_below_311(self):
        with patch('sys.version_info', (3, 10, 0)):
            result = check_python_version()
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('3.10', result.label)
        self.assertIn('towit setup', result.remediation)

    def test_claude_cli_pass_when_found(self):
        with patch('shutil.which', return_value='/usr/local/bin/claude'):
            result = check_claude_cli()
        self.assertEqual(result.status, 'PASS')
        self.assertIn('/usr/local/bin/claude', result.label)

    def test_claude_cli_fail_when_not_found(self):
        with patch('shutil.which', return_value=None):
            result = check_claude_cli()
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('not found', result.label)
        self.assertTrue(result.remediation)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `AttributeError` or `ImportError` referencing `check_python_version`

- [ ] **Step 3: Implement the two check functions**

Add to `towit_doctor.py` (after the `summarise` function):

```python
def check_python_version() -> CheckResult:
    v = sys.version_info
    label = f'Python {v.major}.{v.minor}.{v.micro}'
    if (v.major, v.minor) < (3, 11):
        return CheckResult(
            'FAIL',
            f'{label} (3.11+ required for TOML config support)',
            remediation='Install Python 3.11 or later and ensure it is the active python3.',
        )
    return CheckResult('PASS', f'{label} (≥3.11 required for TOML support)')


def check_claude_cli() -> CheckResult:
    import shutil
    path = shutil.which('claude')
    if path is None:
        return CheckResult(
            'FAIL',
            'claude CLI not found on PATH',
            remediation='Install Claude Code and ensure it is available as \'claude\' on your PATH.',
        )
    return CheckResult('PASS', f'claude CLI found at {path}')
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `OK (10 tests)`

- [ ] **Step 5: Commit**

```bash
git add libexec/towit/towit_doctor.py tests/helpers/towit_doctor_test.py
git commit -m "feat: add python version and claude CLI doctor checks"
```

---

## Task 3: Configuration checks

**Files:**
- Modify: `libexec/towit/towit_doctor.py`
- Modify: `tests/helpers/towit_doctor_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/helpers/towit_doctor_test.py`:

```python
import tempfile, shutil

class TestConfigChecks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _config_path(self, content=None):
        p = os.path.join(self.tmpdir, 'config.toml')
        if content is not None:
            with open(p, 'w') as f:
                f.write(content)
        return p

    def test_config_missing_is_warn(self):
        from towit_doctor import check_config_file
        result = check_config_file(os.path.join(self.tmpdir, 'nonexistent.toml'))
        self.assertEqual(result.status, 'WARN')
        self.assertIn('not found', result.label)
        self.assertIn('towit setup --config', result.remediation)

    def test_config_present_is_pass(self):
        from towit_doctor import check_config_file
        p = self._config_path('[database]\npath = "/tmp/x.db"\n')
        result = check_config_file(p)
        self.assertEqual(result.status, 'PASS')
        self.assertIn(p, result.label)

    def test_config_invalid_toml_is_fail(self):
        from towit_doctor import check_config_file
        p = self._config_path('not valid toml ][')
        result = check_config_file(p)
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('invalid TOML', result.label)
        self.assertTrue(result.remediation)

    def test_unknown_keys_is_warn(self):
        from towit_doctor import check_config_unknown_keys
        p = self._config_path('[unknownsection]\nfoo = 1\n')
        result = check_config_unknown_keys(p)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('unknown', result.label.lower())

    def test_known_keys_only_is_pass(self):
        from towit_doctor import check_config_unknown_keys
        p = self._config_path('[database]\npath = "/tmp/x.db"\n')
        result = check_config_unknown_keys(p)
        self.assertEqual(result.status, 'PASS')

    def test_deprecated_env_var_is_warn(self):
        from towit_doctor import check_deprecated_env
        with patch.dict(os.environ, {'TOWIT_DB_PATH': '/tmp/x.db'}):
            result = check_deprecated_env()
        self.assertEqual(result.status, 'WARN')
        self.assertIn('TOWIT_DB_PATH', result.label)

    def test_no_deprecated_env_var_is_pass(self):
        from towit_doctor import check_deprecated_env
        env = {k: v for k, v in os.environ.items() if k != 'TOWIT_DB_PATH'}
        with patch.dict(os.environ, env, clear=True):
            result = check_deprecated_env()
        self.assertEqual(result.status, 'PASS')
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `ImportError` referencing `check_config_file`

- [ ] **Step 3: Implement config check functions**

Add to `towit_doctor.py`:

```python
# ---------------------------------------------------------------------------
# Config checks
# ---------------------------------------------------------------------------

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


def check_config_file(config_path: str) -> CheckResult:
    """Check whether the config file exists and contains valid TOML."""
    if not os.path.isfile(config_path):
        return CheckResult(
            'WARN',
            f'Config file not found at {config_path}',
            remediation="Run 'towit setup --config' to generate a starter config. Defaults apply until then.",
        )
    import tomllib
    try:
        with open(config_path, 'rb') as f:
            tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        return CheckResult(
            'FAIL',
            f'Config file has invalid TOML: {config_path}',
            remediation=f'Fix the syntax error: {exc}',
        )
    return CheckResult('PASS', f'Config file found and valid: {config_path}')


def check_config_unknown_keys(config_path: str) -> CheckResult:
    """Check for unknown sections/keys in a valid config file."""
    if not os.path.isfile(config_path):
        return CheckResult('PASS', 'Config file absent — no keys to validate')
    import tomllib
    try:
        with open(config_path, 'rb') as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        return CheckResult('PASS', 'Config file invalid TOML — covered by previous check')

    unknown = []
    for section, value in data.items():
        if section not in _KNOWN_KEYS:
            unknown.append(f'[{section}]')
            continue
        if isinstance(value, dict):
            for key in value:
                if key not in _KNOWN_KEYS[section]:
                    unknown.append(f'[{section}] {key!r}')

    if unknown:
        return CheckResult(
            'WARN',
            f'Config file has unknown keys: {", ".join(unknown)}',
            remediation='Remove or correct unrecognised keys; they are ignored by To Wit.',
        )
    return CheckResult('PASS', 'Config file has no unknown keys')


def check_deprecated_env() -> CheckResult:
    """Warn if TOWIT_DB_PATH is set (deprecated in favour of config file)."""
    if os.environ.get('TOWIT_DB_PATH'):
        return CheckResult(
            'WARN',
            'TOWIT_DB_PATH environment variable is set (deprecated)',
            remediation="Move the path to [database] path in your config file and unset TOWIT_DB_PATH.",
        )
    return CheckResult('PASS', 'TOWIT_DB_PATH not set (not deprecated)')
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `OK (17 tests)`

- [ ] **Step 5: Commit**

```bash
git add libexec/towit/towit_doctor.py tests/helpers/towit_doctor_test.py
git commit -m "feat: add config file and deprecated env var doctor checks"
```

---

## Task 4: Database checks

**Files:**
- Modify: `libexec/towit/towit_doctor.py`
- Modify: `tests/helpers/towit_doctor_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/helpers/towit_doctor_test.py`:

```python
import sqlite3, stat

class TestDatabaseChecks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_db(self, tables=True):
        conn = sqlite3.connect(self.db_path)
        if tables:
            conn.executescript("""
                CREATE TABLE conversations (id TEXT PRIMARY KEY, folder TEXT NOT NULL,
                    cwd TEXT, started_at TEXT, last_active TEXT, title TEXT, summary TEXT,
                    message_count INTEGER, indexed_at TEXT NOT NULL DEFAULT (datetime('now')));
                CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_topics (
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    PRIMARY KEY (conversation_id, topic_id));
                CREATE TABLE keywords (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL COLLATE NOCASE);
                CREATE TABLE conversation_keywords (
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
                    PRIMARY KEY (conversation_id, keyword_id));
            """)
        conn.commit()
        conn.close()

    def test_db_missing_is_fail(self):
        from towit_doctor import check_db_exists
        result = check_db_exists('/tmp/does_not_exist_towit.db')
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('not found', result.label)
        self.assertIn('towit setup', result.remediation)

    def test_db_present_is_pass(self):
        from towit_doctor import check_db_exists
        self._make_db()
        result = check_db_exists(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_permissions_correct_is_pass(self):
        from towit_doctor import check_db_permissions
        self._make_db()
        os.chmod(self.db_path, 0o600)
        result = check_db_permissions(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_permissions_too_open_is_warn(self):
        from towit_doctor import check_db_permissions
        self._make_db()
        os.chmod(self.db_path, 0o644)
        result = check_db_permissions(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('644', result.label)
        self.assertTrue(result.remediation)

    def test_db_dir_permissions_correct_is_pass(self):
        from towit_doctor import check_db_dir_permissions
        self._make_db()
        os.chmod(self.tmpdir, 0o700)
        result = check_db_dir_permissions(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_dir_permissions_too_open_is_warn(self):
        from towit_doctor import check_db_dir_permissions
        self._make_db()
        os.chmod(self.tmpdir, 0o755)
        result = check_db_dir_permissions(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertTrue(result.remediation)

    def test_db_tables_all_present_is_pass(self):
        from towit_doctor import check_db_tables
        self._make_db()
        result = check_db_tables(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_tables_missing_is_fail(self):
        from towit_doctor import check_db_tables
        self._make_db(tables=False)
        result = check_db_tables(self.db_path)
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('towit setup', result.remediation)

    def test_db_schema_current_is_pass(self):
        from towit_doctor import check_db_schema
        self._make_db()
        result = check_db_schema(self.db_path)
        self.assertEqual(result.status, 'PASS')

    def test_db_schema_missing_message_count_is_warn(self):
        from towit_doctor import check_db_schema
        # Create DB without message_count
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE conversations (id TEXT PRIMARY KEY,
            folder TEXT NOT NULL, cwd TEXT, started_at TEXT, last_active TEXT,
            title TEXT, summary TEXT, indexed_at TEXT NOT NULL DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL COLLATE NOCASE)""")
        conn.execute("""CREATE TABLE conversation_topics (
            conversation_id TEXT NOT NULL, topic_id INTEGER NOT NULL,
            PRIMARY KEY (conversation_id, topic_id))""")
        conn.commit()
        conn.close()
        result = check_db_schema(self.db_path)
        self.assertEqual(result.status, 'WARN')
        self.assertIn('towit setup', result.remediation)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `ImportError` referencing `check_db_exists`

- [ ] **Step 3: Implement database check functions**

Add to `towit_doctor.py`:

```python
# ---------------------------------------------------------------------------
# Database checks
# ---------------------------------------------------------------------------

_REQUIRED_TABLES = {
    'conversations', 'topics', 'conversation_topics',
    'keywords', 'conversation_keywords',
}


def check_db_exists(db_path: str) -> CheckResult:
    if not os.path.isfile(db_path):
        return CheckResult(
            'FAIL',
            f'Database not found at {db_path}',
            remediation="Run 'towit setup' to initialize the database.",
        )
    return CheckResult('PASS', f'Database found at {db_path}')


def check_db_permissions(db_path: str) -> CheckResult:
    import stat
    mode = os.stat(db_path).st_mode & 0o777
    if mode != 0o600:
        octal = oct(mode)[2:]
        return CheckResult(
            'WARN',
            f'Database file permissions are {octal} (expected 600)',
            remediation=f"Run 'chmod 600 {db_path}' to restrict access.",
        )
    return CheckResult('PASS', 'Database file permissions are 600')


def check_db_dir_permissions(db_path: str) -> CheckResult:
    db_dir = os.path.dirname(db_path)
    mode = os.stat(db_dir).st_mode & 0o777
    if mode != 0o700:
        octal = oct(mode)[2:]
        return CheckResult(
            'WARN',
            f'Database directory permissions are {octal} (expected 700): {db_dir}',
            remediation=f"Run 'chmod 700 {db_dir}' to restrict access.",
        )
    return CheckResult('PASS', f'Database directory permissions are 700: {db_dir}')


def check_db_tables(db_path: str) -> CheckResult:
    import sqlite3
    try:
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
    except sqlite3.Error as exc:
        return CheckResult(
            'FAIL',
            f'Could not query database: {exc}',
            remediation="Run 'towit setup' to reinitialize the database.",
        )
    present = {row[0] for row in rows}
    missing = _REQUIRED_TABLES - present
    if missing:
        return CheckResult(
            'FAIL',
            f'Missing tables: {", ".join(sorted(missing))}',
            remediation="Run 'towit setup' to create missing tables.",
        )
    return CheckResult('PASS', f'All required tables present: {", ".join(sorted(_REQUIRED_TABLES))}')


def check_db_schema(db_path: str) -> CheckResult:
    """Check that incremental migrations have been applied."""
    import sqlite3
    issues = []
    try:
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            cols = {row[1] for row in conn.execute('PRAGMA table_info(conversations)').fetchall()}
            if 'message_count' not in cols:
                issues.append('conversations.message_count column missing')
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if 'keywords' not in tables:
                issues.append('keywords table missing')
            if 'conversation_keywords' not in tables:
                issues.append('conversation_keywords table missing')
    except sqlite3.Error as exc:
        return CheckResult('WARN', f'Could not verify schema: {exc}',
                           remediation="Run 'towit setup' to apply migrations.")
    if issues:
        return CheckResult(
            'WARN',
            f'Schema needs migration: {"; ".join(issues)}',
            remediation="Run 'towit setup' to apply pending schema migrations.",
        )
    return CheckResult('PASS', 'Database schema is current')
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `OK (27 tests)`

- [ ] **Step 5: Commit**

```bash
git add libexec/towit/towit_doctor.py tests/helpers/towit_doctor_test.py
git commit -m "feat: add database existence, permissions, and schema doctor checks"
```

---

## Task 5: Stop hook checks

**Files:**
- Modify: `libexec/towit/towit_doctor.py`
- Modify: `tests/helpers/towit_doctor_test.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/helpers/towit_doctor_test.py`:

```python
import json

class TestHookChecks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.settings_path = os.path.join(self.tmpdir, 'settings.json')
        self.hook_script = os.path.join(self.tmpdir, 'towit_hook.py')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_settings(self, data):
        with open(self.settings_path, 'w') as f:
            json.dump(data, f)

    def test_settings_missing_is_warn(self):
        from towit_doctor import check_hook_settings_file
        result = check_hook_settings_file('/tmp/no_such_settings_towit.json')
        self.assertEqual(result.status, 'WARN')
        self.assertIn('not found', result.label)

    def test_settings_present_is_pass(self):
        from towit_doctor import check_hook_settings_file
        self._write_settings({})
        result = check_hook_settings_file(self.settings_path)
        self.assertEqual(result.status, 'PASS')

    def test_hook_not_installed_is_fail(self):
        from towit_doctor import check_hook_installed
        self._write_settings({'hooks': {'Stop': []}})
        result = check_hook_installed(self.settings_path)
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('towit install-hook', result.remediation)

    def test_hook_installed_is_pass(self):
        from towit_doctor import check_hook_installed
        data = {'hooks': {'Stop': [{'matcher': '', 'hooks': [
            {'type': 'command', 'command': f'python3 {self.hook_script}'}
        ]}]}}
        self._write_settings(data)
        result = check_hook_installed(self.settings_path)
        self.assertEqual(result.status, 'PASS')

    def test_hook_script_missing_from_disk_is_fail(self):
        from towit_doctor import check_hook_script_exists
        command = f'python3 /no/such/towit_hook.py'
        result = check_hook_script_exists(command)
        self.assertEqual(result.status, 'FAIL')
        self.assertIn('/no/such/towit_hook.py', result.label)

    def test_hook_script_exists_on_disk_is_pass(self):
        from towit_doctor import check_hook_script_exists
        open(self.hook_script, 'w').close()
        result = check_hook_script_exists(f'python3 {self.hook_script}')
        self.assertEqual(result.status, 'PASS')
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `ImportError` referencing `check_hook_settings_file`

- [ ] **Step 3: Implement hook check functions**

Add to `towit_doctor.py`:

```python
# ---------------------------------------------------------------------------
# Stop hook checks
# ---------------------------------------------------------------------------

_HOOK_MARKER = 'towit_hook.py'


def _find_hook_command(settings_path: str) -> str | None:
    """Return the hook command string if our hook is installed, else None."""
    import json
    try:
        with open(settings_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    for entry in data.get('hooks', {}).get('Stop', []):
        for hook in entry.get('hooks', []):
            cmd = hook.get('command', '')
            if _HOOK_MARKER in cmd:
                return cmd
    return None


def check_hook_settings_file(settings_path: str) -> CheckResult:
    if not os.path.isfile(settings_path):
        return CheckResult(
            'WARN',
            f'Claude Code settings not found at {settings_path}',
            remediation='Install Claude Code or run it once to create settings.json.',
        )
    return CheckResult('PASS', f'Claude Code settings found at {settings_path}')


def check_hook_installed(settings_path: str) -> CheckResult:
    if not os.path.isfile(settings_path):
        return CheckResult('WARN', 'Cannot check hook — settings file absent (see above)')
    cmd = _find_hook_command(settings_path)
    if cmd is None:
        return CheckResult(
            'FAIL',
            f'To Wit stop hook not found in {settings_path}',
            remediation="Run 'towit install-hook' to register the stop hook.",
        )
    return CheckResult('PASS', f'Stop hook installed: {cmd}')


def check_hook_script_exists(hook_command: str) -> CheckResult:
    """Given the raw hook command string, verify the script path exists on disk."""
    # Command form: "python3 /abs/path/to/towit_hook.py"
    parts = hook_command.strip().split()
    script_path = next((p for p in parts if _HOOK_MARKER in p), None)
    if script_path is None:
        return CheckResult('WARN', 'Could not parse hook script path from command')
    if not os.path.isfile(script_path):
        return CheckResult(
            'FAIL',
            f'Hook script not found on disk: {script_path}',
            remediation='Reinstall To Wit to restore the hook script, then run \'towit install-hook\'.',
        )
    return CheckResult('PASS', f'Hook script exists at {script_path}')
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `OK (33 tests)`

- [ ] **Step 5: Commit**

```bash
git add libexec/towit/towit_doctor.py tests/helpers/towit_doctor_test.py
git commit -m "feat: add stop hook installation doctor checks"
```

---

## Task 6: `main()` entry point

**Files:**
- Modify: `libexec/towit/towit_doctor.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/helpers/towit_doctor_test.py`:

```python
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HELPERS_DIR = os.path.join(PROJECT_ROOT, 'libexec', 'towit')
DOCTOR_SCRIPT = os.path.join(HELPERS_DIR, 'towit_doctor.py')


class TestDoctorMain(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = os.path.join(self.tmpdir, 'config.toml')
        self.settings_path = os.path.join(self.tmpdir, 'settings.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, extra_env=None):
        env = {
            **os.environ,
            'TOWIT_CONFIG_PATH': self.config_path,
            'TOWIT_SETTINGS_PATH': self.settings_path,
        }
        if extra_env:
            env.update(extra_env)
        env.pop('TOWIT_DB_PATH', None)
        return subprocess.run(
            ['python3', DOCTOR_SCRIPT],
            capture_output=True, text=True, env=env,
        )

    def _write_config(self):
        with open(self.config_path, 'w') as f:
            f.write(f'[database]\npath = "{self.db_path}"\n')

    def _make_db(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE conversations (id TEXT PRIMARY KEY, folder TEXT NOT NULL,
                cwd TEXT, started_at TEXT, last_active TEXT, title TEXT, summary TEXT,
                message_count INTEGER, indexed_at TEXT NOT NULL DEFAULT (datetime('now')));
            CREATE TABLE topics (id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL COLLATE NOCASE);
            CREATE TABLE conversation_topics (
                conversation_id TEXT NOT NULL, topic_id INTEGER NOT NULL,
                PRIMARY KEY (conversation_id, topic_id));
            CREATE TABLE keywords (id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL COLLATE NOCASE);
            CREATE TABLE conversation_keywords (
                conversation_id TEXT NOT NULL, keyword_id INTEGER NOT NULL,
                PRIMARY KEY (conversation_id, keyword_id));
        """)
        conn.commit()
        conn.close()
        os.chmod(self.db_path, 0o600)
        os.chmod(self.tmpdir, 0o700)

    def _install_hook(self, hook_script_path):
        import json
        data = {'hooks': {'Stop': [{'matcher': '', 'hooks': [
            {'type': 'command', 'command': f'python3 {hook_script_path}'}
        ]}]}}
        with open(self.settings_path, 'w') as f:
            json.dump(data, f)

    def test_help_exits_zero(self):
        result = subprocess.run(
            ['python3', DOCTOR_SCRIPT, '--help'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        combined = result.stdout + result.stderr
        self.assertIn('usage', combined.lower())

    def test_missing_db_prints_fail_and_exits_one(self):
        self._write_config()
        self._install_hook(DOCTOR_SCRIPT)  # script exists; hook content not checked here
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn('[FAIL]', result.stdout)
        self.assertIn('Database not found', result.stdout)

    def test_hook_not_installed_prints_fail_and_exits_one(self):
        self._write_config()
        self._make_db()
        with open(self.settings_path, 'w') as f:
            import json; json.dump({}, f)
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn('[FAIL]', result.stdout)
        self.assertIn('stop hook not found', result.stdout.lower())

    def test_all_ok_prints_pass_lines_and_exits_zero(self):
        self._write_config()
        self._make_db()
        hook_script = os.path.join(
            PROJECT_ROOT, 'libexec', 'towit', 'towit_hook.py'
        )
        self._install_hook(hook_script)
        result = self._run()
        self.assertEqual(result.returncode, 0, f"Expected exit 0, got output:\n{result.stdout}")
        self.assertNotIn('[FAIL]', result.stdout)
        self.assertIn('[PASS]', result.stdout)
        self.assertIn('All checks passed', result.stdout)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: The `TestDoctorMain` tests fail because there is no `main()` yet (the script runs nothing when invoked directly).

- [ ] **Step 3: Implement `main()`**

Add to the bottom of `towit_doctor.py`:

```python
# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog='towit doctor',
        description='Verify that To Wit setup is complete and configuration is valid.',
    )
    parser.parse_args()  # only --help is accepted; any other arg is an error

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from towit_config import Config, CONFIG_PATH
    from towit_install_hook import SETTINGS_PATH, HOOK_MARKER

    config_path = os.environ.get('TOWIT_CONFIG_PATH', CONFIG_PATH)
    settings_path = os.environ.get('TOWIT_SETTINGS_PATH', SETTINGS_PATH)

    cfg = Config(config_path)
    db_path = cfg.db_path

    results = []

    # --- Python & tooling ---
    results.append(check_python_version())
    results.append(check_claude_cli())

    # --- Configuration ---
    results.append(check_config_file(config_path))
    if os.path.isfile(config_path):
        results.append(check_config_unknown_keys(config_path))
    results.append(check_deprecated_env())

    # --- Database ---
    results.append(check_db_exists(db_path))
    if os.path.isfile(db_path):
        results.append(check_db_permissions(db_path))
        results.append(check_db_dir_permissions(db_path))
        results.append(check_db_tables(db_path))
        if not any(r.status == 'FAIL' and 'Missing tables' in r.label for r in results):
            results.append(check_db_schema(db_path))

    # --- Stop hook ---
    results.append(check_hook_settings_file(settings_path))
    results.append(check_hook_installed(settings_path))
    hook_cmd = _find_hook_command(settings_path)
    if hook_cmd:
        results.append(check_hook_script_exists(hook_cmd))

    # --- Print results ---
    for result in results:
        for line in format_result(result):
            print(line)

    summary, code = summarise(results)
    print()
    print(summary)
    sys.exit(code)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 tests/helpers/towit_doctor_test.py 2>&1
```

Expected: `OK (39 tests)`

- [ ] **Step 5: Commit**

```bash
git add libexec/towit/towit_doctor.py tests/helpers/towit_doctor_test.py
git commit -m "feat: add towit_doctor main() entry point orchestrating all checks"
```

---

## Task 7: Wire into dispatcher and BATS CLI tests

**Files:**
- Modify: `bin/towit`
- Modify: `tests/bin/towit.bats`

- [ ] **Step 1: Write the failing BATS tests**

Add to `tests/bin/towit.bats` after the `setup` subcommand tests:

```bash
# ---------------------------------------------------------------------------
# doctor subcommand
# ---------------------------------------------------------------------------

@test "towit: doctor --help exits 0 and prints usage" {
  run "${TOWIT}" doctor --help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"usage"* ]] || [[ "${output}" == *"Usage"* ]] || {
    echo "Expected 'usage' in output, got: ${output}"; return 1
  }
}

@test "towit: doctor exits non-zero when database is missing" {
  # DB not set up; TOWIT_CONFIG_PATH points to a config referencing a nonexistent DB
  run "${TOWIT}" doctor
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"[FAIL]"* ]] || {
    echo "Expected [FAIL] in output, got: ${output}"; return 1
  }
}

@test "towit: doctor prints [PASS] for database after setup" {
  "${TOWIT}" setup
  run "${TOWIT}" doctor
  [[ "${output}" == *"[PASS]"* ]] || {
    echo "Expected [PASS] lines in output, got: ${output}"; return 1
  }
  [[ "${output}" == *"Database"* ]] || {
    echo "Expected 'Database' in output, got: ${output}"; return 1
  }
}

@test "towit: doctor output contains no JSON or CSV" {
  run "${TOWIT}" doctor
  [[ "${output}" != *"{"* ]] || { echo "Unexpected JSON in output"; return 1; }
  [[ "${output}" != *'","'* ]] || { echo "Unexpected CSV in output"; return 1; }
}

@test "towit: doctor rejects unknown flags" {
  run "${TOWIT}" doctor --json
  [ "${status}" -ne 0 ]
}
```

- [ ] **Step 2: Run BATS to confirm failures**

```bash
./run-tests tests/bin/towit.bats --filter "doctor" 2>&1
```

Expected: All 5 doctor tests fail with "unknown subcommand 'doctor'"

- [ ] **Step 3: Add `doctor` case to `bin/towit`**

In `bin/towit`, add the case entry to the usage comment at the top and to the `case` block.

In the usage comment block (after `stats`), add:
```
#   doctor                        Verify setup, config, database, and hook
```

In the `case` block (after `stats)`):
```bash
  doctor)
    shift
    python3 "${HELPERS_DIR}/towit_doctor.py" "$@" || exit $?
    ;;
```

- [ ] **Step 4: Run BATS to confirm they pass**

```bash
./run-tests tests/bin/towit.bats --filter "doctor" 2>&1
```

Expected: All 5 doctor tests pass.

- [ ] **Step 5: Run full test suite**

```bash
./run-tests 2>&1
```

Expected: All tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add bin/towit tests/bin/towit.bats
git commit -m "feat: wire towit doctor subcommand into dispatcher with CLI tests"
```

---

## Self-Review

**Spec coverage:**
- ✅ Verifies setup steps: Python version, claude CLI, config file, DB, hook
- ✅ Configuration validity: TOML parse, unknown keys, deprecated env var
- ✅ Database: existence, permissions (file + dir), tables, schema migration
- ✅ No automatic remediation — prints hints only
- ✅ Plain text output only — no JSON/CSV
- ✅ Only `--help` flag accepted; unknown flags cause error + non-zero exit
- ✅ Exit 0 = all pass/warn; exit 1 = any fail

**Placeholder scan:** No TBDs, TODOs, or "similar to above" present.

**Type consistency:** `CheckResult` defined once in Task 1 and used identically in Tasks 2–6. `_find_hook_command` defined in Task 5 and reused in Task 6's `main()`.
