# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `implode` subcommand: full uninstall in one command — removes stop hook, database, and binary symlink, then prints the data directory path (with any remaining files) so nothing is left behind unexpectedly
- `uninstall` script now delegates to `claudecat implode` instead of duplicating the teardown + symlink removal logic

## [0.1.1] - 2026-03-31

### Changed
- Moved database default location from `~/.claude/catalog/` to `~/.claudecat/`
- Hook now installs to `~/.claude/settings.json` (global) instead of `settings.local.json`
- Hook install merges into an existing empty-matcher Stop entry rather than appending a separate one

### Security
- Database directory and file are now created with owner-only permissions (`0700`/`0600`)
- Hook error logging added: exceptions are written to `~/.claudecat/errors.log` with rotation (100 KB, 2 backups) instead of being silently discarded
- Hook path validation: `transcript_path` and derived JSONL paths are verified to be within `~/.claude/projects/`; `session_id` is validated against an alphanumeric format before use in path construction
- SQL injection guard: added comment and runtime assertion enforcing that dynamic WHERE clause conditions are hardcoded parameterized strings only
- Subprocess environment scoped to an allowlist of prefixes (`HOME`, `PATH`, `CLAUDE_*`, `ANTHROPIC_*`, etc.) instead of inheriting the full parent environment
- Symlinked JSONL files are excluded from backfill glob traversal
- `CLAUDECAT_SETTINGS_PATH` override validated to be within `~/.claude/` or the system temp directory
- JSON fallback regex changed to non-greedy to avoid large-span matches on long output
- CI `actions/checkout` pinned to SHA digest instead of mutable `v4` tag
