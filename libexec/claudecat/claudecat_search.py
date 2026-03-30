#!/usr/bin/env python3
"""
claudecat_search — Search cataloged Claude conversations.

Usage:
    python3 claudecat_search.py [--or] [--csv] [--folder <path>] <terms...>
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_db import Database


def _print_table(rows):
    """Print results as a formatted text table."""
    if not rows:
        return

    headers = ['ID', 'Title', 'Topics', 'CWD', 'Date']

    # Compute column widths
    col_widths = [len(h) for h in headers]
    data_rows = []
    for r in rows:
        date = (r['started_at'] or '')[:10]
        row_data = [
            r['id'] or '',
            r['title'] or '',
            r['topics'] or '',
            r['cwd'] or '',
            date,
        ]
        data_rows.append(row_data)
        for i, val in enumerate(row_data):
            col_widths[i] = max(col_widths[i], len(val))

    sep = '  '
    header_line = sep.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider = sep.join('-' * w for w in col_widths)

    print(header_line)
    print(divider)
    for row_data in data_rows:
        print(sep.join(val.ljust(col_widths[i]) for i, val in enumerate(row_data)))


def _print_csv(rows):
    """Print results as CSV with header id,title,topics,cwd,date."""
    writer = csv.writer(sys.stdout)
    writer.writerow(['id', 'title', 'topics', 'cwd', 'date'])
    for r in rows:
        date = (r['started_at'] or '')[:10]
        writer.writerow([
            r['id'] or '',
            r['title'] or '',
            r['topics'] or '',
            r['cwd'] or '',
            date,
        ])


def main():
    parser = argparse.ArgumentParser(
        description='Search cataloged Claude conversations.'
    )
    parser.add_argument('terms', nargs='+', metavar='TERM',
                        help='Search terms')
    parser.add_argument('--or', dest='or_', action='store_true',
                        help='Match any term instead of all terms')
    parser.add_argument('--csv', action='store_true',
                        help='Output results as CSV')
    parser.add_argument('--folder', metavar='PATH',
                        help='Restrict search to a specific project folder')
    args = parser.parse_args()

    db = Database()
    db.validate()

    mode = 'or' if args.or_ else 'and'
    results = db.search(args.terms, mode=mode, folder=args.folder)

    if not results:
        print("No conversations found.", file=sys.stderr)
        sys.exit(0)

    if args.csv:
        _print_csv(results)
    else:
        _print_table(results)


if __name__ == '__main__':
    main()
