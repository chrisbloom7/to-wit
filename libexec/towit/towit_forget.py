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
from towit_config import is_valid_session_id
from towit_db import Database
from towit_sanitize import sanitize_cell


MAX_LISTED_KEYS = 10


def main():
    parser = argparse.ArgumentParser(
        description='Permanently delete conversations from the To Wit catalog and archive.'
    )
    parser.add_argument('session_id', nargs='?', help='Session ID to forget')
    parser.add_argument('--repo', help='Forget every conversation in this repo (its key, its directory name, '
                        'or a worktree directory named NAME.<branch>); lists the matched keys before deleting')
    parser.add_argument('--folder', help='Forget every conversation whose working directory is exactly this path')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    selectors = [s for s in (args.session_id, args.repo, args.folder) if s is not None]
    if len(selectors) != 1:
        parser.error('exactly one of <session-id>, --repo or --folder is required')

    if args.session_id is not None and not is_valid_session_id(args.session_id):
        print(f"Error: invalid session id '{args.session_id}'.", file=sys.stderr)
        sys.exit(1)

    db = Database()
    db.validate()

    subagents = []
    if args.session_id is not None:
        subagents = db.subagent_ids_for_session(args.session_id)
        parent_exists = db.get_conversation(args.session_id) is not None
        if not parent_exists and not subagents:
            if db.is_forgotten(args.session_id):
                # Retry path for an earlier forget whose physical cleanup was incomplete.
                warning = db.purge_free_space(args.session_id)
                print("Already forgotten; re-ran physical cleanup.")
                if warning:
                    print(f"Warning: {warning}", file=sys.stderr)
                return
            print(f"Error: conversation '{args.session_id}' not found.", file=sys.stderr)
            sys.exit(1)
        # A session's subagent conversations hold its tool output and prompts, so they go too.
        ids = ([args.session_id] if parent_exists else []) + subagents
    else:
        ids = db.conversation_ids_for_scope(repo=args.repo, folder=args.folder)
        if not ids:
            print("Error: no conversations match.", file=sys.stderr)
            sys.exit(1)

    if args.repo is not None:
        repos = db.repo_count_for_scope(repo=args.repo)
        prompt = (f"Delete {len(ids)} conversation(s) across {repos} repo(s) "
                  f"matching '{sanitize_cell(args.repo)}'? [y/N] ")
    else:
        prompt = f"Delete {len(ids)} conversation(s)? [y/N] "

    if args.repo is not None:
        # A name also matches worktree keys such as <name>.<branch>; show what matched,
        # even with --yes, before anything is deleted.
        keys = db.repo_keys_for_scope(repo=args.repo)
        print("Matched repo keys:")
        for key in keys[:MAX_LISTED_KEYS]:
            print(f"  {sanitize_cell(key)}")
        if len(keys) > MAX_LISTED_KEYS:
            print(f"  +{len(keys) - MAX_LISTED_KEYS} more")

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
    extra = f", including {len(subagents)} subagent conversation(s)" if subagents else ""
    print(f"Forgot {count} conversation(s){extra}.")
    if db.cleanup_warning:
        print(f"Warning: {db.cleanup_warning}", file=sys.stderr)


if __name__ == '__main__':
    main()
