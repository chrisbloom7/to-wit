#!/usr/bin/env python3
"""
towit_install_hook — add the To Wit hooks (Stop, SessionEnd, SessionStart) to Claude Code settings.

Idempotent: does nothing if the hooks are already installed with the current command.
Re-running repairs hooks whose command points at a stale script path.
"""

import argparse
import json
import os
import re
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


def stable_script_path(path):
    """Map a Homebrew Cellar path to its version-independent opt/ path, if that exists.

    <prefix>/Cellar/<name>/<version>/<rest> -> <prefix>/opt/<name>/<rest>. The versioned
    path breaks on `brew upgrade`; opt/<name> is repointed by Homebrew. Deliberately
    avoids realpath, which would resolve opt/ straight back into the Cellar.
    """
    match = re.fullmatch(r'(.*)/Cellar/([^/]+)/[^/]+/(.+)', path)
    if match:
        prefix, name, rest = match.groups()
        candidate = f"{prefix}/opt/{name}/{rest}"
        if os.path.exists(candidate):
            return candidate
    return path


HOOK_SCRIPT = stable_script_path(os.path.join(SCRIPT_DIR, 'towit_hook.py'))
HOOK_MARKER = 'towit_hook.py'  # substring used to identify our hook
# Hook event -> matcher. towit_hook.py dispatches on the payload's hook_event_name.
HOOK_EVENTS = {'Stop': '', 'SessionEnd': '', 'SessionStart': 'startup'}


def hook_interpreter(env=None):
    """Return the interpreter to write into the hook command.

    TOWIT_PYTHON (from `env`, default os.environ) wins when it is an absolute, executable
    path without whitespace (the command is split on whitespace). Otherwise falls back to
    python3, with a warning on stderr if it was set but unusable.
    """
    raw = os.environ.get('TOWIT_PYTHON') if env is None else env.get('TOWIT_PYTHON')
    if not raw:
        return 'python3'
    if (os.path.isabs(raw) and not re.search(r'\s', raw)
            and os.path.isfile(raw) and os.access(raw, os.X_OK)):
        return raw
    print(
        f"Warning: TOWIT_PYTHON={raw!r} is not an absolute, executable path without "
        "whitespace; using python3 in the hook command.",
        file=sys.stderr
    )
    return 'python3'


def hook_command():
    """The command registered for every To Wit hook event (may warn; call once per run)."""
    return f"{hook_interpreter()} {HOOK_SCRIPT}"


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


def is_installed(settings, event=None):
    """Return True if our hook is present for `event`, or for every event if None."""
    events = HOOK_EVENTS if event is None else [event]
    return all(
        any(HOOK_MARKER in hook.get('command', '')
            for entry in settings.get('hooks', {}).get(ev, [])
            for hook in entry.get('hooks', []))
        for ev in events
    )


def _towit_hooks(settings, event):
    """Return our hook dicts registered for `event` (mutating them edits settings)."""
    return [hook
            for entry in settings.get('hooks', {}).get(event, [])
            for hook in entry.get('hooks', [])
            if HOOK_MARKER in hook.get('command', '')]


def repair_commands(settings, command=None):
    """Point every registered To Wit hook at `command` (default hook_command()); return how many changed."""
    command = command or hook_command()
    repaired = 0
    for event in HOOK_EVENTS:
        for hook in _towit_hooks(settings, event):
            if hook['command'] != command:
                hook['command'] = command
                repaired += 1
    return repaired


def main():
    argparse.ArgumentParser(
        description='Add the To Wit hooks (Stop, SessionEnd, SessionStart) to Claude Code settings.'
    ).parse_args()
    settings = _load_settings()

    command = hook_command()
    repaired = repair_commands(settings, command)

    if repaired == 0 and is_installed(settings):
        print("To Wit hooks are already installed.")
        sys.exit(0)

    if repaired:
        print(f"To Wit hook command updated in {repaired} place(s) to: {command}")

    hooks = settings.setdefault('hooks', {})
    added = False
    for event, matcher in HOOK_EVENTS.items():
        if is_installed(settings, event):
            continue
        added = True
        event_hooks = hooks.setdefault(event, [])
        new_hook = {"type": "command", "command": command}

        # Merge into an existing entry with the same matcher rather than appending a
        # new one, so that all global hooks for an event share a single entry.
        for entry in event_hooks:
            if entry.get('matcher', '') == matcher:
                entry.setdefault('hooks', []).append(new_hook)
                break
        else:
            event_hooks.append({"matcher": matcher, "hooks": [new_hook]})

    _save_settings(settings)
    if added:
        print("To Wit hooks installed.")
        print(f"  Hook script: {HOOK_SCRIPT}")
        print(f"  Events:      {', '.join(HOOK_EVENTS)}")
    print(f"  Settings:    {SETTINGS_PATH}")


if __name__ == '__main__':
    main()
