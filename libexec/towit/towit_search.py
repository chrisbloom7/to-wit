#!/usr/bin/env python3
"""
towit_search — Search cataloged Claude conversations.

Usage:
    python3 towit_search.py [--or] [--topic] [--all | --summary] [--all | --title] [--format json|csv] [--folder <path>] <terms...>
"""

import argparse
import csv
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_db import Database


def _truncate(s, width):
    if len(s) <= width:
        return s
    return s[:width - 1] + '…'


def _filter_keywords(keywords_str, terms):
    """Return only keywords matching at least one term, or empty string if none match.

    Uses substring check plus stem prefix matching against each hyphenated word in the keyword
    (e.g. "sprint" → stem "sprin" matches "sprint-planning").
    """
    if not keywords_str:
        return ''
    keywords = [k.strip() for k in keywords_str.split(',')]

    def matches(keyword, term):
        tl = term.lower()
        if tl in keyword.lower():
            return True
        if len(tl) >= 5:
            stem = tl[:-1]
            for word in keyword.lower().replace('-', ' ').split():
                if word.startswith(stem):
                    return True
        return False

    matched = [k for k in keywords if any(matches(k, term) for term in terms)]
    return matched[0] if matched else ''


def _print_table(rows, terms=None, group_by_path=False):
    """Print results as a formatted text table, optionally grouped by CWD."""
    if not rows:
        return

    headers = ['ID', 'Title', 'Keywords', 'Date']
    sep = '  '
    indent = '  ' if group_by_path else ''

    # Pre-process rows: filter keywords and pair each with its CWD
    processed = []
    for r in rows:
        date = (r['started_at'] or '')[:10]
        keywords = r['keywords'] or ''
        if terms:
            keywords = _filter_keywords(keywords, terms)
        processed.append((r['cwd'] or '', [
            r['id'] or '',
            r['title'] or '',
            keywords,
            date,
        ]))

    # Compute natural column widths across all rows
    col_widths = [len(h) for h in headers]
    for _, row_data in processed:
        for i, val in enumerate(row_data):
            col_widths[i] = max(col_widths[i], len(val))

    # Shrink Title and Keywords proportionally if table exceeds terminal width
    term_width = shutil.get_terminal_size((120, 24)).columns - 4
    total = sum(col_widths) + len(sep) * (len(headers) - 1) + len(indent)
    if total > term_width:
        shrink_cols = [1, 2]  # Title, Keywords
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


def main():
    parser = argparse.ArgumentParser(
        description='Search cataloged Claude conversations.'
    )
    parser.add_argument('terms', nargs='+', metavar='TERM',
                        help='Search terms')
    parser.add_argument('--or', dest='or_', action='store_true',
                        help='Match any term instead of all terms')
    parser.add_argument('--topic', action='store_true',
                        help='Also search conversation topics')
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--all', action='store_true',
                       help='Search keywords, topics, summaries, and titles')
    scope.add_argument('--summary', action='store_true',
                       help='Also search conversation summaries')
    scope.add_argument('--title', action='store_true',
                       help='Also search conversation titles')
    parser.add_argument('--format', choices=['json', 'csv'], metavar='FORMAT',
                        help='Output format: json or csv')
    parser.add_argument('--folder', metavar='PATH',
                        help='Restrict search to a specific project folder')
    args = parser.parse_args()

    db = Database()
    db.validate()

    include_topics = args.all or args.topic
    include_summary = args.all or args.summary
    include_title = args.all or args.title
    mode = 'or' if args.or_ else 'and'
    results = db.search(args.terms, mode=mode, folder=args.folder,
                        include_keywords=True, include_topics=include_topics,
                        include_summary=include_summary, include_title=include_title)

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
        _print_table(results, terms=args.terms, group_by_path=not args.folder)


if __name__ == '__main__':
    main()
