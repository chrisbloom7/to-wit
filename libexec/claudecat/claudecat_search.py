#!/usr/bin/env python3
"""
claudecat_search — Search cataloged Claude conversations.

Usage:
    python3 claudecat_search.py [--or] [--all | --summary] [--all | --title] [--csv] [--folder <path>] <terms...>
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


def _filter_topics(topics_str, terms):
    """Return only topics matching at least one term, or empty string if none match.

    Uses substring check plus stem prefix matching against each hyphenated word in the topic
    (e.g. "estimate" → stem "estimat" matches "project-estimation").
    """
    if not topics_str:
        return ''
    topics = [t.strip() for t in topics_str.split(',')]

    def matches(topic, term):
        tl = term.lower()
        if tl in topic.lower():
            return True
        if len(tl) >= 5:
            stem = tl[:-1]
            for word in topic.lower().replace('-', ' ').split():
                if word.startswith(stem):
                    return True
        return False

    matched = [t for t in topics if any(matches(t, term) for term in terms)]
    return matched[0] if matched else ''


def _print_table(rows, terms=None, group_by_path=False):
    """Print results as a formatted text table, optionally grouped by CWD."""
    if not rows:
        return

    headers = ['ID', 'Title', 'Topics', 'Date']
    sep = '  '
    indent = '  ' if group_by_path else ''

    # Pre-process rows: filter topics and pair each with its CWD
    processed = []
    for r in rows:
        date = (r['started_at'] or '')[:10]
        topics = r['topics'] or ''
        if terms:
            topics = _filter_topics(topics, terms)
        processed.append((r['cwd'] or '', [
            r['id'] or '',
            r['title'] or '',
            topics,
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
        description='Search cataloged Claude conversations.'
    )
    parser.add_argument('terms', nargs='+', metavar='TERM',
                        help='Search terms')
    parser.add_argument('--or', dest='or_', action='store_true',
                        help='Match any term instead of all terms')
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--all', action='store_true',
                       help='Search topics, summaries, and titles')
    scope.add_argument('--summary', action='store_true',
                       help='Also search conversation summaries')
    scope.add_argument('--title', action='store_true',
                       help='Also search conversation titles')
    fmt_group = parser.add_mutually_exclusive_group()
    fmt_group.add_argument('--format', choices=['json', 'csv'], metavar='FORMAT',
                           help='Output format: json or csv')
    fmt_group.add_argument('--csv', action='store_true',
                           help='Output results as CSV (shorthand for --format csv)')
    parser.add_argument('--folder', metavar='PATH',
                        help='Restrict search to a specific project folder')
    args = parser.parse_args()

    db = Database()
    db.validate()

    include_summary = args.all or args.summary
    include_title = args.all or args.title
    mode = 'or' if args.or_ else 'and'
    results = db.search(args.terms, mode=mode, folder=args.folder,
                        include_summary=include_summary, include_title=include_title)

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
        _print_table(results, terms=args.terms, group_by_path=not args.folder)


if __name__ == '__main__':
    main()
