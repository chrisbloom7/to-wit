#!/usr/bin/env python3
"""
towit_backfill — Archive and index existing JSONL transcripts.

Usage:
    python3 towit_backfill.py [--dry-run] [--force] [--folder <path>]
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_config import config, is_subagent_path
from towit_index import index_conversation, parse_jsonl, should_index
from towit_ingest import ingest_transcript, should_skip_path
from towit_db import Database


def main():
    parser = argparse.ArgumentParser(
        description='Backfill the To Wit catalog from existing transcripts.'
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

    # Find all JSONL files, sorted by mtime (oldest first). Symlinks, subagent
    # sessions and folder-filtered files are dropped via ingest's own rules.
    pattern = os.path.join(search_root, '**', '*.jsonl')
    jsonl_files = [p for p in glob.glob(pattern, recursive=True) if not should_skip_path(p)]
    jsonl_files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)

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

    counts = {'indexed': 0, 'skipped': 0, 'already_indexed': 0, 'error': 0, 'archived': 0}
    archived_statuses = ('ingested', 'appended', 'rewritten', 'unchanged')

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
            status = ingest_transcript(path)
        except Exception as exc:
            print(f"  -> error: {exc}", file=sys.stderr)
            counts['error'] += 1
            continue

        if status not in archived_statuses:
            print(f"  -> {status}")
            counts['skipped'] += 1  # 'skipped' or 'forgotten': nothing archived
            continue
        counts['archived'] += 1

        if not config.indexing_enabled:
            print(f"  -> {status} (indexing disabled)")
            continue
        if is_subagent_path(path):
            print(f"  -> {status} (subagent: not indexed)")
            continue

        try:
            result = index_conversation(path, force=args.force)
        except Exception as exc:
            print(f"  -> {status}; index error: {exc}", file=sys.stderr)
            counts['error'] += 1
            continue

        if result == 'indexed':
            print(f"  -> {status}; indexed")
            counts['indexed'] += 1
        elif result == 'already_indexed':
            print(f"  -> {status}; already indexed")
            counts['already_indexed'] += 1
        elif result == 'skipped':
            print(f"  -> {status}; index skipped")
        else:
            print(f"  -> {status}; index error (status: {result})")
            counts['error'] += 1

    summary = "\nBackfill complete. "
    if not args.dry_run:
        summary += f"Archived: {counts['archived']}, "
    print(
        summary
        + f"Indexed: {counts['indexed']}, "
        f"Skipped: {counts['skipped']}, "
        f"Already indexed: {counts['already_indexed']}"
        + (f", Errors: {counts['error']}" if counts['error'] else "")
    )


if __name__ == '__main__':
    main()
