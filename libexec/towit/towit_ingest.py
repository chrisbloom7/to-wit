#!/usr/bin/env python3
"""
towit_ingest.py — Parse Claude Code transcripts into archive messages.

Unlike towit_index.parse_jsonl (which keeps only prose for LLM analysis), this
keeps one-line stubs for tool calls and failed tool results so the archive is
searchable by what was run, not just what was said.
"""

import fnmatch
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field

from towit_config import (config, get_error_logger, is_valid_session_id,
                          safe_subprocess_env, validate_jsonl_path)
from towit_db import Database
from towit_index import index_conversation
from towit_redact import redact

MAX_MESSAGE_CHARS = 50_000
CATCH_UP_SLACK_SECONDS = 60
CATCH_UP_META_KEY = 'last_catch_up'
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
        # Missing/unreadable transcript: never raise (called from the hooks).
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


def _sanitize(text: str) -> str:
    """Replace characters SQLite cannot encode (e.g. lone surrogates) with '?'."""
    return text.encode('utf-8', 'replace').decode('utf-8')


def should_skip_path(jsonl_path: str) -> bool:
    """True if config/path rules exclude this transcript (symlink, subagent, folder filter)."""
    if os.path.islink(jsonl_path):
        return True
    path = os.path.abspath(jsonl_path)
    if '/subagents/' in path and not config.ingest_include_subagents:
        return True
    folder = os.path.dirname(path)
    folders = config.ingest_folders
    return bool(folders) and not any(fnmatch.fnmatch(folder, pat) for pat in folders)


def ingest_transcript(jsonl_path: str, db: Database | None = None) -> str:
    """Archive one transcript. Never raises for bad input; DB errors propagate.

    Returns 'ingested' | 'appended' | 'rewritten' | 'unchanged' | 'skipped' | 'forgotten'.
    """
    if should_skip_path(jsonl_path):
        return 'skipped'
    path = os.path.abspath(jsonl_path)
    folder = os.path.dirname(path)

    session_id = os.path.splitext(os.path.basename(path))[0]
    if not is_valid_session_id(session_id):
        return 'skipped'

    db = db or Database()
    if db.is_forgotten(session_id):
        return 'forgotten'

    parsed = parse_transcript(path)
    if sum(1 for m in parsed.messages if m.role == 'user') < 2:
        return 'skipped'

    extra = config.ingest_extra_patterns
    do_redact = config.ingest_redact
    messages = []
    for m in parsed.messages:
        text = redact(m.text, extra) if do_redact else m.text
        messages.append({'role': m.role, 'ts': m.ts, 'text': _sanitize(text)})

    conv = {
        'id': session_id,
        'folder': folder,
        'cwd': _sanitize(parsed.cwd),
        'started_at': parsed.started_at,
        'last_active': parsed.last_active,
        # Resolved once: a stored key is kept (the upsert also keeps it), so git runs only
        # for new sessions or ones whose key was never set.
        'repo_key': db.get_repo_key(session_id) or _sanitize(resolve_repo_key(parsed.cwd)),
        'source_path': path,
    }
    return db.archive_session(conv, messages)


def catch_up(root: str | None = None, db: Database | None = None) -> dict[str, int]:
    """Archive transcripts modified since the last catch-up scan (all, if never run).

    Scans `root` (default ~/.claude/projects) for *.jsonl files with an mtime newer than
    the `last_catch_up` stamp minus a 60 s slack. Never calls the LLM. Returns counts
    keyed by ingest_transcript status, plus 'error' for files that raised. The stamp is
    the scan start time, written only once the scan completes. A missing DB (SystemExit)
    propagates: it is a global failure, not a per-file one.
    """
    root = root or os.path.expanduser('~/.claude/projects')
    db = db or Database()
    started = datetime.now(timezone.utc)
    stamp = db.get_meta(CATCH_UP_META_KEY)
    cutoff = None
    if stamp:
        try:
            cutoff = datetime.fromisoformat(stamp).timestamp() - CATCH_UP_SLACK_SECONDS
        except ValueError:
            cutoff = None  # corrupt stamp: rescan everything

    counts: dict[str, int] = {}
    for dirpath, _dirs, files in os.walk(root):  # os.walk does not follow symlinked dirs
        for name in files:
            if not name.endswith('.jsonl'):
                continue
            path = os.path.join(dirpath, name)
            if should_skip_path(path):
                continue
            try:
                if cutoff is not None and os.stat(path).st_mtime < cutoff:
                    continue
                status = ingest_transcript(path, db)
            except SystemExit:
                raise
            except Exception:
                status = 'error'
                try:
                    get_error_logger().exception("towit catch-up error: %s", path)
                except Exception:
                    pass
            counts[status] = counts.get(status, 0) + 1

    db.set_meta(CATCH_UP_META_KEY, started.isoformat())
    return counts


def main():
    """Detached entry point spawned by the hook: archive, then index (or `--catch-up`).

    Never raises or exits non-zero; failures are logged to ~/.towit/errors.log.
    """
    if os.environ.get('TOWIT_INDEXING'):
        return  # recursive call from towit's own Claude invocation
    if len(sys.argv) < 2:
        return
    try:
        if sys.argv[1] == '--catch-up':
            catch_up()
            return
        jsonl_path = validate_jsonl_path(sys.argv[1])
        if jsonl_path is None:
            get_error_logger().error("towit ingest: path outside ~/.claude/projects: %s",
                                     sys.argv[1])
            return
        status = ingest_transcript(jsonl_path)
        if status in ('forgotten', 'skipped') or not config.indexing_enabled:
            return
        if '/subagents/' in jsonl_path:
            return  # archived only: subagent sessions stay out of the LLM-indexed catalog
        index_conversation(jsonl_path)
    except (Exception, SystemExit):
        # SystemExit: Database.validate() exits when the DB is missing.
        try:
            get_error_logger().exception("towit ingest error")
        except Exception:
            pass


if __name__ == '__main__':
    main()
