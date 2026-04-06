#!/usr/bin/env python3
"""
towit_config — Configuration loader for To Wit.

Loads ~/.towit/config.toml (or TOWIT_CONFIG_PATH) and exposes a Config
object with typed property accessors. Missing file → silent defaults.
Bad TOML or wrong types → warning to stderr, defaults used.

This module is imported by other towit scripts; it is not run directly.
"""

import os
import sys

try:
    import tomllib
except ImportError:
    raise SystemExit("towit requires Python 3.11+ for TOML config support.")

_DEFAULT_CONFIG_PATH = os.path.expanduser('~/.towit/config.toml')
_DEFAULT_DB_PATH = os.path.expanduser('~/.towit/catalog.db')

CONFIG_PATH = os.environ.get('TOWIT_CONFIG_PATH', _DEFAULT_CONFIG_PATH)

# Registry of known config sections and their known keys.
# Used to emit warnings for unrecognized entries.
_KNOWN_KEYS = {
    'database': {'path'},
}


class Config:
    def __init__(self, path=None):
        self._path = path if path is not None else CONFIG_PATH
        self._data = self._load()
        self._warn_unknown_keys()
        self._deprecated_warned = False

    def _load(self):
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, 'rb') as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            print(
                f"Warning: could not parse config file {self._path}: {exc}",
                file=sys.stderr,
            )
            return {}

    def _warn_unknown_keys(self):
        for section, value in self._data.items():
            if section not in _KNOWN_KEYS:
                print(
                    f"Warning: unknown config section [{section}]; ignoring.",
                    file=sys.stderr,
                )
                continue
            if not isinstance(value, dict):
                continue
            for key in value:
                if key not in _KNOWN_KEYS[section]:
                    print(
                        f"Warning: unknown config key [{section}] {key!r}; ignoring.",
                        file=sys.stderr,
                    )

    def _get(self, section, key, default, expected_type):
        section_data = self._data.get(section, {})
        if not isinstance(section_data, dict):
            return default
        if key not in section_data:
            return default
        value = section_data[key]
        if not isinstance(value, expected_type):
            print(
                f"Warning: config [{section}] {key!r} must be a "
                f"{expected_type.__name__}; using default ({default!r}).",
                file=sys.stderr,
            )
            return default
        return value

    @property
    def db_path(self) -> str:
        """Resolved database path. TOWIT_DB_PATH env var overrides (deprecated)."""
        env_db_path = os.environ.get('TOWIT_DB_PATH')
        if env_db_path:
            if not self._deprecated_warned:
                print(
                    "Warning: TOWIT_DB_PATH is deprecated. "
                    "Set [database] path in your config file instead.",
                    file=sys.stderr,
                )
                self._deprecated_warned = True
            return env_db_path
        raw = self._get('database', 'path', _DEFAULT_DB_PATH, str)
        return os.path.expanduser(raw)


config = Config()
