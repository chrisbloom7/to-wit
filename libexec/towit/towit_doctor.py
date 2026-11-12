#!/usr/bin/env python3
"""
towit_doctor — Verify that To Wit's setup is complete and correct.

Prints a plain-text health report and exits 0 if all checks pass (or only
warnings), 1 if any check fails.  Never performs automatic remediation.
"""

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import sys
import tomllib
from urllib.parse import quote
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_config import _KNOWN_KEYS
from towit_db import SCHEMA_VERSION
from towit_install_hook import HOOK_EVENTS
from towit_pipe import run_cli


@dataclass
class CheckResult:
    status: str          # 'PASS', 'WARN', or 'FAIL'
    label: str           # one-line description shown after the status tag
    remediation: str = ''  # shown indented below for WARN/FAIL


_USE_COLOR = sys.stdout.isatty()
_RESET = '\033[0m'
_STATUS_COLORS = {
    'PASS': '\033[32m',    # green
    'WARN': '\033[1;33m',  # bold yellow
    'FAIL': '\033[31m',    # red
}
_DARK_YELLOW = '\033[33m'


def format_result(result: CheckResult) -> list:
    """Return a list of output lines for one CheckResult."""
    if _USE_COLOR:
        color = _STATUS_COLORS.get(result.status, '')
        tag = f'{color}[{result.status}]{_RESET}'
    else:
        tag = f'[{result.status}]'
    lines = [f'{tag} {result.label}']
    if result.remediation and result.status in ('WARN', 'FAIL'):
        if _USE_COLOR:
            lines.append(f'       → {_DARK_YELLOW}{result.remediation}{_RESET}')
        else:
            lines.append(f'       → {result.remediation}')
    return lines


def summarise(results: list) -> tuple:
    """Return (summary_line, exit_code) for a list of CheckResults."""
    warns = sum(1 for r in results if r.status == 'WARN')
    fails = sum(1 for r in results if r.status == 'FAIL')
    if warns == 0 and fails == 0:
        return 'All checks passed.', 0
    parts = [f'{warns} warning(s)', f'{fails} failure(s)']
    return ', '.join(parts) + '.', (1 if fails else 0)


def check_python_version() -> CheckResult:
    """Check that Python version is 3.11 or later."""
    v = sys.version_info
    label = f'Python {v.major}.{v.minor}.{v.micro}'
    if (v.major, v.minor) < (3, 11):
        return CheckResult(
            'FAIL',
            f'{label} (3.11+ required for TOML config support)',
            remediation='Install Python 3.11 or later and ensure it is the active python3. Then run: towit setup',
        )
    return CheckResult('PASS', f'{label} (≥3.11 required for TOML support)')


VERSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION')


def check_towit_version(path: str = VERSION_PATH) -> CheckResult:
    """Report the installed To Wit version from the VERSION file shipped next to the helpers."""
    try:
        with open(path, encoding='utf-8') as fh:
            version = fh.read().strip()
    except OSError:
        version = ''
    if not version:
        return CheckResult(
            'WARN',
            f'To Wit version unknown (no readable version in {path})',
            remediation='Reinstall To Wit (for example: brew reinstall towit).',
        )
    return CheckResult('PASS', f'To Wit version {version}')


def check_claude_cli() -> CheckResult:
    """Check that the claude CLI is installed and available on PATH."""
    path = shutil.which('claude')
    if path is None:
        return CheckResult(
            'FAIL',
            'claude CLI not found on PATH',
            remediation="Install Claude Code and ensure it is available as 'claude' on your PATH.",
        )
    return CheckResult('PASS', f'claude CLI found at {path}')


# ---------------------------------------------------------------------------
# Config checks
# ---------------------------------------------------------------------------


def check_config_file(config_path: str) -> CheckResult:
    """Check whether the config file exists and contains valid TOML."""
    if not os.path.isfile(config_path):
        return CheckResult(
            'WARN',
            f'Config file not found at {config_path}',
            remediation="Run 'towit setup --config' to generate a starter config. Defaults apply until then.",
        )
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
    return CheckResult('PASS', 'TOWIT_DB_PATH not set')


# ---------------------------------------------------------------------------
# Database checks
# ---------------------------------------------------------------------------

_REQUIRED_TABLES = {
    'conversations', 'topics', 'conversation_topics',
    'keywords', 'conversation_keywords',
}


def _connect_ro(db_path: str) -> sqlite3.Connection:
    """Open a read-only raw connection (doctor must work on a broken DB and never alter it)."""
    return sqlite3.connect(f'file:{quote(db_path)}?mode=ro', uri=True, timeout=5.0)


_ARCHIVE_TABLES = ('messages', 'messages_fts')


def check_db_exists(db_path: str) -> CheckResult:
    if not os.path.isfile(db_path):
        return CheckResult(
            'FAIL',
            f'Database not found at {db_path}',
            remediation="Run 'towit setup' to initialize the database.",
        )
    return CheckResult('PASS', f'Database found at {db_path}')


def check_db_permissions(db_path: str) -> CheckResult:
    try:
        mode = os.stat(db_path).st_mode & 0o777
    except OSError:
        return CheckResult('WARN', f'Could not read permissions for {db_path}')
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
    try:
        mode = os.stat(db_dir).st_mode & 0o777
    except OSError:
        return CheckResult('WARN', f'Could not read permissions for {db_dir}')
    if mode != 0o700:
        octal = oct(mode)[2:]
        return CheckResult(
            'WARN',
            f'Database directory permissions are {octal} (expected 700): {db_dir}',
            remediation=f"Run 'chmod 700 {db_dir}' to restrict access.",
        )
    return CheckResult('PASS', f'Database directory permissions are 700: {db_dir}')


def check_db_tables(db_path: str) -> CheckResult:
    try:
        conn = _connect_ro(db_path)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        finally:
            conn.close()
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
    issues = []
    try:
        conn = _connect_ro(db_path)
        try:
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
            for name in _ARCHIVE_TABLES:
                if name not in tables:
                    issues.append(f'{name} table missing')
        finally:
            conn.close()
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


def check_fts5_available() -> CheckResult:
    """Check that this SQLite build has FTS5 (needed for archive search)."""
    try:
        conn = sqlite3.connect(':memory:')
        try:
            conn.execute("CREATE VIRTUAL TABLE fts5_probe USING fts5(x)")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return CheckResult(
            'FAIL',
            f'SQLite FTS5 is not available: {exc}',
            remediation="Use a Python/SQLite build compiled with FTS5 (e.g. Homebrew python3). Archive search needs it.",
        )
    return CheckResult('PASS', 'SQLite FTS5 is available')


_INTEGRITY_TIMEOUT = 5.0


def _is_corruption(exc: sqlite3.Error) -> bool:
    name = getattr(exc, 'sqlite_errorname', '') or ''
    return name.startswith('SQLITE_CORRUPT') or 'malformed' in str(exc).lower()


def _fts_integrity_check(db_path: str) -> None:
    """Run the FTS5 integrity-check; raises sqlite3.Error if the index is inconsistent.

    rank=1 also compares the index with the external content table. The check is an
    INSERT command, which SQLite refuses on a read-only handle, so
    it runs on a rw handle inside a transaction that is always rolled back.
    """
    conn = sqlite3.connect(f'file:{quote(db_path)}?mode=rw', uri=True, timeout=_INTEGRITY_TIMEOUT)
    try:
        conn.execute("BEGIN")
        try:
            conn.execute("INSERT INTO messages_fts(messages_fts, rank) VALUES('integrity-check', 1)")
        finally:
            conn.rollback()
    finally:
        conn.close()


def check_archive_schema(db_path: str) -> CheckResult:
    """Check archive tables exist, user_version is current, and the FTS index is consistent."""
    try:
        conn = _connect_ro(db_path)
        try:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()}
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return CheckResult('WARN', f'Could not verify archive schema: {exc}',
                           remediation="Run 'towit setup' to apply migrations.")
    missing = [t for t in _ARCHIVE_TABLES if t not in tables]
    if missing:
        return CheckResult(
            'WARN',
            f'Archive tables missing: {", ".join(missing)}',
            remediation="Run 'towit setup' to apply pending schema migrations.",
        )
    if version < SCHEMA_VERSION:
        return CheckResult(
            'WARN',
            f'Schema user_version is {version}, expected {SCHEMA_VERSION}',
            remediation="Run 'towit setup' to apply pending schema migrations.",
        )
    try:
        _fts_integrity_check(db_path)
    except sqlite3.Error as exc:
        if not _is_corruption(exc):
            # busy/locked (live writer), read-only file, cannot open...: not evidence of damage
            return CheckResult(
                'WARN',
                f'Could not run FTS integrity check: {exc}',
                remediation='Retry later, or check that the database is writable and not in use.',
            )
        return CheckResult(
            'FAIL',
            f'FTS index integrity check failed: {exc}',
            remediation="Rebuild the index: sqlite3 <db> \"INSERT INTO messages_fts(messages_fts) VALUES('rebuild')\"",
        )
    return CheckResult('PASS', f'Archive schema current (version {version}) and FTS index consistent')


# ---------------------------------------------------------------------------
# Hook checks (Stop, SessionEnd, SessionStart)
# ---------------------------------------------------------------------------

_HOOK_MARKER = 'towit_hook.py'


def _load_settings(settings_path: str) -> dict:
    try:
        with open(settings_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_hook_commands(settings_path: str) -> dict:
    """Return {event: first towit hook command} for each event where our hook is registered."""
    hooks = _load_settings(settings_path).get('hooks', {})
    if not isinstance(hooks, dict):
        return {}
    found = {}
    for event in HOOK_EVENTS:
        entries = hooks.get(event, [])
        for entry in entries if isinstance(entries, list) else []:
            inner = entry.get('hooks', []) if isinstance(entry, dict) else []
            for hook in inner if isinstance(inner, list) else []:
                cmd = hook.get('command', '') if isinstance(hook, dict) else ''
                if isinstance(cmd, str) and _HOOK_MARKER in cmd:
                    found.setdefault(event, cmd)
    return found


def _tokens(command: str) -> list[str]:
    """Split a hook command shell-style; fall back to whitespace on an unbalanced quote."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _script_path(command: str) -> str | None:
    # Command form: "python3 /abs/path/to/towit_hook.py", each path shell-quoted when it has
    # special characters (e.g. "'/my dir/python' '/my dir/towit_hook.py'")
    return next((p for p in _tokens(command) if _HOOK_MARKER in p), None)


def check_hook_settings_file(settings_path: str) -> CheckResult:
    if not os.path.isfile(settings_path):
        return CheckResult(
            'WARN',
            f'Claude Code settings not found at {settings_path}',
            remediation='Install Claude Code or run it once to create settings.json.',
        )
    return CheckResult('PASS', f'Claude Code settings found at {settings_path}')


def check_hook_installed(settings_path: str) -> CheckResult:
    """FAIL when no To Wit hook is registered for any event (partial installs: check_hook_events)."""
    if not os.path.isfile(settings_path):
        return CheckResult('WARN', 'Cannot check hooks — settings file absent (see above)')
    found = _find_hook_commands(settings_path)
    if not found:
        return CheckResult(
            'FAIL',
            f'To Wit hooks not found in {settings_path}',
            remediation="Run 'towit install-hook' to register the hooks.",
        )
    return CheckResult('PASS', f'To Wit hooks installed for: {", ".join(found)}')


def check_hook_events(settings_path: str) -> CheckResult:
    """WARN naming each of Stop, SessionEnd, SessionStart not registered with the towit hook."""
    found = _find_hook_commands(settings_path)
    missing = [ev for ev in HOOK_EVENTS if ev not in found]
    if missing:
        return CheckResult(
            'WARN',
            f'To Wit hook not registered for: {", ".join(missing)}',
            remediation="Run 'towit install-hook' to register the missing hooks. "
                        "Without them sessions are only archived when Stop fires.",
        )
    return CheckResult('PASS', f'To Wit hook registered for all events: {", ".join(HOOK_EVENTS)}')


def _interpreter(command: str) -> str | None:
    """First token of a hook command when it is an absolute path (bare names are PATH-resolved)."""
    tokens = _tokens(command)
    return tokens[0] if tokens and os.path.isabs(tokens[0]) else None


def _interpreter_unrunnable(interp: str | None) -> bool:
    return interp is not None and not (os.path.isfile(interp) and os.access(interp, os.X_OK))


def check_hook_commands(settings_path: str) -> CheckResult:
    """FAIL when no registered hook can run (script or absolute interpreter missing); WARN when only some can
    or events point at different scripts."""
    found = _find_hook_commands(settings_path)
    if not found:
        return CheckResult('PASS', 'No To Wit hook commands to verify')
    paths = {ev: _script_path(cmd) for ev, cmd in found.items()}
    interps = {ev: _interpreter(cmd) for ev, cmd in found.items()}
    no_script = [f'{ev} ({p})' for ev, p in paths.items() if p is None or not os.path.isfile(p)]
    no_interp = [f'{ev} ({i})' for ev, i in interps.items() if _interpreter_unrunnable(i)]
    broken = {ev for ev in found
              if paths[ev] is None or not os.path.isfile(paths[ev]) or _interpreter_unrunnable(interps[ev])}
    if broken:
        parts = []
        if no_script:
            parts.append(f'Hook script not found on disk for: {", ".join(no_script)}')
        if no_interp:
            parts.append(f'Hook interpreter not found or not executable for: {", ".join(no_interp)}')
        remediation = ("Reinstall To Wit to restore the hook script, then run 'towit install-hook'."
                       if no_script else
                       "Run 'towit install-hook' to rewrite the hook command with a working interpreter.")
        return CheckResult(
            'FAIL' if len(broken) == len(found) else 'WARN',  # FAIL: nothing can run, capture is dead
            '; '.join(parts),
            remediation=remediation,
        )
    distinct = sorted(set(paths.values()))
    if len(distinct) > 1:
        return CheckResult(
            'WARN',
            f'Hook events point at different towit_hook.py scripts: {", ".join(distinct)}',
            remediation="Remove the stale hook entries from settings.json, then run 'towit install-hook'.",
        )
    return CheckResult('PASS', f'Hook script exists at {distinct[0]}')


def check_hooks_not_disabled(settings_path: str) -> CheckResult:
    """WARN when Claude Code's disableAllHooks is true (no hook, so no archiving, will fire)."""
    if _load_settings(settings_path).get('disableAllHooks') is True:
        return CheckResult(
            'WARN',
            'disableAllHooks is true in Claude Code settings; To Wit hooks will not run',
            remediation='Set "disableAllHooks" to false (or remove it) in settings.json.',
        )
    return CheckResult('PASS', 'Hooks are not globally disabled')


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
    from towit_install_hook import SETTINGS_PATH

    config_path = os.environ.get('TOWIT_CONFIG_PATH', CONFIG_PATH)
    settings_path = os.environ.get('TOWIT_SETTINGS_PATH', SETTINGS_PATH)

    cfg = Config(config_path)
    db_path = cfg.db_path

    results = []

    # --- Python & tooling ---
    results.append(check_towit_version())
    results.append(check_python_version())
    results.append(check_claude_cli())

    # --- Configuration ---
    config_result = check_config_file(config_path)
    results.append(config_result)
    if config_result.status != 'FAIL':
        results.append(check_config_unknown_keys(config_path))
    results.append(check_deprecated_env())

    # --- Database ---
    results.append(check_db_exists(db_path))
    if os.path.isfile(db_path):
        results.append(check_db_permissions(db_path))
        results.append(check_db_dir_permissions(db_path))
        db_tables_result = check_db_tables(db_path)
        results.append(db_tables_result)
        if db_tables_result.status != 'FAIL':
            results.append(check_db_schema(db_path))

    results.append(check_fts5_available())
    if os.path.isfile(db_path):
        results.append(check_archive_schema(db_path))

    # --- Hooks ---
    results.append(check_hook_settings_file(settings_path))
    hook_result = check_hook_installed(settings_path)
    results.append(hook_result)
    if os.path.isfile(settings_path):
        if hook_result.status == 'PASS':
            results.append(check_hook_events(settings_path))
            results.append(check_hook_commands(settings_path))
        results.append(check_hooks_not_disabled(settings_path))

    # --- Print results ---
    for result in results:
        for line in format_result(result):
            print(line)

    summary, code = summarise(results)
    print()
    print(summary)
    sys.exit(code)


if __name__ == '__main__':
    run_cli(main)
