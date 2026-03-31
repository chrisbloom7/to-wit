#!/usr/bin/env python3
"""
claudecat_prune — Remove catalog entries whose transcripts no longer exist.

Usage:
    python3 claudecat_prune.py [--dry-run]

Conversations whose JSONL transcript is missing from ~/.claude/projects/ cannot
be resumed or exported. This command removes them from the catalog.

Conversations whose working directory is missing but transcript is intact are
left untouched — they can still be resumed with `claudecat open --force`.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_db import Database


def main():
    parser = argparse.ArgumentParser(
        description='Remove catalog entries whose transcripts no longer exist.'
    )
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

    for s in missing:
        transcript = os.path.join(s['folder'], f"{s['id']}.jsonl")
        if args.dry_run:
            print(f"  would remove: {s['id']}  (transcript: {transcript})")
        else:
            db.delete_conversation(s['id'])
            print(f"  removed: {s['id']}")

    total = len(missing)
    if args.dry_run:
        print(f"\nDry run: {total} of {len(stubs)} entr{'y' if total == 1 else 'ies'} would be pruned.")
    else:
        print(f"\nPruned {total} of {len(stubs)} entr{'y' if total == 1 else 'ies'}.")


if __name__ == '__main__':
    main()
