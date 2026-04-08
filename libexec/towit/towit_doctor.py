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
    import shutil
    path = shutil.which('claude')
    if path is None:
        return CheckResult(
            'FAIL',
            'claude CLI not found on PATH',
            remediation="Install Claude Code and ensure it is available as 'claude' on your PATH.",
        )
    return CheckResult('PASS', f'claude CLI found at {path}')
