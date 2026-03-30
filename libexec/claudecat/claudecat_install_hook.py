#!/usr/bin/env python3
"""
claudecat_install_hook — add the claudecat stop hook to Claude Code settings.

Idempotent: does nothing if the hook is already installed.
"""

import json
import os
import sys
import tempfile

SETTINGS_PATH = os.environ.get(
    'CLAUDECAT_SETTINGS_PATH',
    os.path.expanduser('~/.claude/settings.local.json')
)
# Hook script lives alongside this file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK_SCRIPT = os.path.join(SCRIPT_DIR, 'claudecat_hook.py')
HOOK_COMMAND = f"python3 {HOOK_SCRIPT}"
HOOK_MARKER = 'claudecat_hook.py'  # substring used to identify our hook


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
    settings = _load_settings()

    if is_installed(settings):
        print("claudecat stop hook is already installed.")
        sys.exit(0)

    hooks = settings.setdefault('hooks', {})
    stop_hooks = hooks.setdefault('Stop', [])
    stop_hooks.append({
        "matcher": "",
        "hooks": [{"type": "command", "command": HOOK_COMMAND}]
    })

    _save_settings(settings)
    print(f"claudecat stop hook installed.")
    print(f"  Hook script: {HOOK_SCRIPT}")
    print(f"  Settings:    {SETTINGS_PATH}")


if __name__ == '__main__':
    main()
