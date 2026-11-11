#!/usr/bin/env python3
"""
towit_ingest.py — Parse Claude Code transcripts into archive messages.

Unlike towit_index.parse_jsonl (which keeps only prose for LLM analysis), this
keeps one-line stubs for tool calls and failed tool results so the archive is
searchable by what was run, not just what was said.
"""

import json
import os
import subprocess
from dataclasses import dataclass, field

from towit_config import safe_subprocess_env

MAX_MESSAGE_CHARS = 50_000
STUB_VALUE_CHARS = 200
ERROR_RESULT_CHARS = 300
STUB_VALUE_KEYS = ('description', 'command', 'file_path', 'pattern',
                   'query', 'url', 'skill', 'path')


@dataclass
class ArchiveMessage:
    role: str
    ts: str | None
    text: str


@dataclass
class ParsedTranscript:
    session_id: str
    cwd: str
    started_at: str | None
    last_active: str | None
    messages: list[ArchiveMessage] = field(default_factory=list)


def _tool_stub(item: dict) -> str:
    """Build '[<ToolName>] <value>' from a tool_use item."""
    name = item.get('name') or 'tool'
    tool_input = item.get('input')
    value = ''
    if isinstance(tool_input, dict):
        for key in STUB_VALUE_KEYS:
            candidate = tool_input.get(key)
            if isinstance(candidate, str) and candidate.strip():
                value = candidate
                break
    return f'[{name}] {value[:STUB_VALUE_CHARS]}'.rstrip()


def _error_text(item: dict) -> str:
    """Return '[error] <first 300 chars>' for a failed tool_result."""
    content = item.get('content', '')
    if isinstance(content, list):
        content = '\n'.join(
            c.get('text', '') for c in content
            if isinstance(c, dict) and c.get('type') == 'text'
            and isinstance(c.get('text'), str)
        )
    elif not isinstance(content, str):
        content = ''
    return '[error] ' + content[:ERROR_RESULT_CHARS]


def _truncate(text: str) -> str:
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    dropped = len(text) - MAX_MESSAGE_CHARS
    return f'{text[:MAX_MESSAGE_CHARS]}\n[... {dropped} chars truncated ...]'


def _entry_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ''
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get('type', '')
        if item_type == 'text':
            text = item.get('text', '')
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        elif item_type == 'tool_use':
            parts.append(_tool_stub(item))
        elif item_type == 'tool_result' and item.get('is_error'):
            parts.append(_error_text(item))
    return '\n'.join(parts)


def parse_transcript(path: str) -> ParsedTranscript:
    """Parse a JSONL transcript into ArchiveMessages (no redaction applied)."""
    session_id = os.path.basename(path)
    if session_id.endswith('.jsonl'):
        session_id = session_id[:-len('.jsonl')]

    cwd = ''
    messages: list[ArchiveMessage] = []
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # e.g. partial last line from a transcript mid-write
                if not isinstance(entry, dict):
                    continue

                if not cwd and isinstance(entry.get('cwd'), str):
                    cwd = entry['cwd']

                entry_type = entry.get('type', '')
                if entry_type not in ('user', 'assistant'):
                    continue
                msg = entry.get('message')
                if not isinstance(msg, dict):
                    continue
                role = msg.get('role', entry_type)
                if role not in ('user', 'assistant'):
                    continue

                text = _entry_text(msg.get('content', ''))
                if not text:
                    continue
                ts = entry.get('timestamp') or None
                messages.append(ArchiveMessage(role=role, ts=ts, text=_truncate(text)))
    except OSError:
        # Missing/unreadable transcript: never raise (called from the stop hook).
        return ParsedTranscript(session_id=session_id, cwd='', started_at=None,
                                last_active=None, messages=[])

    stamps = [m.ts for m in messages if m.ts]
    return ParsedTranscript(
        session_id=session_id,
        cwd=cwd,
        started_at=stamps[0] if stamps else None,
        last_active=stamps[-1] if stamps else None,
        messages=messages,
    )


def resolve_repo_key(cwd: str) -> str:
    """Return the repo root that groups all worktrees of a repo, else `cwd`.

    Uses the git common dir, so linked worktrees map to the main repo. Never raises.
    """
    if not cwd or not os.path.isdir(cwd):
        return cwd
    try:
        result = subprocess.run(
            ['git', '-C', cwd, 'rev-parse', '--git-common-dir'],
            capture_output=True, text=True, timeout=5,
            env=safe_subprocess_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return cwd
    common = result.stdout.strip() if result.returncode == 0 else ''
    if not common:
        return cwd
    common = os.path.realpath(os.path.join(cwd, common))  # join keeps absolute paths as-is
    if os.path.basename(common) == '.git':
        return os.path.dirname(common)
    return common
