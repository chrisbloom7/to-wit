#!/usr/bin/env python3
"""
towit_doctor — Verify that To Wit's setup is complete and correct.

Prints a plain-text health report and exits 0 if all checks pass (or only
warnings), 1 if any check fails.  Never performs automatic remediation.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import tomllib
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_config import _KNOWN_KEYS


@dataclass
class CheckResult:
    status: str          # 'PASS', 'WARN', or 'FAIL'
    label: str           # one-line description shown after the status tag
    remediation: str = ''  # shown indented below for WARN/FAIL


def format_result(result: CheckResult) -> list:
    """Return a list of output lines for one CheckResult."""
    lines = [f'[{result.status}] {result.label}']
    if result.remediation and result.status in ('WARN', 'FAIL'):
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
        conn = sqlite3.connect(db_path, timeout=5.0)
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
        conn = sqlite3.connect(db_path, timeout=5.0)
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
