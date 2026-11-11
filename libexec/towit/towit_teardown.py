#!/usr/bin/env python3
"""
towit_teardown — remove the To Wit hooks and delete the database.

Use before uninstalling To Wit to clean up all artifacts.
"""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from towit_config import config, database_sidecar_paths, remove_database_files


def main():
    db_path = config.db_path
    parser = argparse.ArgumentParser(description='Remove To Wit hook and database')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')
    args = parser.parse_args()

    hook_installed = _check_hook_installed()
    db_exists = os.path.exists(db_path)
    sidecars = database_sidecar_paths(db_path)

    if not hook_installed and not db_exists and not sidecars:
        print("Nothing to tear down — hook is not installed and database does not exist.")
        sys.exit(0)

    # Describe what will be removed
    print("The following will be removed:")
    if hook_installed:
        print("  • To Wit hooks from ~/.claude/settings.json")
    if db_exists:
        print(f"  • Database at {db_path}")
    for sidecar in sidecars:
        print(f"  • Leftover database file {sidecar}")

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

    print("Teardown complete.")


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
