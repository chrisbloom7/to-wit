# Config File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `~/.towit/config.toml` as the persistent config mechanism for To Wit, replacing `TOWIT_DB_PATH` with a `[database] path` entry.

**Architecture:** A new `towit_config.py` shared module loads the TOML file, warns on errors, and exposes a `Config` class with typed property accessors plus a module-level singleton. Consumer modules (`towit_db`, `towit_setup`, `towit_teardown`, `towit_implode`, `towit_index`) import the singleton instead of reading env vars directly. Tests use `TOWIT_CONFIG_PATH` pointing to a temp file for isolation.

**Tech Stack:** Python 3.11+ stdlib `tomllib`, `unittest`, `tempfile`, BATS

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `libexec/towit/towit_config.py` | Config loading, `Config` class, module singleton |
| Create | `tests/helpers/towit_config_test.py` | Unit tests for `towit_config.py` |
| Modify | `libexec/towit/towit_db.py` | Remove `DB_PATH` env var; use `config.db_path` as default |
| Modify | `libexec/towit/towit_index.py` | Remove `DB_PATH` import; use `config` |
| Modify | `libexec/towit/towit_setup.py` | Remove env var lookup; add `--config` flag |
| Modify | `libexec/towit/towit_teardown.py` | Remove `DB_PATH` env var; use `config.db_path` |
| Modify | `libexec/towit/towit_implode.py` | Remove `DB_PATH` env var; use `config.db_path` |
| Modify | `tests/helpers/towit_db_test.py` | Remove `TOWIT_DB_PATH` env var usage |
| Modify | `tests/helpers/towit_index_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/helpers/towit_backfill_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/helpers/towit_setup_test.py` | Switch to `TOWIT_CONFIG_PATH`; add `--config` tests |
| Modify | `tests/helpers/towit_teardown_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/helpers/towit_implode_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/helpers/towit_search_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/helpers/towit_prune_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/helpers/towit_resume_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/helpers/towit_stats_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/helpers/towit_list_test.py` | Switch to `TOWIT_CONFIG_PATH` |
| Modify | `tests/test_helper.bash` | Set `TOWIT_CONFIG_PATH` instead of `TOWIT_DB_PATH` |
| Modify | `tests/bin/towit.bats` | Add `--config` and `--full` config tests; update env refs |
| Modify | `CHANGELOG.md` | Document the change and `TOWIT_DB_PATH` migration |

---

## Task 1: Create `towit_config.py` with unit tests (TDD)

**Files:**
- Create: `tests/helpers/towit_config_test.py`
- Create: `libexec/towit/towit_config.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/helpers/towit_config_test.py`:

```python
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
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
            self.assertEqual(cfg.db_path, _DEFAULT_DB_PATH)

    def test_missing_file_produces_no_warnings(self):
        cfg = Config(path='/nonexistent/config.toml')
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
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
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
            self.assertEqual(cfg.db_path, '/tmp/custom.db')

    def test_expands_tilde_in_database_path(self):
        path = write_config(self.tmpdir, '[database]\npath = "~/.towit/custom.db"\n')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
            self.assertEqual(cfg.db_path, os.path.expanduser('~/.towit/custom.db'))

    def test_empty_config_returns_defaults(self):
        path = write_config(self.tmpdir, '')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
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
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
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
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
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
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
            with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as mock_err:
                _ = cfg.db_path
                self.assertIn('Warning', mock_err.getvalue())

    def test_wrong_type_for_database_path_uses_default(self):
        path = write_config(self.tmpdir, '[database]\npath = 42\n')
        cfg = Config(path=path)
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('TOWIT_DB_PATH', None)
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
```

- [ ] **Step 1.2: Run the tests to confirm they fail**

```bash
python3 tests/helpers/towit_config_test.py
```

Expected: `ModuleNotFoundError: No module named 'towit_config'`

- [ ] **Step 1.3: Implement `towit_config.py`**

Create `libexec/towit/towit_config.py`:

```python
#!/usr/bin/env python3
"""
towit_config — Configuration loader for To Wit.

Loads ~/.towit/config.toml (or TOWIT_CONFIG_PATH) and exposes a Config
object with typed property accessors. Missing file → silent defaults.
Bad TOML or wrong types → warning to stderr, defaults used.

This module is imported by other towit scripts; it is not run directly.
"""

import os
import sys

try:
    import tomllib
except ImportError:
    raise SystemExit("towit requires Python 3.11+ for TOML config support.")

_DEFAULT_CONFIG_PATH = os.path.expanduser('~/.towit/config.toml')
_DEFAULT_DB_PATH = os.path.expanduser('~/.towit/catalog.db')

CONFIG_PATH = os.environ.get('TOWIT_CONFIG_PATH', _DEFAULT_CONFIG_PATH)

# Registry of known config sections and their known keys.
# Used to emit warnings for unrecognized entries.
_KNOWN_KEYS = {
    'database': {'path'},
}


class Config:
    def __init__(self, path=None):
        self._path = path if path is not None else CONFIG_PATH
        self._data = self._load()
        self._warn_unknown_keys()

    def _load(self):
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, 'rb') as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            print(
                f"Warning: could not parse config file {self._path}: {exc}",
                file=sys.stderr,
            )
            return {}

    def _warn_unknown_keys(self):
        for section, value in self._data.items():
            if section not in _KNOWN_KEYS:
                print(
                    f"Warning: unknown config section [{section}]; ignoring.",
                    file=sys.stderr,
                )
                continue
            if not isinstance(value, dict):
                continue
            for key in value:
                if key not in _KNOWN_KEYS[section]:
                    print(
                        f"Warning: unknown config key [{section}] {key!r}; ignoring.",
                        file=sys.stderr,
                    )

    def _get(self, section, key, default, expected_type):
        section_data = self._data.get(section, {})
        if not isinstance(section_data, dict):
            return default
        if key not in section_data:
            return default
        value = section_data[key]
        if not isinstance(value, expected_type):
            print(
                f"Warning: config [{section}] {key!r} must be a "
                f"{expected_type.__name__}; using default ({default!r}).",
                file=sys.stderr,
            )
            return default
        return value

    @property
    def db_path(self) -> str:
        """Resolved database path. TOWIT_DB_PATH env var overrides (deprecated)."""
        env_db_path = os.environ.get('TOWIT_DB_PATH')
        if env_db_path:
            print(
                "Warning: TOWIT_DB_PATH is deprecated. "
                "Set [database] path in your config file instead.",
                file=sys.stderr,
            )
            return env_db_path
        raw = self._get('database', 'path', _DEFAULT_DB_PATH, str)
        return os.path.expanduser(raw)


config = Config()
```

- [ ] **Step 1.4: Run the tests to confirm they pass**

```bash
python3 tests/helpers/towit_config_test.py
```

Expected: All tests pass with `OK`.

- [ ] **Step 1.5: Commit**

```bash
git add libexec/towit/towit_config.py tests/helpers/towit_config_test.py
git commit -m "feat: add towit_config module with TOML config file support"
```

---

## Task 2: Update `towit_db.py` to use config

**Files:**
- Modify: `libexec/towit/towit_db.py`

`DB_PATH` is currently a module-level constant read from env. Replace it with a lazy default via `config.db_path`. Tests that pass `Database(self.db_path)` explicitly are unaffected.

- [ ] **Step 2.1: Update `towit_db.py`**

Replace the top of the file (lines 1–16):

```python
#!/usr/bin/env python3
"""
towit_db — Database abstraction layer for the To Wit catalog.

This module is imported by other towit scripts; it is not run directly.
"""

import contextlib
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_config import config
```

Replace the `Database.__init__` signature (line 53):

```python
    def __init__(self, db_path=None):
        self.db_path = db_path if db_path is not None else config.db_path
```

- [ ] **Step 2.2: Run existing db tests to confirm they still pass**

```bash
python3 tests/helpers/towit_db_test.py
```

Expected: All tests pass. (These tests pass `db_path` explicitly to `Database()`, so the config change is transparent to them. The `TOWIT_DB_PATH` env var set in some db tests will trigger a deprecation warning but the test assertions still hold — that cleanup happens in Task 8.)

- [ ] **Step 2.3: Commit**

```bash
git add libexec/towit/towit_db.py
git commit -m "refactor: towit_db uses config.db_path instead of TOWIT_DB_PATH env var"
```

---

## Task 3: Update `towit_index.py` to use config

**Files:**
- Modify: `libexec/towit/towit_index.py`

`towit_index.py` imports `DB_PATH` from `towit_db` and uses it as a fallback. Since `Database(None)` now reads from config, the explicit fallback is no longer needed.

- [ ] **Step 3.1: Update the import and `index_conversation` default in `towit_index.py`**

Replace line 16:
```python
from towit_db import Database, DB_PATH
```
With:
```python
from towit_db import Database
```

Replace line 244 inside `index_conversation`:
```python
        db = Database(db_path or DB_PATH)
```
With:
```python
        db = Database(db_path)
```

- [ ] **Step 3.2: Run index tests to confirm they still pass**

```bash
python3 tests/helpers/towit_index_test.py
```

Expected: All tests pass. (The `TOWIT_DB_PATH` env var in index tests still works via the deprecation path in `config.db_path`. Cleanup happens in Task 8.)

- [ ] **Step 3.3: Commit**

```bash
git add libexec/towit/towit_index.py
git commit -m "refactor: towit_index uses config via Database default instead of DB_PATH"
```

---

## Task 4: Update `towit_setup.py` — use config and add `--config` flag

**Files:**
- Modify: `libexec/towit/towit_setup.py`

`towit_setup.py` currently reads `TOWIT_DB_PATH` twice (via import and env lookup). Replace both with `config.db_path`. Add a `--config` flag that generates a starter `config.toml` and update `--full` to call it.

- [ ] **Step 4.1: Rewrite `towit_setup.py`**

```python
#!/usr/bin/env python3
"""
towit_setup — Initialize the To Wit catalog database.

Usage:
    python3 towit_setup.py [--config] [--full] [--hook]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_config import config, CONFIG_PATH
from towit_db import Database

_CONFIG_TEMPLATE = """\
# To Wit configuration
# https://github.com/chrisbloom7/to-wit
#
# Generated by: towit setup --config
# Edit this file to customize To Wit's behavior.

[database]
# Database file path. Default: ~/.towit/catalog.db
# path = "~/.towit/catalog.db"
"""


def generate_config():
    """Write a starter config.toml. Does nothing if file already exists."""
    config_path = os.path.expanduser(CONFIG_PATH)
    if os.path.isfile(config_path):
        print(f"Config file already exists at {config_path}")
        return
    parent = os.path.dirname(config_path)
    os.makedirs(parent, exist_ok=True)
    old_umask = os.umask(0o177)  # 0600 permissions
    try:
        with open(config_path, 'w') as f:
            f.write(_CONFIG_TEMPLATE)
    finally:
        os.umask(old_umask)
    print(f"Config file created at {config_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Initialize the To Wit catalog database.'
    )
    parser.add_argument('--config', action='store_true',
                        help='Generate a starter config.toml')
    parser.add_argument('--full', action='store_true',
                        help='Also generate config, install hook, and run backfill')
    parser.add_argument('--hook', action='store_true',
                        help='Also install the stop hook after setup')
    args = parser.parse_args()

    if args.full or args.config:
        generate_config()

    db_path = config.db_path
    db = Database(db_path)

    if os.path.isfile(db_path):
        db.run_migrations()
        print(f"Database already initialized at {db_path}")
        if not (args.full or args.hook):
            sys.exit(0)
    else:
        parent = os.path.dirname(db_path)
        old_umask = os.umask(0o077)
        try:
            os.makedirs(parent, exist_ok=True)
            db.create_schema()
        finally:
            os.umask(old_umask)
        print(f"Database initialized at {db_path}")

    if args.full or args.hook:
        from towit_install_hook import main as install_hook
        install_hook()

    if args.full:
        from towit_backfill import main as backfill
        backfill()


if __name__ == '__main__':
    main()
```

- [ ] **Step 4.2: Run setup tests to confirm existing tests still pass**

```bash
python3 tests/helpers/towit_setup_test.py
```

Expected: All existing tests pass. (They pass `TOWIT_DB_PATH` env var which still works via deprecation path.)

- [ ] **Step 4.3: Commit**

```bash
git add libexec/towit/towit_setup.py
git commit -m "feat: towit setup --config generates starter config.toml; use config module"
```

---

## Task 5: Update `towit_teardown.py` to use config

**Files:**
- Modify: `libexec/towit/towit_teardown.py`

Remove the module-level `DB_PATH` env var lookup; use `config.db_path` at runtime instead.

- [ ] **Step 5.1: Update `towit_teardown.py`**

Replace lines 8–16 (imports and `DB_PATH`):

```python
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from towit_config import config
```

Replace all uses of the module-level `DB_PATH` constant inside `main()` with `config.db_path`. The function becomes:

```python
def main():
    db_path = config.db_path
    parser = argparse.ArgumentParser(description='Remove To Wit hook and database')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')
    args = parser.parse_args()

    hook_installed = _check_hook_installed()
    db_exists = os.path.exists(db_path)

    if not hook_installed and not db_exists:
        print("Nothing to tear down — hook is not installed and database does not exist.")
        sys.exit(0)

    print("The following will be removed:")
    if hook_installed:
        print("  • To Wit stop hook from ~/.claude/settings.json")
    if db_exists:
        print(f"  • Database at {db_path}")

    if not args.yes:
        try:
            answer = input("\nContinue? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer not in ('y', 'yes'):
            print("Aborted.")
            sys.exit(1)

    if hook_installed:
        _remove_hook()

    if db_exists:
        os.remove(db_path)
        print(f"Database deleted: {db_path}")

    print("Teardown complete.")
```

- [ ] **Step 5.2: Run teardown tests to confirm they still pass**

```bash
python3 tests/helpers/towit_teardown_test.py
```

Expected: All tests pass.

- [ ] **Step 5.3: Commit**

```bash
git add libexec/towit/towit_teardown.py
git commit -m "refactor: towit_teardown uses config.db_path instead of TOWIT_DB_PATH env var"
```

---

## Task 6: Update `towit_implode.py` to use config

**Files:**
- Modify: `libexec/towit/towit_implode.py`

Remove the module-level `DB_PATH` / `DATA_DIR` env var lookups; resolve at runtime from config.

- [ ] **Step 6.1: Update `towit_implode.py`**

Replace lines 8–21 (imports, `DB_PATH`, `DATA_DIR`, `DEFAULT_INSTALL_DIR`):

```python
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from towit_config import config

DEFAULT_INSTALL_DIR = '/usr/local/bin'
```

Update `main()` to resolve `db_path` and `data_dir` at runtime:

```python
def main():
    db_path = config.db_path
    data_dir = os.path.dirname(db_path)

    parser = argparse.ArgumentParser(
        description='Remove To Wit hook, database, and binary symlink'
    )
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')
    parser.add_argument('--install-dir', default=DEFAULT_INSTALL_DIR,
                        metavar='DIR',
                        help=f'Directory where towit binary was installed (default: {DEFAULT_INSTALL_DIR})')
    args = parser.parse_args()

    binary = os.path.join(args.install_dir, 'towit')
    hook_installed = _check_hook_installed()
    db_exists = os.path.exists(db_path)
    binary_is_symlink = os.path.islink(binary)
    binary_exists = os.path.exists(binary)

    if not hook_installed and not db_exists and not binary_is_symlink:
        if binary_exists:
            print(f"Warning: '{binary}' exists but is not a symlink — not removing.")
            print("         Remove it manually if needed.")
        else:
            print("Nothing to remove — hook is not installed, database does not exist, "
                  f"and no symlink found at {binary}.")
        _print_data_dir(data_dir)
        sys.exit(0)

    print("The following will be removed:")
    if hook_installed:
        print("  • To Wit stop hook from ~/.claude/settings.json")
    if db_exists:
        print(f"  • Database at {db_path}")
    if binary_is_symlink:
        print(f"  • Binary symlink at {binary}")

    if not args.yes:
        try:
            answer = input("\nContinue? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer not in ('y', 'yes'):
            print("Aborted.")
            sys.exit(1)

    if hook_installed:
        _remove_hook()

    if db_exists:
        os.remove(db_path)
        print(f"Database deleted: {db_path}")

    if binary_is_symlink:
        os.remove(binary)
        print(f"Removed: {binary}")

    print("Implode complete.")
    _print_data_dir(data_dir)
```

Update `_print_data_dir` to accept `data_dir` as parameter:

```python
def _print_data_dir(data_dir):
    print(f"\nTo Wit data directory: {data_dir}")
    if os.path.isdir(data_dir):
        contents = os.listdir(data_dir)
        if contents:
            print("  Remaining files:")
            for name in sorted(contents):
                print(f"    {os.path.join(data_dir, name)}")
        else:
            print("  (empty)")
    else:
        print("  (does not exist)")
```

- [ ] **Step 6.2: Run implode tests to confirm they still pass**

```bash
python3 tests/helpers/towit_implode_test.py
```

Expected: All tests pass.

- [ ] **Step 6.3: Commit**

```bash
git add libexec/towit/towit_implode.py
git commit -m "refactor: towit_implode uses config.db_path instead of TOWIT_DB_PATH env var"
```

---

## Task 7: Update Python subprocess test helpers

**Files:**
- Modify: `tests/helpers/towit_setup_test.py`
- Modify: `tests/helpers/towit_teardown_test.py`
- Modify: `tests/helpers/towit_implode_test.py`
- Modify: `tests/helpers/towit_search_test.py`
- Modify: `tests/helpers/towit_prune_test.py`
- Modify: `tests/helpers/towit_resume_test.py`
- Modify: `tests/helpers/towit_stats_test.py`
- Modify: `tests/helpers/towit_list_test.py`

Each test file has `run_*` helpers that pass `TOWIT_DB_PATH` to subprocess envs. Replace with `TOWIT_CONFIG_PATH` pointing to a temp config file. Add a shared `write_config` helper to each file.

**Pattern:** add this helper near the top of each file (after imports), then update every `run_*` function to accept and pass `config_path` instead of `db_path` in the env.

```python
def write_config(tmpdir, db_path):
    """Write a minimal config.toml containing db_path. Returns config file path."""
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path
```

- [ ] **Step 7.1: Update `tests/helpers/towit_setup_test.py`**

Replace `run_setup`:

```python
def write_config(tmpdir, db_path):
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_setup(db_path, config_path, args=None):
    """Run towit_setup.py as a subprocess with the given config."""
    return subprocess.run(
        ['python3', SETUP_SCRIPT] + (args or []),
        env={**os.environ, 'TOWIT_CONFIG_PATH': config_path},
        capture_output=True,
        text=True
    )
```

Update `setUp` to create a config file and thread `config_path` through each test:

```python
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.config_path = write_config(self.tmpdir, self.db_path)
```

Update every `run_setup(self.db_path)` call to `run_setup(self.db_path, self.config_path)`.

- [ ] **Step 7.2: Update `tests/helpers/towit_teardown_test.py`**

Add `write_config` helper. Update `run_setup` and `run_teardown`:

```python
def write_config(tmpdir, db_path):
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_setup(db_path, config_path, home):
    env = {**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home}
    return subprocess.run(['python3', SETUP_SCRIPT], env=env, capture_output=True, text=True)


def run_teardown(db_path, config_path, home, args=None, stdin_input=None):
    settings_path = os.path.join(home, SETTINGS_REL_PATH)
    env = {**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home,
           'TOWIT_SETTINGS_PATH': settings_path}
    return subprocess.run(
        ['python3', TEARDOWN_SCRIPT] + (args or []),
        env=env, input=stdin_input, capture_output=True, text=True
    )
```

Add `config_path` to `setUp` and update all call sites:

```python
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        self.settings_path = os.path.join(self.tmpdir, SETTINGS_REL_PATH)
        self.config_path = write_config(self.tmpdir, self.db_path)
```

Update every `run_setup(self.db_path, self.tmpdir)` to `run_setup(self.db_path, self.config_path, self.tmpdir)` and every `run_teardown(self.db_path, self.tmpdir, ...)` to `run_teardown(self.db_path, self.config_path, self.tmpdir, ...)`.

- [ ] **Step 7.3: Update `tests/helpers/towit_implode_test.py`**

Same pattern — add `write_config`, update `run_setup` and `run_implode` signatures and call sites. `setUp` gets `self.config_path = write_config(self.tmpdir, self.db_path)`.

```python
def write_config(tmpdir, db_path):
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_setup(db_path, config_path, home):
    env = {**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home}
    return subprocess.run(['python3', SETUP_SCRIPT], env=env, capture_output=True, text=True)


def run_implode(db_path, config_path, home, settings_path=None, args=None, stdin_input=None):
    env = {**os.environ, 'TOWIT_CONFIG_PATH': config_path, 'HOME': home}
    if settings_path:
        env['TOWIT_SETTINGS_PATH'] = settings_path
    return subprocess.run(
        ['python3', IMPLODE_SCRIPT] + (args or []),
        env=env, input=stdin_input, capture_output=True, text=True
    )
```

- [ ] **Step 7.4: Update the four single-helper test files**

For `towit_search_test.py`, `towit_prune_test.py`, `towit_resume_test.py`, `towit_stats_test.py`, and `towit_list_test.py`, the pattern is identical. In each file:

1. Add `write_config` helper.
2. Add `self.config_path = write_config(self.tmpdir, self.db_path)` to `setUp`.
3. Update the `run_*` function to accept `config_path` and use `'TOWIT_CONFIG_PATH': config_path` instead of `'TOWIT_DB_PATH': db_path`.
4. Update all call sites.

Example — `run_search` after the change:

```python
def write_config(tmpdir, db_path):
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path


def run_search(config_path, args):
    """Run towit_search.py as a subprocess."""
    return subprocess.run(
        ['python3', SEARCH_SCRIPT] + args,
        env={**os.environ, 'TOWIT_CONFIG_PATH': config_path},
        capture_output=True,
        text=True
    )
```

Apply the same pattern to the `run_*` helpers in prune, resume, stats, and list test files.

- [ ] **Step 7.5: Run all updated subprocess tests**

```bash
./run-tests tests/helpers/towit_setup_test.py
./run-tests tests/helpers/towit_teardown_test.py
./run-tests tests/helpers/towit_implode_test.py
./run-tests tests/helpers/towit_search_test.py
./run-tests tests/helpers/towit_prune_test.py
./run-tests tests/helpers/towit_resume_test.py
./run-tests tests/helpers/towit_stats_test.py
./run-tests tests/helpers/towit_list_test.py
```

Expected: All tests in all files pass.

- [ ] **Step 7.6: Commit**

```bash
git add tests/helpers/
git commit -m "test: migrate subprocess test helpers from TOWIT_DB_PATH to TOWIT_CONFIG_PATH"
```

---

## Task 8: Update Python direct-import tests

**Files:**
- Modify: `tests/helpers/towit_db_test.py`
- Modify: `tests/helpers/towit_index_test.py`
- Modify: `tests/helpers/towit_backfill_test.py`

These tests set `os.environ['TOWIT_DB_PATH']` directly (not via subprocess). Since they also pass `db_path` explicitly to `Database()` or other constructors, the env var is redundant — remove it.

- [ ] **Step 8.1: Update `tests/helpers/towit_db_test.py`**

Find every `setUp` / `tearDown` pair that does:
```python
os.environ['TOWIT_DB_PATH'] = self.db_path
...
os.environ.pop('TOWIT_DB_PATH', None)
```

Remove both lines from every occurrence. The tests pass `db_path` explicitly to `Database(self.db_path)`, so these env var lines were redundant and are no longer needed.

- [ ] **Step 8.2: Update `tests/helpers/towit_index_test.py`**

Same removal — find `os.environ['TOWIT_DB_PATH'] = self.db_path` and `os.environ.pop('TOWIT_DB_PATH', None)` and remove them. Verify that the test still passes an explicit `db_path` to `index_conversation`.

- [ ] **Step 8.3: Update `tests/helpers/towit_backfill_test.py`**

Remove the `patch.dict(os.environ, {'TOWIT_DB_PATH': db_path})` context and the direct `os.environ['TOWIT_DB_PATH']` assignments. Add `write_config` and pass config via `TOWIT_CONFIG_PATH` in the subprocess env instead.

```python
def write_config(tmpdir, db_path):
    config_path = os.path.join(tmpdir, 'config.toml')
    with open(config_path, 'w') as f:
        f.write(f'[database]\npath = "{db_path}"\n')
    return config_path
```

- [ ] **Step 8.4: Run the updated direct-import tests**

```bash
./run-tests tests/helpers/towit_db_test.py
./run-tests tests/helpers/towit_index_test.py
./run-tests tests/helpers/towit_backfill_test.py
```

Expected: All tests pass with no deprecation warnings.

- [ ] **Step 8.5: Commit**

```bash
git add tests/helpers/towit_db_test.py tests/helpers/towit_index_test.py tests/helpers/towit_backfill_test.py
git commit -m "test: remove TOWIT_DB_PATH from direct-import tests"
```

---

## Task 9: Update BATS tests and add `--config` tests

**Files:**
- Modify: `tests/test_helper.bash`
- Modify: `tests/bin/towit.bats`

- [ ] **Step 9.1: Update `tests/test_helper.bash`**

Replace the `TOWIT_DB_PATH` export with a temp config file setup:

```bash
_setup_common() {
  TEST_TMPDIR="$(mktemp -d)"

  mkdir -p "${TEST_TMPDIR}/mock_bin"

  # No-op sleep mock (speeds up any log-style sleeps)
  cat > "${TEST_TMPDIR}/mock_bin/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${TEST_TMPDIR}/mock_bin/sleep"

  export PATH="${TEST_TMPDIR}/mock_bin:${PATH}"

  # Config file controls DB path for all subprocess invocations
  export TOWIT_CONFIG_PATH="${TEST_TMPDIR}/config.toml"
  local db_path="${TEST_TMPDIR}/test.db"
  printf '[database]\npath = "%s"\n' "${db_path}" > "${TOWIT_CONFIG_PATH}"

  export TOWIT="${BIN_DIR}/towit"

  # Clear mode vars that shell scripts might reference
  export FORCE_MODE=false
  export VERBOSE_MODE=false
  export QUIET_MODE=false
}
```

- [ ] **Step 9.2: Update `tests/bin/towit.bats` setup block and references**

In the `setup()` function at the top of `towit.bats`, remove the `export TOWIT_DB_PATH` line:

```bash
setup() {
  _setup_common
  TOWIT="${BIN_DIR}/towit"
}
```

Find and update the missing-python3 test (currently uses `TOWIT_DB_PATH` explicitly):

```bash
@test "towit: missing python3 prints helpful error and exits non-zero" {
  local no_py_bin="${TEST_TMPDIR}/no_python3"
  mkdir -p "${no_py_bin}"
  cat > "${no_py_bin}/python3" <<'EOF'
#!/bin/sh
echo "python3: command not found" >&2
exit 127
EOF
  chmod +x "${no_py_bin}/python3"
  run -127 env -i \
    HOME="${HOME}" \
    TOWIT_CONFIG_PATH="${TOWIT_CONFIG_PATH}" \
    PATH="${no_py_bin}:/usr/local/bin:/usr/bin:/bin" \
    "${TOWIT}" setup 2>&1
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"python3"* ]] || [[ "${output}" == *"Python"* ]] || {
    echo "Expected python3 error message, got: ${output}"; return 1
  }
}
```

Also update any remaining `TOWIT_DB_PATH` reference in the prune tests or other inline env overrides:

```bash
# Before:
TOWIT_DB_PATH="${TEST_TMPDIR}/test.db" \
# After:
TOWIT_CONFIG_PATH="${TOWIT_CONFIG_PATH}" \
```

- [ ] **Step 9.3: Write failing BATS tests for `towit setup --config`**

Add to `tests/bin/towit.bats` after the existing setup tests:

```bash
# ---------------------------------------------------------------------------
# setup --config subcommand
# ---------------------------------------------------------------------------

@test "towit: setup --config creates config file" {
  local cfg="${TEST_TMPDIR}/new_config.toml"
  export TOWIT_CONFIG_PATH="${cfg}"
  [ ! -f "${cfg}" ]
  run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
  [ -f "${cfg}" ] || {
    echo "Expected config file at ${cfg}"; return 1
  }
}

@test "towit: setup --config prints path of created config" {
  local cfg="${TEST_TMPDIR}/new_config.toml"
  export TOWIT_CONFIG_PATH="${cfg}"
  run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"${cfg}"* ]] || {
    echo "Expected config path in output, got: ${output}"; return 1
  }
}

@test "towit: setup --config is idempotent — does not overwrite existing config" {
  local cfg="${TEST_TMPDIR}/existing_config.toml"
  export TOWIT_CONFIG_PATH="${cfg}"
  echo "# my custom config" > "${cfg}"
  local mtime_before
  mtime_before="$(stat -f '%m' "${cfg}" 2>/dev/null || stat -c '%Y' "${cfg}")"
  sleep 0.05
  run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
  local mtime_after
  mtime_after="$(stat -f '%m' "${cfg}" 2>/dev/null || stat -c '%Y' "${cfg}")"
  [ "${mtime_before}" = "${mtime_after}" ] || {
    echo "Config file was overwritten — it should not be"; return 1
  }
  [[ "$(cat "${cfg}")" == "# my custom config" ]] || {
    echo "Config file content was changed"; return 1
  }
}

@test "towit: setup --config does not require database to exist" {
  local cfg="${TEST_TMPDIR}/standalone_config.toml"
  local fresh_db="${TEST_TMPDIR}/fresh.db"
  printf '[database]\npath = "%s"\n' "${fresh_db}" > "${cfg}"
  export TOWIT_CONFIG_PATH="${cfg}"
  run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
}
```

- [ ] **Step 9.4: Run new `--config` BATS tests**

```bash
./run-tests tests/bin/towit.bats --filter "setup --config"
```

Expected: All four new tests pass. (`--config` was implemented in Task 4.)

- [ ] **Step 9.5: Run the full BATS test suite**

```bash
./run-tests tests/bin/towit.bats
```

Expected: All tests pass.

- [ ] **Step 9.6: Commit**

```bash
git add tests/test_helper.bash tests/bin/towit.bats
git commit -m "test: migrate BATS tests from TOWIT_DB_PATH to TOWIT_CONFIG_PATH; add --config tests"
```

---

## Task 10: Update CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 10.1: Add entry under `[Unreleased]`**

Add to the `## [Unreleased]` section:

```markdown
## [Unreleased]

### Added
- Config file support: To Wit now reads `~/.towit/config.toml` (TOML format) for persistent configuration. Generate a starter file with `towit setup --config` or `towit setup --full`.
- `towit setup --config` flag: generates a commented starter `~/.towit/config.toml` with all options documented; does nothing if the file already exists.

### Changed
- `TOWIT_DB_PATH` environment variable is deprecated. Set `[database] path` in `~/.towit/config.toml` instead. `TOWIT_DB_PATH` continues to work but emits a deprecation warning. Migration:
  ```toml
  # ~/.towit/config.toml
  [database]
  path = "/your/custom/path/catalog.db"
  ```
- Minimum Python version bumped to **3.11** (required for stdlib `tomllib`).
- `towit setup --full` now also generates the config file as its first step.
```

- [ ] **Step 10.2: Run the full test suite one final time**

```bash
./run-tests
```

Expected: All BATS and Python tests pass.

- [ ] **Step 10.3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: document config file feature and TOWIT_DB_PATH deprecation in CHANGELOG"
```
