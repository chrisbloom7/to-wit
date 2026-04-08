# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] - 2026-04-08

### Added

- **Indexing cost controls**: new `[indexing]` section in `~/.towit/config.toml` with 9 settings to tune Claude API spend:
  - `model` (default: `"haiku"`) — model passed to `claude -p`; use `"default"` to inherit your Claude Code default, or any alias/full model ID
  - `reindex_delta` (default: `2`) — exchanges (user+assistant pairs) that must occur before a resumed session is re-analyzed; prevents re-indexing on every turn of a long conversation
  - `min_topics` / `max_topics` (defaults: `1` / `5`) — range of topic tags Claude assigns per conversation
  - `min_keywords` / `max_keywords` (defaults: `15` / `30`) — range of keywords Claude extracts per conversation
  - `min_summary_sentences` / `max_summary_sentences` (defaults: `3` / `6`) — sentence range for the generated summary
  - `transcript_max_chars` (default: `8000`) — character cap on the transcript excerpt sent to Claude
- `towit setup --config` now generates a fully commented `[indexing]` section in the starter config file
- README `## Configuration` section documents all settings with a cost-estimates table

## [0.6.0] - 2026-04-08

### Added

- **Keywords field**: conversations are now indexed with 15–30 specific keywords extracted from the content — identifiers, method/class names, error messages, domain terminology, proper nouns, filenames, plan names, etc. Stored in a normalized `keywords` table with efficient indexed lookups.
- `towit search --topic`: new flag to include topics in search scope (topics are no longer searched by default).
- `towit list --keyword <name>`: new filter to list conversations by keyword.
- Keywords included in all output formats: table (Keywords column), JSON (`keywords` array), CSV (`keywords` column). Topics retained in JSON and CSV.

### Changed

- `towit search` default scope is now **keywords** instead of topics. Use `--topic` to include topics, `--all` to include keywords, topics, summaries, and titles.
- Analysis prompt expanded: summary now requests 3–6 sentences with emphasis on capturing context for wide-ranging conversations.
- Table output column renamed from "Topics" to "Keywords" in both `towit search` and `towit list`.

## [0.5.1] - 2026-04-07

### Fixed

- Stop hook no longer blocks Claude Code while waiting for the Claude API to analyze a session. Indexing now runs as a detached background process, so the hook exits immediately after validating the session path.

## [0.5.0] - 2026-04-06

### Added

- Config file support: To Wit now reads `~/.towit/config.toml` (TOML format) for persistent configuration. Generate a starter file with `towit setup --config` or `towit setup --full`.
- `towit setup --config` flag: generates a commented starter `~/.towit/config.toml` with all options documented; does nothing if the file already exists.

### Changed

- `TOWIT_DB_PATH` environment variable is deprecated. Set `[database] path` in `~/.towit/config.toml` instead. `TOWIT_DB_PATH` continues to work but emits a deprecation warning. Migration:

  ```toml
  # ~/.towit/config.toml
  [database]
  path = "/your/custom/path/catalog.db"
  ```

- Minimum Python version bumped to **3.11** (required for stdlib `tomllib`).
- `towit setup --full` now also generates the config file as its first step.

## [0.4.0] - 2026-04-06

### Changed

- Project renamed from **claudecat** to **To Wit**; CLI command is now `towit`
- All `CLAUDECAT_*` environment variables renamed to `TOWIT_*`: `TOWIT_DB_PATH`, `TOWIT_SETTINGS_PATH`, `TOWIT_INDEXING`
- Data directory moved from `~/.claudecat/` to `~/.towit/`; existing data must be moved manually: `mv ~/.claudecat ~/.towit`
- Hook path updated; re-run `towit install-hook` after upgrading to update the path in `~/.claude/settings.json`
- GitHub repository renamed from `chrisbloom7/claudecat` to `chrisbloom7/to-wit`

## [0.3.0] - 2026-04-03

### Added
- `search --all` flag: searches topics, summaries, and titles simultaneously; mutually exclusive with `--summary` and `--title`
- `search --format json|csv` and `list --format json|csv`: structured output for agent consumption; `--format json` emits a JSON array with `id`, `title`, `topics` (array), `cwd`, and `date` fields

### Removed
- `search --csv` and `list --csv` flags replaced by `--format csv` for consistency with `export --format`

### Changed
- `open` subcommand renamed to `resume` to match Claude Code's `--resume` flag terminology; `open` remains as a deprecated alias with a warning

### Fixed
- `backfill --dry-run` now applies the same `should_index` preflight filter as a live run, so short/trivial sessions are counted as skipped rather than inflating the "would index" total
- `setup` now runs schema migrations on existing databases, fixing a "no such column: message_count" error on backfill and indexing for databases created before that column was added

## [0.2.0] - 2026-03-31

### Added
- `implode` subcommand: full uninstall in one command — removes stop hook, database, and binary symlink, then prints the data directory path (with any remaining files) so nothing is left behind unexpectedly
- `uninstall` script now delegates to `claudecat implode` instead of duplicating the teardown + symlink removal logic
- Resumed conversations are now re-indexed when new messages are detected, instead of being silently skipped
- Re-indexing passes the previously assigned topics to Claude with a preference hint, reducing topic drift across sessions
- `message_count` column added to the `conversations` table; existing databases are migrated automatically on next `setup` or first use

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
