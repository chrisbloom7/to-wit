#!/usr/bin/env python3
"""
claudecat_index — Core indexing logic for the claudecat catalog.

Can be used as a module (imported by backfill and hook) or run standalone:
    python3 claudecat_index.py <path/to/session.jsonl>
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_db import Database, DB_PATH


# ---------------------------------------------------------------------------
# parse_jsonl
# ---------------------------------------------------------------------------

def parse_jsonl(path: str) -> list:
    """
    Read a JSONL transcript and return a flat list of message dicts:
        {'role': str, 'content': str, 'timestamp': str,
         'session_id': str, 'cwd': str}

    Skips: tool_use, tool_result, thinking, file-history-snapshot content.
    For assistant messages: only includes type='text' content items.
    """
    messages = []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get('type', '')
                if entry_type not in ('user', 'assistant'):
                    continue

                msg = entry.get('message', {})
                role = msg.get('role', entry_type)
                if role not in ('user', 'assistant'):
                    continue

                timestamp = entry.get('timestamp', '')
                session_id = entry.get('sessionId', '')
                cwd = entry.get('cwd', '')

                content = msg.get('content', '')
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = []
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get('type', '')
                        if item_type in ('tool_use', 'tool_result', 'thinking',
                                         'file-history-snapshot'):
                            continue
                        if item_type == 'text':
                            parts.append(item.get('text', ''))
                    text = '\n'.join(parts)
                else:
                    continue

                text = text.strip()
                if not text:
                    continue

                messages.append({
                    'role':       role,
                    'content':    text,
                    'timestamp':  timestamp,
                    'session_id': session_id,
                    'cwd':        cwd,
                })

    except OSError as exc:
        print(f"Error reading {path}: {exc}", file=sys.stderr)

    return messages


# ---------------------------------------------------------------------------
# should_index
# ---------------------------------------------------------------------------

def should_index(messages: list) -> bool:
    """
    Pre-flight filter: return False if the conversation is not worth indexing.
    Conditions for False:
      - Fewer than 2 messages with role='user'
      - Average length of user messages is < 20 chars
    """
    user_msgs = [m for m in messages if m['role'] == 'user']
    if len(user_msgs) < 2:
        return False
    avg_len = sum(len(m['content']) for m in user_msgs) / len(user_msgs)
    if avg_len < 20:
        return False
    return True


# ---------------------------------------------------------------------------
# build_transcript
# ---------------------------------------------------------------------------

def build_transcript(messages: list, max_chars: int = 8000) -> str:
    """
    Format messages as 'Human: ...\n\nAssistant: ...\n\n...'
    Truncates to max_chars, keeping first 30% and last 70% with an omission marker.
    """
    parts = []
    for m in messages:
        label = 'Human' if m['role'] == 'user' else 'Assistant'
        parts.append(f"{label}: {m['content']}")

    full = '\n\n'.join(parts)

    if len(full) <= max_chars:
        return full

    first_chars = int(max_chars * 0.30)
    last_chars = int(max_chars * 0.70)
    omitted = len(full) - first_chars - last_chars
    return (
        full[:first_chars]
        + f'\n\n[... {omitted} chars omitted ...]\n\n'
        + full[len(full) - last_chars:]
    )


# ---------------------------------------------------------------------------
# analyze_with_claude
# ---------------------------------------------------------------------------

_ANALYSIS_PROMPT_TEMPLATE = """\
Analyze the following Claude conversation transcript and return a JSON object with these fields:

- "title": A concise, descriptive title for the conversation (max 80 chars)
- "summary": A 2-4 sentence summary of what was discussed and accomplished
- "topics": A list of 1-5 short topic tags (e.g. ["python", "refactoring", "git"])
- "skip": false (set to true only if this is a trivial/test/empty conversation not worth cataloging)

Return ONLY the JSON object, no other text.

Transcript:
{transcript}"""


def analyze_with_claude(transcript: str) -> dict:
    """
    Call Claude to produce a title, summary, and topics for a conversation.
    Returns a dict with keys: title, summary, topics, skip.
    On any error returns {'skip': True}.
    """
    prompt = _ANALYSIS_PROMPT_TEMPLATE.format(transcript=transcript)

    # Pass an explicit allowlist rather than the full environment to avoid
    # leaking unrelated credentials (AWS keys, DB passwords, etc.) to the
    # claude subprocess. Prefix-based allowlist covers Claude/Anthropic vars
    # and the shell basics the CLI needs to locate binaries and config.
    _PASS_THROUGH_PREFIXES = (
        'HOME', 'PATH', 'USER', 'TMPDIR', 'TERM', 'LANG', 'LC_',
        'CLAUDE_', 'ANTHROPIC_',
    )
    safe_env = {
        k: v for k, v in os.environ.items()
        if any(k.startswith(p) for p in _PASS_THROUGH_PREFIXES)
    }
    safe_env['CLAUDECAT_INDEXING'] = '1'

    try:
        result = subprocess.run(
            ['claude', '-p', prompt, '--output-format', 'text'],
            capture_output=True, text=True, timeout=60,
            env=safe_env,
        )
    except subprocess.TimeoutExpired:
        return {'skip': True}

    if result.returncode != 0:
        return {'skip': True}

    output = result.stdout.strip()

    # Try direct parse first, then regex fallback
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


# ---------------------------------------------------------------------------
# index_conversation
# ---------------------------------------------------------------------------

def index_conversation(jsonl_path: str, db_path: str = None, force: bool = False):
    """
    Index a single JSONL transcript file into the catalog database.

    Returns a dict with 'status' key:
        {'status': 'already_indexed'}
        {'status': 'skipped', 'reason': 'pre-filter' | 'claude_filter'}
        {'status': 'indexed', 'title': ..., 'topics': [...]}
    Returns None on unrecoverable error.
    """
    session_id = os.path.splitext(os.path.basename(jsonl_path))[0]

    if isinstance(db_path, Database):
        db = db_path
    else:
        db = Database(db_path or DB_PATH)

    if not force:
        try:
            if db.is_indexed(session_id):
                return 'already_indexed'
        except SystemExit:
            # DB not yet initialized — skip check
            pass

    messages = parse_jsonl(jsonl_path)

    if not should_index(messages):
        return 'skipped'

    transcript = build_transcript(messages)
    analysis = analyze_with_claude(transcript)

    if analysis.get('skip'):
        return 'skipped'

    # Extract metadata from first message
    first = messages[0] if messages else {}
    cwd = first.get('cwd', '')
    timestamps = [m['timestamp'] for m in messages if m.get('timestamp')]
    started_at = timestamps[0] if timestamps else None
    last_active = timestamps[-1] if timestamps else None
    folder = str(os.path.dirname(os.path.abspath(jsonl_path)))

    data = {
        'id':          session_id,
        'folder':      folder,
        'cwd':         cwd,
        'started_at':  started_at,
        'last_active': last_active,
        'title':       analysis.get('title', ''),
        'summary':     analysis.get('summary', ''),
        'topics':      analysis.get('topics', []),
    }

    db.upsert_conversation(data)

    return 'indexed'


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path/to/session.jsonl>", file=sys.stderr)
        sys.exit(1)

    result = index_conversation(sys.argv[1])
    print(json.dumps(result, indent=2))
