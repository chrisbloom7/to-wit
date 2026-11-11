#!/usr/bin/env python3
"""
towit_uninstall_hook — remove the To Wit hooks from Claude Code settings.

Idempotent: does nothing if the hook is not installed.
"""

import argparse
import json
import os
import sys
import tempfile


def _resolve_settings_path():
    """Return a validated settings path from env override or default."""
    raw = os.environ.get(
        'TOWIT_SETTINGS_PATH',
        os.path.expanduser('~/.claude/settings.json')
    )
    resolved = os.path.realpath(os.path.expanduser(raw))
    home_claude = os.path.realpath(os.path.expanduser('~/.claude'))
    tmp = os.path.realpath(tempfile.gettempdir())
    if resolved.startswith(home_claude + os.sep) or resolved.startswith(tmp + os.sep):
        return resolved
    print(
        "Warning: TOWIT_SETTINGS_PATH is outside expected directories, using default.",
        file=sys.stderr
    )
    return os.path.expanduser('~/.claude/settings.json')


SETTINGS_PATH = _resolve_settings_path()
HOOK_MARKER = 'towit_hook.py'  # substring used to identify our hook


def _load_settings():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH) as f:
            return json.load(f)
    return {}


def _save_settings(settings):
    """Write settings atomically."""
    settings_dir = os.path.dirname(SETTINGS_PATH)
    os.makedirs(settings_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=settings_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(settings, f, indent=2)
            f.write('\n')
        os.replace(tmp_path, SETTINGS_PATH)
    except Exception:
        os.unlink(tmp_path)
        raise


def is_installed(settings):
    """Return True if our hook is present under any event."""
    return any(
        HOOK_MARKER in hook.get('command', '')
        for entries in settings.get('hooks', {}).values()
        for entry in entries
        for hook in entry.get('hooks', [])
    )


def remove_hooks(settings):
    """Remove every To Wit hook from all events in place, preserving all others."""
    hooks = settings.get('hooks', {})
    for event in list(hooks):
        cleaned = []
        for entry in hooks[event]:
            filtered_hooks = [
                h for h in entry.get('hooks', [])
                if HOOK_MARKER not in h.get('command', '')
            ]
            if filtered_hooks:
                cleaned.append({**entry, 'hooks': filtered_hooks})
            # If all hooks in this entry were ours, drop the whole entry
        if cleaned:
            hooks[event] = cleaned
        else:
            del hooks[event]  # clean up empty event sections
    if not hooks:
        settings.pop('hooks', None)


def main():
    argparse.ArgumentParser(
        description='Remove the To Wit hooks from Claude Code settings.'
    ).parse_args()
    if not os.path.exists(SETTINGS_PATH):
        print("No settings file found — hooks were not installed.")
        sys.exit(0)

    settings = _load_settings()

    if not is_installed(settings):
        print("To Wit hooks are not installed.")
        sys.exit(0)

    remove_hooks(settings)
    _save_settings(settings)
    print("To Wit hooks removed.")


if __name__ == '__main__':
    main()
