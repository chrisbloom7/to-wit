#!/usr/bin/env python3
"""
towit_implode — remove the To Wit hook, database, and binary symlink.

Performs a full uninstall: removes the To Wit hooks from ~/.claude/settings.json,
deletes the database, and removes the towit binary symlink. After completing,
prints the data directory path so the user can verify or manually remove any
remaining files.
"""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from towit_config import config, database_sidecar_paths, remove_database_files

DEFAULT_INSTALL_DIR = os.path.expanduser('~/.local/bin')


def is_homebrew_install(script_path):
    """True when script_path lives inside a Homebrew Cellar (a whole /Cellar/ path component)."""
    return '/Cellar/' in script_path


def main():
    db_path = config.db_path
    data_dir = os.path.dirname(db_path)
    parser = argparse.ArgumentParser(
        description='Remove To Wit hook, database, and binary symlink'
    )
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')
    parser.add_argument('--install-dir', default=DEFAULT_INSTALL_DIR,
                        metavar='DIR',
                        help=f'Directory where towit binary was installed (default: {DEFAULT_INSTALL_DIR})')
    args = parser.parse_args()

    # Under Homebrew the binary symlink belongs to brew; leave it for `brew uninstall`.
    homebrew = is_homebrew_install(os.path.abspath(__file__))
    binary = os.path.join(args.install_dir, 'towit')
    hook_installed = _check_hook_installed()
    db_exists = os.path.exists(db_path)
    sidecars = database_sidecar_paths(db_path)
    binary_is_symlink = not homebrew and os.path.islink(binary)
    binary_exists = not homebrew and os.path.exists(binary)

    if not hook_installed and not db_exists and not sidecars and not binary_is_symlink:
        if homebrew:
            print("Nothing to remove — hook is not installed and database does not exist.")
        elif binary_exists:
            print(f"Warning: '{binary}' exists but is not a symlink — not removing.")
            print("         Remove it manually if needed.")
        else:
            print("Nothing to remove — hook is not installed, database does not exist, "
                  f"and no symlink found at {binary}.")
        _print_data_dir(data_dir)
        if homebrew:
            _print_brew_hint()
        sys.exit(0)

    print("The following will be removed:")
    if hook_installed:
        print("  • To Wit hooks from ~/.claude/settings.json")
    if db_exists:
        print(f"  • Database at {db_path}")
    for sidecar in sidecars:
        print(f"  • Leftover database file {sidecar}")
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

    if db_exists or sidecars:
        remove_database_files(db_path)
        if db_exists:
            print(f"Database deleted: {db_path}")
        else:
            print("Leftover database files deleted")

    if binary_is_symlink:
        os.remove(binary)
        print(f"Removed: {binary}")

    print("Implode complete.")
    _print_data_dir(data_dir)
    if homebrew:
        _print_brew_hint()


def _print_brew_hint():
    print("\nTo Wit was installed with Homebrew. To finish removing it, run: brew uninstall towit")


def _print_data_dir(data_dir):
    print(f"\nTo Wit data directory: {data_dir}")
    if os.path.isdir(data_dir):
        contents = os.listdir(data_dir)
        if contents:
            print("  Remaining files:")
            for name in sorted(contents):
                print(f"    {os.path.join(data_dir, name)}")
        else:
            print("  (empty)")
    else:
        print("  (does not exist)")


def _check_hook_installed():
    from towit_uninstall_hook import _load_settings, is_installed
    settings = _load_settings()
    return is_installed(settings)


def _remove_hook():
    from towit_uninstall_hook import _load_settings, _save_settings, remove_hooks, SETTINGS_PATH
    if not os.path.exists(SETTINGS_PATH):
        return
    settings = _load_settings()
    remove_hooks(settings)
    _save_settings(settings)
    print("To Wit hooks removed.")


if __name__ == '__main__':
    main()
