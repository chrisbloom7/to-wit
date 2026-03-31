#!/usr/bin/env python3
"""
claudecat_hook — Claude Code stop hook.

Reads stdin JSON from Claude Code's hook mechanism and indexes the
completed conversation into the claudecat catalog.

Always exits 0 to avoid interrupting Claude Code.
"""

import sys
import os
import json
import re

# Guard against recursive calls triggered by claudecat's own Claude invocations
if os.environ.get('CLAUDECAT_INDEXING'):
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_index import index_conversation

_EXPECTED_ROOT = os.path.realpath(os.path.expanduser('~/.claude/projects'))
_SESSION_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{8,}$')


def _validate_jsonl_path(path):
    """Return realpath if it's under ~/.claude/projects/, else None."""
    resolved = os.path.realpath(path)
    if resolved.startswith(_EXPECTED_ROOT + os.sep):
        return resolved
    return None


def _get_error_logger():
    """Return a rotating logger that writes to ~/.claudecat/errors.log."""
    import logging
    import logging.handlers
    log_dir = os.path.expanduser('~/.claudecat')
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger('claudecat.hook')
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, 'errors.log'),
            maxBytes=100_000,
            backupCount=2,
        )
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
    return logger


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        data = json.loads(raw)

        session_id = data.get('session_id', '')
        transcript_path = data.get('transcript_path', '')
        cwd = data.get('cwd', '')

        if transcript_path and os.path.exists(transcript_path):
            jsonl_path = _validate_jsonl_path(transcript_path)
            if jsonl_path is None:
                sys.exit(0)
        elif session_id and cwd:
            # Validate session_id format before using it in path construction
            if not _SESSION_ID_RE.match(session_id):
                sys.exit(0)
            # Derive path from cwd encoding
            encoded = cwd.replace('/', '-').lstrip('-')
            folder = os.path.expanduser(f'~/.claude/projects/-{encoded}')
            jsonl_path = _validate_jsonl_path(os.path.join(folder, f'{session_id}.jsonl'))
            if jsonl_path is None:
                sys.exit(0)
        else:
            sys.exit(0)

        if not os.path.exists(jsonl_path):
            sys.exit(0)

        # Skip subagent sessions — they are not interactive user conversations
        if '/subagents/' in jsonl_path:
            sys.exit(0)

        result = index_conversation(jsonl_path)
        if result == 'indexed':
            print(f"claudecat: indexed session {session_id[:8]}...", file=sys.stderr)
    except Exception:
        try:
            _get_error_logger().exception("claudecat hook error")
        except Exception:
            pass  # Never interrupt Claude Code

    sys.exit(0)


if __name__ == '__main__':
    main()
