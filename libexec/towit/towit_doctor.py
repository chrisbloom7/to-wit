#!/usr/bin/env python3
"""
towit_doctor — Verify that To Wit's setup is complete and correct.

Prints a plain-text health report and exits 0 if all checks pass (or only
warnings), 1 if any check fails.  Never performs automatic remediation.
"""

import argparse
import os
import shutil
import sys
import tomllib
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
    return CheckResult('PASS', 'TOWIT_DB_PATH not set (not deprecated)')
