#!/usr/bin/env python3
"""
claudecat_list — List cataloged Claude conversations.

Usage:
    python3 claudecat_list.py [--format json|csv | --csv] [--folder <path>] [--topic <name>]
"""

import argparse
import csv
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_db import Database


def _truncate(s, width):
    if len(s) <= width:
        return s
    return s[:width - 1] + '…'


def _print_table(rows, group_by_path=False):
    """Print results as a formatted text table, optionally grouped by CWD."""
    if not rows:
        return

    headers = ['ID', 'Title', 'Topics', 'Date']
    sep = '  '
    indent = '  ' if group_by_path else ''

    processed = []
    for r in rows:
        date = (r['started_at'] or '')[:10]
        processed.append((r['cwd'] or '', [
            r['id'] or '',
            r['title'] or '',
            r['topics'] or '',
            date,
        ]))

    # Compute natural column widths across all rows
    col_widths = [len(h) for h in headers]
    for _, row_data in processed:
        for i, val in enumerate(row_data):
            col_widths[i] = max(col_widths[i], len(val))

    # Shrink Title and Topics proportionally if table exceeds terminal width
    term_width = shutil.get_terminal_size((120, 24)).columns - 4
    total = sum(col_widths) + len(sep) * (len(headers) - 1) + len(indent)
    if total > term_width:
        shrink_cols = [1, 2]  # Title, Topics
        shrinkable = sum(col_widths[i] for i in shrink_cols)
        overflow = total - term_width
        for i in shrink_cols:
            reduction = int(overflow * col_widths[i] / shrinkable)
            col_widths[i] = max(8, col_widths[i] - reduction)

    def fmt_row(row_data):
        return indent + sep.join(
            _truncate(val, col_widths[i]).ljust(col_widths[i])
            for i, val in enumerate(row_data)
        )

    header_line = indent + sep.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider = indent + sep.join('-' * w for w in col_widths)

    if group_by_path:
        groups = {}
        order = []
        for cwd, row_data in processed:
            if cwd not in groups:
                groups[cwd] = []
                order.append(cwd)
            groups[cwd].append(row_data)

        first = True
        for cwd in sorted(order):
            if not first:
                print()
            first = False
            print(cwd or '(unknown)')
            print(header_line)
            print(divider)
            for row_data in groups[cwd]:
                print(fmt_row(row_data))
    else:
        print(header_line)
        print(divider)
        for _, row_data in processed:
            print(fmt_row(row_data))


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


def _print_json(rows):
    """Print results as a JSON array of objects."""
    out = []
    for r in rows:
        topics_str = r['topics'] or ''
        topics = [t.strip() for t in topics_str.split(',')] if topics_str else []
        out.append({
            'id': r['id'] or '',
            'title': r['title'] or '',
            'topics': topics,
            'cwd': r['cwd'] or '',
            'date': (r['started_at'] or '')[:10],
        })
    print(json.dumps(out, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description='List cataloged Claude conversations.'
    )
    fmt_group = parser.add_mutually_exclusive_group()
    fmt_group.add_argument('--format', choices=['json', 'csv'], metavar='FORMAT',
                           help='Output format: json or csv')
    fmt_group.add_argument('--csv', action='store_true',
                           help='Output results as CSV (shorthand for --format csv)')
    parser.add_argument('--folder', metavar='PATH',
                        help='Restrict to a specific project folder')
    parser.add_argument('--topic', metavar='NAME',
                        help='Filter by topic name')
    args = parser.parse_args()

    db = Database()
    db.validate()

    results = db.list_conversations(folder=args.folder, topic=args.topic)

    fmt = args.format or ('csv' if args.csv else None)

    if fmt == 'json':
        _print_json(results)
    elif fmt == 'csv' or args.csv:
        if not results:
            print("No conversations found.", file=sys.stderr)
            sys.exit(0)
        _print_csv(results)
    else:
        if not results:
            print("No conversations found.", file=sys.stderr)
            sys.exit(0)
        _print_table(results, group_by_path=not args.folder)


if __name__ == '__main__':
    main()
