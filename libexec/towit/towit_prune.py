#!/usr/bin/env python3
"""
towit_prune — Remove catalog entries whose transcripts no longer exist.

Usage:
    python3 towit_prune.py [--archive] [--yes] [--dry-run]

Conversations whose JSONL transcript is missing from ~/.claude/projects/ cannot
be resumed or exported. By default this removes only metadata-only entries
(never archived). Archived conversations keep their searchable messages after
Claude Code deletes the transcript, so they are kept unless --archive is given.

Archived conversations whose whole project folder is gone are reported as
"likely removed by claude purge"; a manually deleted folder looks identical,
so this is a report, never an automatic deletion.

Conversations whose working directory is missing but transcript is intact are
left untouched — they can still be resumed with `towit open --force`.
"""

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_db import Database
from towit_pipe import run_cli


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def main():
    parser = argparse.ArgumentParser(
        description='Remove catalog entries whose transcripts no longer exist.'
    )
    parser.add_argument('--archive', action='store_true',
                        help='Also remove archived conversations (and their stored messages) '
                             'whose transcripts are missing, after confirmation')
    parser.add_argument('--yes', action='store_true',
                        help='Skip the --archive confirmation prompt')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be removed without deleting')
    args = parser.parse_args()

    db = Database()
    db.validate()

    stubs = db.all_conversation_stubs()
    if not stubs:
        print("No conversations in catalog.")
        return

    missing = [
        s for s in stubs
        if not os.path.isfile(os.path.join(s['folder'], f"{s['id']}.jsonl"))
    ]

    if not missing:
        print(f"All {len(stubs)} transcripts accounted for. Nothing to prune.")
        return

    removable = [s for s in missing if args.archive or not s['archived']]
    removable_ids = {s['id'] for s in removable}
    purged = [s for s in stubs
              if s['archived'] and not os.path.isdir(s['folder']) and s['id'] not in removable_ids]
    purged_ids = {s['id'] for s in purged}
    # a purged-folder row is listed in the purge section only, not twice
    kept = [s for s in missing if s['id'] not in removable_ids and s['id'] not in purged_ids]
    archived_removable = sum(1 for s in removable if s['archived'])

    if (removable and archived_removable and args.archive
            and not args.dry_run and not args.yes):
        print(f"{archived_removable} archived "
              f"{_plural(archived_removable, 'conversation', 'conversations')} "
              f"with missing transcripts will be removed, including their stored messages.")
        try:
            answer = input("Continue? [y/N] ")
        except EOFError:
            answer = ''
        if answer.strip().lower() not in ('y', 'yes'):
            print("Aborted. Nothing removed.")
            return

    if args.dry_run:
        for s in removable:
            transcript = os.path.join(s['folder'], f"{s['id']}.jsonl")
            print(f"  would remove: {s['id']}  (transcript: {transcript})")
    elif removable:
        # Archived rows get the same physical removal as `forget` (FTS merge, VACUUM, WAL
        # truncate) minus the tombstone, so a pruned session can be archived again if its
        # transcript returns. Metadata-only rows hold no message text: a plain delete is enough.
        try:
            for s in removable:
                if not s['archived']:
                    db.delete_conversation(s['id'])
            archived_ids = [s['id'] for s in removable if s['archived']]
            if archived_ids:
                db.forget_conversations(archived_ids, tombstone=False)
        except sqlite3.Error as exc:
            print(f"Error: could not prune ({exc}); some entries may not have been deleted.",
                  file=sys.stderr)
            sys.exit(1)
        for s in removable:
            print(f"  removed: {s['id']}")

    total = len(removable)
    if not removable:
        print("Nothing to prune.")
    elif args.dry_run:
        print(f"\nDry run: {total} of {len(stubs)} entr{'y' if total == 1 else 'ies'} would be pruned.")
    else:
        print(f"\nPruned {total} of {len(stubs)} entr{'y' if total == 1 else 'ies'}.")

    if db.cleanup_warning:
        print(f"Warning: {db.cleanup_warning}", file=sys.stderr)

    if kept:
        print(f"\nKept {len(kept)} archived "
              f"{_plural(len(kept), 'conversation', 'conversations')} with missing transcripts "
              f"(searchable archive; use --archive to remove):")
        for s in kept:
            print(f"  kept (archived): {s['id']}")

    # Report-only: a whole project folder missing usually means `claude purge`.
    if purged:
        print(f"\nLikely removed by claude purge: {len(purged)} archived conversations "
              f"whose project folder no longer exists")
        for s in purged:
            print(f"  {s['id']}  (cwd: {s['cwd']})")
        print("  (kept; a manually deleted folder looks identical. "
              "Use --archive to remove them, or `towit forget --folder <cwd>`.)")


if __name__ == '__main__':
    run_cli(main)
