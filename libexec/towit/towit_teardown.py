#!/usr/bin/env python3
"""
towit_teardown — remove the To Wit stop hook and delete the database.

Use before uninstalling To Wit to clean up all artifacts.
"""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

DB_PATH = os.environ.get('TOWIT_DB_PATH',
                          os.path.expanduser('~/.towit/catalog.db'))


def main():
    parser = argparse.ArgumentParser(description='Remove To Wit hook and database')
    parser.add_argument('--yes', '-y', action='store_true',
                        help='Skip confirmation prompt')
    args = parser.parse_args()

    hook_installed = _check_hook_installed()
    db_exists = os.path.exists(DB_PATH)

    if not hook_installed and not db_exists:
        print("Nothing to tear down — hook is not installed and database does not exist.")
        sys.exit(0)

    # Describe what will be removed
    print("The following will be removed:")
    if hook_installed:
        print("  • To Wit stop hook from ~/.claude/settings.json")
    if db_exists:
        print(f"  • Database at {DB_PATH}")

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
        from towit_uninstall_hook import main as uninstall_hook
        # Redirect: call the logic directly, not the main() which exits
        _remove_hook()

    if db_exists:
        os.remove(DB_PATH)
        print(f"Database deleted: {DB_PATH}")

    print("Teardown complete.")


def _check_hook_installed():
    from towit_install_hook import _load_settings, is_installed
    settings = _load_settings()
    return is_installed(settings)


def _remove_hook():
    from towit_uninstall_hook import _load_settings, _save_settings, is_installed, HOOK_MARKER, SETTINGS_PATH
    import os
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
    print("To Wit stop hook removed.")


if __name__ == '__main__':
    main()
