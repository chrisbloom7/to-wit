#!/usr/bin/env python3
"""
towit_install_hook — add the To Wit stop hook to Claude Code settings.

Idempotent: does nothing if the hook is already installed.
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
# Hook script lives alongside this file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK_SCRIPT = os.path.join(SCRIPT_DIR, 'towit_hook.py')
HOOK_COMMAND = f"python3 {HOOK_SCRIPT}"
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
    """Return True if our hook is already present."""
    for entry in settings.get('hooks', {}).get('Stop', []):
        for hook in entry.get('hooks', []):
            if HOOK_MARKER in hook.get('command', ''):
                return True
    return False


def main():
    argparse.ArgumentParser(
        description='Add the To Wit stop hook to Claude Code settings.'
    ).parse_args()
    settings = _load_settings()

    if is_installed(settings):
        print("To Wit stop hook is already installed.")
        sys.exit(0)

    hooks = settings.setdefault('hooks', {})
    stop_hooks = hooks.setdefault('Stop', [])
    new_hook = {"type": "command", "command": HOOK_COMMAND}

    # Merge into an existing empty-matcher entry rather than appending a new one,
    # so that all global Stop hooks share a single entry in the settings file.
    merged = False
    for entry in stop_hooks:
        if entry.get('matcher', '') == '':
            entry.setdefault('hooks', []).append(new_hook)
            merged = True
            break

    if not merged:
        stop_hooks.append({"matcher": "", "hooks": [new_hook]})

    _save_settings(settings)
    print(f"To Wit stop hook installed.")
    print(f"  Hook script: {HOOK_SCRIPT}")
    print(f"  Settings:    {SETTINGS_PATH}")


if __name__ == '__main__':
    main()
