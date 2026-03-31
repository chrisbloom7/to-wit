#!/usr/bin/env python3
"""
claudecat_open — Resume a cataloged Claude conversation.

Usage:
    python3 claudecat_open.py <session-id>

Changes to the conversation's working directory and resumes the session with
`claude --resume <session-id>`, replacing the current process.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_db import Database


def main():
    parser = argparse.ArgumentParser(
        description='Resume a cataloged Claude conversation.'
    )
    parser.add_argument('session_id', metavar='SESSION_ID',
                        help='Session ID to resume')
    args = parser.parse_args()

    db = Database()
    db.validate()

    conv = db.get_conversation(args.session_id)
    if not conv:
        print(f"Error: session not found: {args.session_id}", file=sys.stderr)
        sys.exit(1)

    cwd = conv.get('cwd')
    if cwd:
        if not os.path.isdir(cwd):
            print(f"Error: working directory no longer exists: {cwd}", file=sys.stderr)
            sys.exit(1)
        os.chdir(cwd)

    os.execvp('claude', ['claude', '--resume', args.session_id])


if __name__ == '__main__':
    main()
