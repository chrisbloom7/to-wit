#!/usr/bin/env python3
"""
towit_hook — Claude Code stop hook.

Reads stdin JSON from Claude Code's hook mechanism and spawns towit_ingest.py
to archive and index the completed conversation into the To Wit catalog.

Always exits 0 to avoid interrupting Claude Code.
"""

import sys
import os
import json
import subprocess

# Guard against recursive calls triggered by towit's own Claude invocations.
# Must run before towit_config is imported (which reads the config file).
if os.environ.get('TOWIT_INDEXING'):
    sys.exit(0)

from towit_config import get_error_logger, is_valid_session_id, validate_jsonl_path


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
            jsonl_path = validate_jsonl_path(transcript_path)
            if jsonl_path is None:
                sys.exit(0)
        elif session_id and cwd:
            # Validate session_id format before using it in path construction
            if not is_valid_session_id(session_id):
                sys.exit(0)
            # Derive path from cwd encoding
            encoded = cwd.replace('/', '-').lstrip('-')
            folder = os.path.expanduser(f'~/.claude/projects/-{encoded}')
            jsonl_path = validate_jsonl_path(os.path.join(folder, f'{session_id}.jsonl'))
            if jsonl_path is None:
                sys.exit(0)
        else:
            sys.exit(0)

        if not os.path.exists(jsonl_path):
            sys.exit(0)

        # Skip subagent sessions — they are not interactive user conversations
        if '/subagents/' in jsonl_path:
            sys.exit(0)

        # Spawn archiving + indexing as a detached background process so the
        # stop hook exits immediately rather than blocking on the Claude API call.
        helpers_dir = os.path.dirname(os.path.abspath(__file__))
        subprocess.Popen(
            [sys.executable, os.path.join(helpers_dir, 'towit_ingest.py'), jsonl_path],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        try:
            get_error_logger().exception("towit hook error")
        except Exception:
            pass  # Never interrupt Claude Code

    sys.exit(0)


if __name__ == '__main__':
    main()
