#!/usr/bin/env python3
"""
claudecat_setup — Initialize the claudecat catalog database.

Usage:
    python3 claudecat_setup.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claudecat_db import Database, DB_PATH


def main():
    db_path = os.environ.get(
        'CLAUDECAT_DB_PATH',
        os.path.expanduser('~/.claudecat/catalog.db')
    )

    if os.path.isfile(db_path):
        print(f"Database already initialized at {db_path}")
        sys.exit(0)

    parent = os.path.dirname(db_path)
    old_umask = os.umask(0o077)
    try:
        os.makedirs(parent, exist_ok=True)
        db = Database(db_path)
        db.create_schema()
    finally:
        os.umask(old_umask)
    print(f"Database initialized at {db_path}")


if __name__ == '__main__':
    main()
