#!/usr/bin/env python3
"""
claudecat_export — Export one or more Claude conversations from the catalog.

Usage:
    python3 claudecat_export.py <session-id> [--format md|json] [--summarize]
    python3 claudecat_export.py --topic <name> [--format md|json] [--summarize]
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_db import Database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_claude(prompt: str) -> str:
    result = subprocess.run(
        ['claude', '-p', prompt, '--output-format', 'text'],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, 'CLAUDECAT_INDEXING': '1'}
    )
    if result.returncode != 0:
        print(f"Error calling Claude: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _parse_jsonl(path: str) -> list:
    """
    Parse a JSONL transcript file into a list of message dicts.

    Returns: [{'role': 'user'|'assistant', 'content': str}, ...]
    Skips: tool_use, tool_result, thinking, file-history-snapshot entries.
    For assistant messages, only includes type='text' content items.
    """
    messages = []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get('type') != 'message':
                    continue

                msg = entry.get('message', {})
                role = msg.get('role', '')
                if role not in ('user', 'assistant'):
                    continue

                content = msg.get('content', '')
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = []
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        item_type = item.get('type', '')
                        if item_type in ('tool_use', 'tool_result', 'thinking',
                                         'file-history-snapshot'):
                            continue
                        if item_type == 'text':
                            parts.append(item.get('text', ''))
                        elif role == 'user' and item_type not in (
                                'tool_use', 'tool_result', 'thinking',
                                'file-history-snapshot'):
                            # For user messages include plain text items
                            text_val = item.get('text', '')
                            if text_val:
                                parts.append(text_val)
                    text = '\n'.join(parts)
                else:
                    continue

                text = text.strip()
                if not text:
                    continue

                messages.append({'role': role, 'content': text})

    except OSError as exc:
        print(f"Error reading {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    return messages


def _format_markdown(conv: dict, messages: list) -> str:
    """Render a single conversation as Markdown."""
    lines = []
    title = conv.get('title') or conv.get('id', 'Conversation')
    lines.append(f"# {title}")
    lines.append('')
    date = (conv.get('started_at') or '')[:10]
    if date:
        lines.append(f"**Date:** {date}")
    cwd = conv.get('cwd', '')
    if cwd:
        lines.append(f"**Project:** {cwd}")
    lines.append('')
    lines.append('---')
    lines.append('')

    for msg in messages:
        role_label = 'Human' if msg['role'] == 'user' else 'Assistant'
        lines.append(f"**{role_label}:**")
        lines.append('')
        lines.append(msg['content'])
        lines.append('')

    return '\n'.join(lines)


def _format_json_export(conv: dict, messages: list) -> str:
    """Render a single conversation as JSON."""
    payload = {
        'id':         conv.get('id'),
        'title':      conv.get('title'),
        'date':       (conv.get('started_at') or '')[:10],
        'cwd':        conv.get('cwd'),
        'topics':     conv.get('topics'),
        'messages':   messages,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _get_jsonl_path(conv: dict, session_id: str) -> str:
    folder = conv.get('folder', '')
    if not folder:
        print(
            f"Error: no folder recorded for session {session_id}.",
            file=sys.stderr
        )
        sys.exit(1)
    return os.path.join(folder, f'{session_id}.jsonl')


# ---------------------------------------------------------------------------
# Export implementations
# ---------------------------------------------------------------------------

def export_single(db: Database, session_id: str, fmt: str, summarize: bool):
    conv = db.get_conversation(session_id)
    if conv is None:
        print(f"Error: session '{session_id}' not found in catalog.", file=sys.stderr)
        sys.exit(1)

    jsonl_path = _get_jsonl_path(conv, session_id)
    if not os.path.exists(jsonl_path):
        print(f"Error: transcript not found at {jsonl_path}", file=sys.stderr)
        sys.exit(1)

    messages = _parse_jsonl(jsonl_path)

    if summarize:
        transcript_text = _format_markdown(conv, messages)
        date = (conv.get('started_at') or '')[:10]
        cwd = conv.get('cwd', '')
        prompt = (
            f"Please produce a structured Markdown summary of the following "
            f"Claude conversation. The summary should cover:\n"
            f"- What was asked / the problem being solved\n"
            f"- What was explored or attempted\n"
            f"- Key conclusions or outcomes\n\n"
            f"Begin with a metadata header:\n"
            f"- Session: {session_id}\n"
            f"- Date: {date}\n"
            f"- Project: {cwd}\n\n"
            f"Transcript:\n\n{transcript_text}"
        )
        print(_call_claude(prompt))
        return

    if fmt == 'json':
        print(_format_json_export(conv, messages))
    else:
        print(_format_markdown(conv, messages))


def export_topic(db: Database, topic: str, fmt: str, summarize: bool):
    convs = db.list_conversations(topic=topic)
    if not convs:
        print(f"No conversations found for topic '{topic}'.", file=sys.stderr)
        sys.exit(0)

    if summarize:
        # Build a meta-summary from DB summaries (no JSONL re-read)
        summary_parts = []
        for conv in convs:
            session_id = conv['id']
            short_id = session_id[:8]
            date = (conv.get('started_at') or '')[:10]
            cwd = conv.get('cwd', '')
            ref = f"[Session {short_id}] {date} | {cwd}"
            db_summary = conv.get('summary') or '(no summary available)'
            summary_parts.append(f"### {ref}\n\n{db_summary}")

        all_summaries = '\n\n---\n\n'.join(summary_parts)
        prompt = (
            f"The following are summaries of multiple Claude conversations "
            f"all related to the topic '{topic}'. Please produce a single "
            f"synthesized meta-summary document that:\n"
            f"- Identifies common themes and patterns\n"
            f"- Highlights key conclusions across sessions\n"
            f"- Notes any evolution or progression of ideas\n"
            f"- Includes a references section listing each session\n\n"
            f"Format each reference as: [Session <short-id>] <date> | <cwd>\n\n"
            f"Session summaries:\n\n{all_summaries}"
        )
        print(_call_claude(prompt))
        return

    # Full transcript export for each conversation
    separator = '\n\n---\n\n'
    outputs = []

    for conv in convs:
        session_id = conv['id']
        jsonl_path = _get_jsonl_path(conv, session_id)
        if not os.path.exists(jsonl_path):
            print(
                f"Warning: transcript not found at {jsonl_path}, skipping.",
                file=sys.stderr
            )
            continue
        messages = _parse_jsonl(jsonl_path)
        if fmt == 'json':
            outputs.append(_format_json_export(conv, messages))
        else:
            outputs.append(_format_markdown(conv, messages))

    if not outputs:
        print("No transcripts could be exported.", file=sys.stderr)
        sys.exit(1)

    print(separator.join(outputs))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Export Claude conversations from the catalog.'
    )
    parser.add_argument('session_id', nargs='?', default=None,
                        metavar='SESSION_ID',
                        help='Session ID to export')
    parser.add_argument('--topic', metavar='NAME',
                        help='Export all conversations for a topic')
    parser.add_argument('--format', dest='format', choices=['md', 'json'],
                        default='md',
                        help='Output format (default: md)')
    parser.add_argument('--summarize', action='store_true',
                        help='Generate a Claude-powered summary instead of raw transcript')
    args = parser.parse_args()

    # Validate: exactly one of session_id or --topic
    if args.session_id and args.topic:
        print("Error: specify either a session ID or --topic, not both.", file=sys.stderr)
        sys.exit(1)
    if not args.session_id and not args.topic:
        print("Error: specify a session ID or --topic.", file=sys.stderr)
        parser.print_usage(sys.stderr)
        sys.exit(1)

    db = Database()
    db.validate()

    if args.session_id:
        export_single(db, args.session_id, args.format, args.summarize)
    else:
        export_topic(db, args.topic, args.format, args.summarize)


if __name__ == '__main__':
    main()
