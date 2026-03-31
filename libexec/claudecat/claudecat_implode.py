#!/usr/bin/env python3
"""
claudecat_implode — remove the claudecat hook, database, and binary symlink.

Performs a full uninstall: removes the stop hook from ~/.claude/settings.json,
deletes the database, and removes the claudecat binary symlink. After completing,
prints the data directory path so the user can verify or manually remove any
remaining files.
"""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

DB_PATH = os.environ.get('CLAUDECAT_DB_PATH',
                          os.path.expanduser('~/.claudecat/catalog.db'))
DATA_DIR = os.path.dirname(DB_PATH)
DEFAULT_INSTALL_DIR = '/usr/local/bin'


def main():
    parser = argparse.ArgumentParser(
        description='Remove claudecat hook, database, and binary symlink'
    )
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')
    parser.add_argument('--install-dir', default=DEFAULT_INSTALL_DIR,
                        metavar='DIR',
                        help=f'Directory where claudecat binary was installed (default: {DEFAULT_INSTALL_DIR})')
    args = parser.parse_args()

    binary = os.path.join(args.install_dir, 'claudecat')
    hook_installed = _check_hook_installed()
    db_exists = os.path.exists(DB_PATH)
    binary_is_symlink = os.path.islink(binary)
    binary_exists = os.path.exists(binary)

    if not hook_installed and not db_exists and not binary_is_symlink:
        if binary_exists:
            print(f"Warning: '{binary}' exists but is not a symlink — not removing.")
            print("         Remove it manually if needed.")
        else:
            print("Nothing to remove — hook is not installed, database does not exist, "
                  f"and no symlink found at {binary}.")
        _print_data_dir()
        sys.exit(0)

    print("The following will be removed:")
    if hook_installed:
        print("  • claudecat stop hook from ~/.claude/settings.json")
    if db_exists:
        print(f"  • Database at {DB_PATH}")
    if binary_is_symlink:
        print(f"  • Binary symlink at {binary}")

    if not args.yes:
        try:
            answer = input("\nContinue? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer not in ('y', 'yes'):
            print("Aborted.")
            sys.exit(1)

    if hook_installed:
        _remove_hook()

    if db_exists:
        os.remove(DB_PATH)
        print(f"Database deleted: {DB_PATH}")

    if binary_is_symlink:
        os.remove(binary)
        print(f"Removed: {binary}")

    print("Implode complete.")
    _print_data_dir()


def _print_data_dir():
    print(f"\nclaudecat data directory: {DATA_DIR}")
    if os.path.isdir(DATA_DIR):
        contents = os.listdir(DATA_DIR)
        if contents:
            print("  Remaining files:")
            for name in sorted(contents):
                print(f"    {os.path.join(DATA_DIR, name)}")
        else:
            print("  (empty)")
    else:
        print("  (does not exist)")


def _check_hook_installed():
    from claudecat_install_hook import _load_settings, is_installed
    settings = _load_settings()
    return is_installed(settings)


def _remove_hook():
    from claudecat_uninstall_hook import _load_settings, _save_settings, is_installed, HOOK_MARKER, SETTINGS_PATH
    if not os.path.exists(SETTINGS_PATH):
        return
    settings = _load_settings()
    stop_hooks = settings.get('hooks', {}).get('Stop', [])
    cleaned = []
    for entry in stop_hooks:
        filtered = [h for h in entry.get('hooks', []) if HOOK_MARKER not in h.get('command', '')]
        if filtered:
            cleaned.append({**entry, 'hooks': filtered})
    settings['hooks']['Stop'] = cleaned
    if not settings['hooks']['Stop']:
        del settings['hooks']['Stop']
    if not settings['hooks']:
        del settings['hooks']
    _save_settings(settings)
    print("claudecat stop hook removed.")


if __name__ == '__main__':
    main()
