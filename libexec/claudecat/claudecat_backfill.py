#!/usr/bin/env python3
"""
claudecat_backfill — Backfill the catalog from existing JSONL transcripts.

Usage:
    python3 claudecat_backfill.py [--dry-run] [--force] [--folder <path>]
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_index import index_conversation, parse_jsonl, should_index
from claudecat_db import Database


def main():
    parser = argparse.ArgumentParser(
        description='Backfill the claudecat catalog from existing transcripts.'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be indexed without writing')
    parser.add_argument('--force', action='store_true',
                        help='Re-index already indexed conversations')
    parser.add_argument('--folder', metavar='PATH',
                        help='Restrict to a specific project folder path')
    args = parser.parse_args()

    # Determine search root
    if args.folder:
        search_root = args.folder
    else:
        search_root = os.path.expanduser('~/.claude/projects')

    if not os.path.isdir(search_root):
        print(f"Error: directory not found: {search_root}", file=sys.stderr)
        sys.exit(1)

    # Find all JSONL files, sorted by mtime (oldest first).
    # Exclude subagent sessions — they live under a subagents/ directory and
    # are not interactive user conversations.
    pattern = os.path.join(search_root, '**', '*.jsonl')
    jsonl_files = [
        p for p in glob.glob(pattern, recursive=True)
        if '/subagents/' not in p and not os.path.islink(p)
    ]
    jsonl_files.sort(key=lambda p: os.path.getmtime(p))

    total = len(jsonl_files)
    print(f"[0/{total}] Starting backfill...")

    if total == 0:
        print("No JSONL files found.")
        return

    # For dry-run already-indexed checks we need the DB
    db = None
    if args.dry_run:
        db = Database()
        try:
            db.validate()
        except SystemExit:
            db = None  # DB not yet set up; everything would be indexed

    counts = {'indexed': 0, 'skipped': 0, 'already_indexed': 0, 'error': 0}

    for i, path in enumerate(jsonl_files, start=1):
        session_id = os.path.splitext(os.path.basename(path))[0]
        print(f"[{i}/{total}] Processing {session_id}...")

        if args.dry_run:
            if db is not None and db.is_indexed(session_id) and not args.force:
                print(f"  -> would skip (already indexed)")
                counts['already_indexed'] += 1
                continue
            messages = parse_jsonl(path)
            if not should_index(messages):
                print(f"  -> would skip (too short / insufficient content)")
                counts['skipped'] += 1
                continue
            print(f"  -> would index (Claude analysis may still skip)")
            counts['indexed'] += 1
            continue

        try:
            result = index_conversation(path, force=args.force)
        except Exception as exc:
            print(f"  -> error: {exc}", file=sys.stderr)
            counts['error'] += 1
            continue

        if result is None:
            print(f"  -> error (None returned)")
            counts['error'] += 1
        elif result == 'already_indexed':
            print(f"  -> already indexed")
            counts['already_indexed'] += 1
        elif result == 'skipped':
            print(f"  -> skipped")
            counts['skipped'] += 1
        elif result == 'indexed':
            print(f"  -> indexed")
            counts['indexed'] += 1
        else:
            print(f"  -> unknown status: {result}")

    print(
        f"\nBackfill complete. "
        f"Indexed: {counts['indexed']}, "
        f"Skipped: {counts['skipped']}, "
        f"Already indexed: {counts['already_indexed']}"
        + (f", Errors: {counts['error']}" if counts['error'] else "")
    )


if __name__ == '__main__':
    main()
