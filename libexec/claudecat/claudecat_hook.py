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

# Guard against recursive calls triggered by claudecat's own Claude invocations
if os.environ.get('CLAUDECAT_INDEXING'):
    sys.exit(0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_index import index_conversation


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
            jsonl_path = transcript_path
        elif session_id and cwd:
            # Derive path from cwd encoding
            encoded = cwd.replace('/', '-').lstrip('-')
            folder = os.path.expanduser(f'~/.claude/projects/-{encoded}')
            jsonl_path = os.path.join(folder, f'{session_id}.jsonl')
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
        pass  # Never interrupt Claude Code

    sys.exit(0)


if __name__ == '__main__':
    main()
