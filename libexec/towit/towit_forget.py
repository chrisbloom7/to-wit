#!/usr/bin/env python3
"""
towit_forget — Permanently delete conversations from the catalog and archive.

Usage:
    python3 towit_forget.py <session-id> [--yes]
    python3 towit_forget.py --repo <path|name> [--yes]
    python3 towit_forget.py --folder <path> [--yes]

Exactly one selector is required. Deleted conversations lose their messages,
search index entries, topics and keywords; only the session id is kept (in a
tombstone table) so backfill and the hook never re-ingest them. Their transcripts
under ~/.claude/projects/ are not touched.
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_db import Database


def main():
    parser = argparse.ArgumentParser(
        description='Permanently delete conversations from the To Wit catalog and archive.'
    )
    parser.add_argument('session_id', nargs='?', help='Session ID to forget')
    parser.add_argument('--repo', help='Forget every conversation in this repo (path or name)')
    parser.add_argument('--folder', help='Forget every conversation whose working directory is exactly this path')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    selectors = [s for s in (args.session_id, args.repo, args.folder) if s is not None]
    if len(selectors) != 1:
        parser.error('exactly one of <session-id>, --repo or --folder is required')

    db = Database()
    db.validate()

    if args.session_id is not None:
        if db.get_conversation(args.session_id) is None:
            if db.is_forgotten(args.session_id):
                # Retry path for an earlier forget whose physical cleanup was incomplete.
                warning = db.purge_free_space(args.session_id)
                print("Already forgotten; re-ran physical cleanup.")
                if warning:
                    print(f"Warning: {warning}", file=sys.stderr)
                return
            print(f"Error: conversation '{args.session_id}' not found.", file=sys.stderr)
            sys.exit(1)
        ids = [args.session_id]
    else:
        ids = db.conversation_ids_for_scope(repo=args.repo, folder=args.folder)
        if not ids:
            print("Error: no conversations match.", file=sys.stderr)
            sys.exit(1)

    if args.repo is not None:
        repos = db.repo_count_for_scope(repo=args.repo)
        prompt = (f"Delete {len(ids)} conversation(s) across {repos} repo(s) "
                  f"matching '{args.repo}'? [y/N] ")
    else:
        prompt = f"Delete {len(ids)} conversation(s)? [y/N] "

    if not args.yes:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer not in ('y', 'yes'):
            print("Aborted.")
            sys.exit(1)

    try:
        count = db.forget_conversations(ids)
    except sqlite3.Error as exc:
        print(f"Error: could not forget ({exc}); nothing was deleted.", file=sys.stderr)
        sys.exit(1)
    print(f"Forgot {count} conversation(s).")
    if db.cleanup_warning:
        print(f"Warning: {db.cleanup_warning}", file=sys.stderr)


if __name__ == '__main__':
    main()
