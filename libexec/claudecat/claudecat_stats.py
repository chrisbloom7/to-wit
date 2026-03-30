#!/usr/bin/env python3
"""
claudecat_stats — Show statistics about the claudecat catalog.

Usage:
    python3 claudecat_stats.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_db import Database


def main():
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

    print(f"Conversations indexed : {total}")
    print(f"Date range            : {oldest or 'n/a'} — {newest or 'n/a'}")
    print(f"Unique projects       : {unique_projects}")
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
    main()
