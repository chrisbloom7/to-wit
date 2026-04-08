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
    'indexing': {
        'model', 'reindex_delta',
        'min_topics', 'max_topics',
        'min_keywords', 'max_keywords',
        'min_summary_sentences', 'max_summary_sentences',
        'transcript_max_chars',
    },
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

    def _get_range(self, section, min_key, max_key, default_min, default_max):
        """
        Return (min_val, max_val) for a paired min/max config entry.
        If either value has the wrong type or min > max, emits a warning and
        returns the defaults for both.
        """
        raw_min = self._get(section, min_key, default_min, int)
        raw_max = self._get(section, max_key, default_max, int)
        if raw_min > raw_max:
            print(
                f"Warning: config [{section}] {min_key!r} ({raw_min}) must not exceed "
                f"{max_key!r} ({raw_max}); using defaults "
                f"({default_min}, {default_max}).",
                file=sys.stderr,
            )
            return default_min, default_max
        return raw_min, raw_max

    @property
    def indexing_model(self) -> str:
        """Model passed to `claude -p`. 'default' uses the user's configured default."""
        return self._get('indexing', 'model', 'haiku', str)

    @property
    def indexing_reindex_delta(self) -> int:
        """Exchanges (user+assistant pairs) between re-analyses of a growing session."""
        return self._get('indexing', 'reindex_delta', 2, int)

    @property
    def indexing_min_topics(self) -> int:
        return self._get_range('indexing', 'min_topics', 'max_topics', 1, 5)[0]

    @property
    def indexing_max_topics(self) -> int:
        return self._get_range('indexing', 'min_topics', 'max_topics', 1, 5)[1]

    @property
    def indexing_min_keywords(self) -> int:
        return self._get_range('indexing', 'min_keywords', 'max_keywords', 15, 30)[0]

    @property
    def indexing_max_keywords(self) -> int:
        return self._get_range('indexing', 'min_keywords', 'max_keywords', 15, 30)[1]

    @property
    def indexing_min_summary_sentences(self) -> int:
        return self._get_range('indexing', 'min_summary_sentences', 'max_summary_sentences', 3, 6)[0]

    @property
    def indexing_max_summary_sentences(self) -> int:
        return self._get_range('indexing', 'min_summary_sentences', 'max_summary_sentences', 3, 6)[1]

    @property
    def indexing_transcript_max_chars(self) -> int:
        """Character cap applied to the transcript before sending to Claude."""
        return self._get('indexing', 'transcript_max_chars', 8000, int)

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
