#!/usr/bin/env python3
"""
towit_resume — Resume a cataloged Claude conversation.

Usage:
    python3 towit_resume.py [--force] <session-id>

Changes to the conversation's working directory and resumes the session with
`claude --resume <session-id>`, replacing the current process.

If the working directory no longer exists but the transcript is intact, use
--force to recreate it and resume.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_db import Database


def jsonl_path(conv):
    return os.path.join(conv['folder'], f"{conv['id']}.jsonl")


def main():
    parser = argparse.ArgumentParser(
        description='Resume a cataloged Claude conversation.'
    )
    parser.add_argument('session_id', metavar='SESSION_ID',
                        help='Session ID to resume')
    parser.add_argument('--force', action='store_true',
                        help='Recreate missing working directory and resume')
    args = parser.parse_args()

    db = Database()
    db.validate()

    conv = db.get_conversation(args.session_id)
    if not conv:
        print(f"Error: session not found: {args.session_id}", file=sys.stderr)
        sys.exit(1)

    cwd = conv.get('cwd')
    if cwd and not os.path.isdir(cwd):
        transcript = jsonl_path(conv)
        if not os.path.isfile(transcript):
            print(
                f"Error: working directory and transcript are both gone.\n"
                f"  Directory:  {cwd}\n"
                f"  Transcript: {transcript}\n"
                f"This session is no longer resumable.",
                file=sys.stderr
            )
            sys.exit(1)

        if not args.force:
            print(
                f"Error: working directory no longer exists: {cwd}\n"
                f"\n"
                f"The transcript is intact. If the directory was renamed or moved,\n"
                f"cd there and run:\n"
                f"  claude --resume {args.session_id}\n"
                f"\n"
                f"To recreate the original directory and resume:\n"
                f"  towit resume --force {args.session_id}",
                file=sys.stderr
            )
            sys.exit(1)

        os.makedirs(cwd, exist_ok=True)
        print(f"Warning: recreated missing directory: {cwd}", file=sys.stderr)

    if cwd:
        os.chdir(cwd)

    os.execvp('claude', ['claude', '--resume', args.session_id])


if __name__ == '__main__':
    main()
