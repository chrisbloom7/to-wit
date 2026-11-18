#!/usr/bin/env python3
"""
towit_list — List cataloged Claude conversations.

Usage:
    python3 towit_list.py [--format json|csv] [--folder <path>] [--topic <name>] [--keyword <name>] [--since YYYY-MM-DD]
"""

import argparse
import csv
from datetime import date
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_db import Database
from towit_pipe import run_cli
from towit_sanitize import sanitize_cell
from towit_table import display_width, fit_widths, pad, truncate


def _print_table(rows, group_by_path=False):
    """Print results as a formatted text table, optionally grouped by CWD."""
    if not rows:
        return

    headers = ['ID', 'Title', 'Keywords', 'Date']
    sep = '  '
    indent = '  ' if group_by_path else ''

    processed = []
    for r in rows:
        date = (r['started_at'] or '')[:10]
        processed.append((sanitize_cell(r['cwd']), [sanitize_cell(v) for v in (
            r['id'], r['title'], r['keywords'], date)]))

    # Compute natural column widths across all rows
    col_widths = [display_width(h) for h in headers]
    for _, row_data in processed:
        for i, val in enumerate(row_data):
            col_widths[i] = max(col_widths[i], display_width(val))

    # Fit the table after omitting any entirely empty Keywords column.
    term_width = shutil.get_terminal_size((120, 24)).columns - 4
    floors = [None, 8, 8, None]
    floors = [None if f is None else max(f, display_width(h)) for f, h in zip(floors, headers)]
    keywords_col = headers.index('Keywords')
    hide_keywords = not any(row[keywords_col] for _, row in processed)
    col_widths, kept = fit_widths(
        col_widths, floors, term_width, sep_width=len(sep), indent_width=len(indent),
        droppable=keywords_col, omit_droppable=hide_keywords,
    )

    def fmt_row(row_data):
        return indent + sep.join(
            pad(truncate(row_data[i], col_widths[i]), col_widths[i]) for i in kept
        )

    header_line = indent + sep.join(pad(headers[i], col_widths[i]) for i in kept)
    divider = indent + sep.join('-' * col_widths[i] for i in kept)

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
    """Print results as CSV with header id,title,keywords,topics,cwd,date."""
    writer = csv.writer(sys.stdout)
    writer.writerow(['id', 'title', 'keywords', 'topics', 'cwd', 'date'])
    for r in rows:
        date = (r['started_at'] or '')[:10]
        writer.writerow([
            r['id'] or '',
            r['title'] or '',
            r['keywords'] or '',
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
        keywords_str = r['keywords'] or ''
        keywords = [k.strip() for k in keywords_str.split(',')] if keywords_str else []
        out.append({
            'id': r['id'] or '',
            'title': r['title'] or '',
            'keywords': keywords,
            'topics': topics,
            'cwd': r['cwd'] or '',
            'date': (r['started_at'] or '')[:10],
        })
    print(json.dumps(out, indent=2))


def _iso_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('expected a valid date in YYYY-MM-DD format')


def main():
    parser = argparse.ArgumentParser(
        description='List cataloged Claude conversations.'
    )
    parser.add_argument('--format', choices=['json', 'csv'], metavar='FORMAT',
                        help='Output format: json or csv')
    parser.add_argument('--folder', metavar='PATH',
                        help='Restrict to a specific project folder')
    parser.add_argument('--topic', metavar='NAME',
                        help='Filter by topic name')
    parser.add_argument('--keyword', metavar='NAME',
                        help='Filter by keyword')
    parser.add_argument('--since', type=_iso_date, metavar='YYYY-MM-DD',
                        help='Include conversations that started on or after this date')
    args = parser.parse_args()

    db = Database()
    db.validate()

    results = db.list_conversations(
        folder=args.folder, topic=args.topic, keyword=args.keyword, since=args.since,
    )

    if args.format == 'json':
        _print_json(results)
    elif args.format == 'csv':
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
    run_cli(main)
