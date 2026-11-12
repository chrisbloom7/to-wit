#!/usr/bin/env python3
"""
towit_stats — Show statistics about the To Wit catalog.

Usage:
    python3 towit_stats.py
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_db import Database
from towit_pipe import run_cli


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ('B', 'KB', 'MB'):
        if size < 1024:
            return f"{int(size)} B" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def main():
    argparse.ArgumentParser(
        description='Show statistics about the To Wit catalog.'
    ).parse_args()
    db = Database()
    db.validate()

    with db.connect() as conn:
        # Total conversations
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM conversations"
        ).fetchone()['n']

        # Date range
        dates = conn.execute(
            "SELECT MIN(started_at) AS oldest, MAX(started_at) AS newest "
            "FROM conversations"
        ).fetchone()
        oldest = (dates['oldest'] or '')[:10]
        newest = (dates['newest'] or '')[:10]

        # Top 20 topics by conversation count
        top_topics = conn.execute(
            """
            SELECT t.name, COUNT(ct.conversation_id) AS cnt
            FROM topics t
            JOIN conversation_topics ct ON ct.topic_id = t.id
            GROUP BY t.id, t.name
            ORDER BY cnt DESC
            LIMIT 20
            """
        ).fetchall()

        # Unique projects (distinct cwd values)
        unique_projects = conn.execute(
            "SELECT COUNT(DISTINCT cwd) AS n FROM conversations WHERE cwd IS NOT NULL AND cwd != ''"
        ).fetchone()['n']

    # Count pruneable entries: what a default `towit prune` removes (archived rows are kept)
    stubs = db.all_conversation_stubs()
    pruneable = sum(
        1 for s in stubs
        if not s['archived']
        and not os.path.isfile(os.path.join(s['folder'], f"{s['id']}.jsonl"))
    )
    archive = db.archive_stats()

    print(f"Total conversations   : {total}")
    print(f"Date range            : {oldest or 'n/a'} — {newest or 'n/a'}")
    print(f"Unique projects       : {unique_projects}")
    if pruneable:
        print(f"Pruneable entries     : {pruneable}  (run: towit prune)")
    print()
    print(f"Archived conversations      : {archive['archived']}")
    print(f"Metadata-only conversations : {archive['metadata_only']}")
    print(f"Archived messages           : {archive['messages']}")
    print(f"Database size               : {_format_bytes(archive['db_bytes'])}")
    print()

    if top_topics:
        print("Top topics:")
        max_name_len = max(len(r['name']) for r in top_topics)
        for row in top_topics:
            bar_width = row['cnt']
            bar = '#' * min(bar_width, 40)
            print(f"  {row['name']:<{max_name_len}}  {row['cnt']:>4}  {bar}")
    else:
        print("No topics indexed yet.")


if __name__ == '__main__':
    run_cli(main)
