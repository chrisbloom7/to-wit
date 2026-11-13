#!/usr/bin/env python3
"""
towit_show — Print the archived messages of a conversation.

Usage:
    python3 towit_show.py <session-id> [--around <msg>] [--context <n>] [--role user|assistant]
                             [--match <term>]... [--format text|json]

Reads from the archive, so it works after the original transcript is deleted.
--around windows are counted by message number before --role and --match filter them.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_db import Database
from towit_pipe import run_cli
from towit_sanitize import sanitize

DEFAULT_CONTEXT = 5
MAX_NUMBER = 2**62


def _non_negative_int(parser_name: str, value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = -1
    if not 0 <= number <= MAX_NUMBER:
        print(f"Error: {parser_name} must be an integer between 0 and {MAX_NUMBER}, got '{value}'.",
              file=sys.stderr)
        sys.exit(1)
    return number


def _print_text(header: dict, messages: list, around) -> None:
    title = ' '.join((header['title'] or '(untitled)').split())
    where = header['repo_key'] or header['cwd'] or header['folder']
    start = (header['started_at'] or '')[:10]
    end = (header['last_active'] or '')[:10]
    dates = start if start == end or not end else f"{start} to {end}"
    print(sanitize(f"{header['id']}  {title}  [{where}]  {dates}").replace('\n', ' ').replace('\t', ' '))
    print()
    for msg in messages:
        marker = '>> ' if around is not None and msg['seq'] == around else ''
        stamp = f" ({sanitize(msg['ts'])})" if msg['ts'] else ''
        print(f"{marker}[{msg['seq']}] {msg['role']}{stamp}")
        print(sanitize(msg['text']))
        print()


def main():
    parser = argparse.ArgumentParser(description='Show archived messages of a conversation.')
    parser.add_argument('session_id', metavar='SESSION_ID', help='Session ID to show')
    parser.add_argument('--around', metavar='MSG',
                        help='Show only messages near this message number (0-based; '
                             'the Msg column in `towit search` results)')
    parser.add_argument('--context', metavar='N', default=str(DEFAULT_CONTEXT),
                        help=f'Messages either side of --around (default: {DEFAULT_CONTEXT}); '
                             'only applies with --around')
    parser.add_argument('--role', choices=['user', 'assistant'], metavar='user|assistant',
                        help='Show only messages of this role (alone, an outline of the session\'s '
                             'prompts with their Msg numbers). Under `--role user` an [error] row '
                             '(a failed tool result) can still appear; under `--role assistant` '
                             '[Bash]-style tool stubs remain, as they sit inside assistant messages')
    parser.add_argument('--match', metavar='TERM', action='append',
                        help='Show only messages containing TERM (literal substring, ignoring case '
                             'and diacritics; not whole-word). Repeat to require every term in the '
                             'same message')
    parser.add_argument('--format', dest='format', choices=['text', 'json'], default='text',
                        help='Output format (default: text)')
    args = parser.parse_args()

    around = _non_negative_int('--around', args.around) if args.around is not None else None
    context = _non_negative_int('--context', args.context)

    for term in args.match or []:
        if not term.strip():
            print("Error: --match needs a non-empty term.", file=sys.stderr)
            sys.exit(1)

    db = Database()
    db.validate()

    header = db.get_show_header(args.session_id)
    if header is None:
        print(f"Error: session '{args.session_id}' not found in catalog.", file=sys.stderr)
        sys.exit(1)
    if not header['archived']:
        print(
            f"Error: session '{args.session_id}' has no archived messages.\n"
            "Run 'towit backfill' to archive it.",
            file=sys.stderr
        )
        sys.exit(1)

    messages = db.get_messages(args.session_id, around=around, context=context,
                               role=args.role, match=args.match)
    if not messages:
        if args.role or args.match:
            print("No messages match the given filters.", file=sys.stderr)
        elif around is None:
            print(f"Error: session '{args.session_id}' has no archived messages.", file=sys.stderr)
        else:
            print(f"Error: no archived messages within {context} of --around {around}.", file=sys.stderr)
        sys.exit(1)

    if args.format == 'json':
        print(json.dumps(messages, indent=2, ensure_ascii=True))
    else:
        _print_text(header, messages, around)


if __name__ == '__main__':
    run_cli(main)
