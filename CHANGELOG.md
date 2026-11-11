# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> This release changes existing behavior (the default scope of `search`, the default of `prune`, what `backfill` does, and which hook events are installed). To Wit is a 0.x project, so these behavior changes are made in a minor release rather than a major one. The notes under **Changed** and **Upgrading** explain how to get the old behavior back.

### Added

- **Full-text archive.** To Wit now stores the text of every user and assistant message (plus one-line tool-call stubs such as `[Bash] <description>` and truncated `[error]` results) in SQLite with FTS5, so conversations stay searchable after Claude Code deletes the transcript. Metadata generation by Claude is now optional enrichment, not a prerequisite for a conversation being found. Archiving is incremental and append-only, needs no API calls, and a message is capped at 50,000 characters.
- **Three hook events.** `towit install-hook` now registers `Stop`, `SessionEnd`, and `SessionStart` (matcher `startup`). `SessionEnd` captures the final state of a session; `SessionStart` runs a catch-up scan that archives (without any LLM calls) transcripts modified since the last scan, recovering sessions that ended without a hook. All work runs in a detached background process.
- `towit show <session-id> [--around <seq>] [--context <n>] [--format text|json]`: print archived messages (the **Turn** number in search results is the 0-based `seq`). Works after the transcript is gone.
- `towit forget <session-id> | --repo <path|name> | --folder <path> [--yes]`: permanently delete conversations (messages, FTS entries, topics, keywords) and tombstone the id so backfill, hooks, and the catch-up scan never re-ingest it. Cleanup is physical (`secure_delete`, FTS `optimize`, `VACUUM`, WAL truncate); re-running `forget <id>` on an already-forgotten id retries it.
- `towit search --only text|metadata` and `--repo <path|name>` (matches a repo key exactly or by its final path component; the key is the git common directory of the session's working directory, resolved once at first archive and kept on re-ingest, so sessions first archived after their worktree was deleted do not group under the main repo). Results gain a Turn and Snippet column in the table, and `seq`, `snippet`, and `score` fields in JSON and CSV.
- `towit prune --archive` and `--yes`, and a "Likely removed by claude purge" report listing archived conversations whose whole project folder is gone.
- **Configuration:** `[ingest]` section (`redact`, `extra_patterns`, `include_subagents`, `folders`) and `[indexing] enabled` (set `false` for archive-only operation with zero API spend).
- **Secret redaction.** Secret-shaped strings are replaced with `[REDACTED:<kind>]` before text is archived and before the indexing transcript is sent to `claude -p`. Best effort and ingest-time only. `towit export --summarize` still sends the original, unredacted transcript, and `export --topic --summarize` sends stored titles and summaries, which for conversations indexed by 0.8.2 or earlier may derive from unredacted transcripts.
- `towit doctor` (now up to 17 checks): SQLite FTS5 availability; archive schema (tables, `PRAGMA user_version`) and an FTS5 integrity check that fails only on real corruption and warns if the database is locked or read-only; all three hook events registered; hook command paths exist (fail if none resolve, warn if only some do); a warning when `disableAllHooks` is true in the settings file it reads.
- `towit stats` prints archived and metadata-only conversation counts, archived message count, and database size in their own block.
- The schema migrates automatically on first use: databases created by earlier versions are upgraded in place (tracked with `PRAGMA user_version`), and `towit setup` still works as before.

### Changed

- **`towit search` default scope now includes message text** together with keywords, titles, and summaries (previously keywords only). Conversations with a metadata match rank first, then by `bm25` relevance of the best message. Use `--only metadata` for the old scope. Text-only matches are capped at 50; arguments containing spaces are exact phrases; FTS5 operators in input are treated literally.
- **`towit prune` no longer removes archived conversations by default**; it removes only entries that were never archived and whose transcripts are missing. Use `prune --archive` for the old behavior.
- `towit backfill` now archives message text for every transcript on disk (and only runs the LLM for sessions that are not yet indexed, unless `--force`). `--dry-run` reports what would be indexed.
- The transcript sent to Claude for analysis is now redacted.
- The hooks archive in a detached background process; LLM indexing runs after archiving unless `[indexing] enabled = false`. `Stop` and `SessionEnd` can both trigger indexing for one session, which may cost an extra API call.
- JSON search output keeps the existing `id` key (it does not become `conversation_id`) and adds `seq`, `snippet`, and `score`.
- Teardown, implode, and doctor wording now refers to the hooks rather than "the stop hook". `teardown` and `implode` delete the archive.

### Upgrading

- Existing installs only have the `Stop` hook. Re-run `towit install-hook` to add `SessionEnd` and `SessionStart` (`towit doctor` warns until you do), then `towit backfill` to archive transcripts that are still on disk.
- **`claude purge` and Claude Code's retention sweep do not delete the To Wit archive.** Use `towit forget` to remove data.
- The archive adds roughly 0.7 MB per top-level session on a heavy-use project (see the README).

### Fixed

- `towit setup --full` now generates `~/.towit/config.toml` as documented.

### Security

- Secret redaction before archiving and before the indexing transcript is sent to Claude (best effort; see SECURITY.md). The `export --summarize` paths are not redacted (see Added).
- `towit forget` provides permanent, physical deletion of archived conversations, with a tombstone so they are not re-ingested.
- `towit show` strips terminal control sequences from archived text before printing it.
- `towit export --summarize` now runs `claude` with the scoped environment allowlist (as indexing already did) instead of the full environment.
- FTS5 search input is escaped into quoted phrases and bound as a parameter; the `git rev-parse` subprocess used for repo grouping uses a list command, the scoped environment, and a 5-second timeout.

## [0.8.2] - 2026-04-17

### Fixed

- Add `--no-session-persistence` to `claude -p` analysis calls so towit's indexing sessions are not saved to disk and do not appear in Claude Code's `/resume` picker.

## [0.8.1] - 2026-04-08

### Fixed

- README Usage section: added missing `doctor` subcommand, corrected `export --format` to show `md|json`, fixed `setup --hook` wording, reordered `prune` to match `towit help` output.

## [0.8.0] - 2026-04-08

### Added

- **`towit doctor` subcommand**: runs 15 health checks across 5 categories and prints a plain-text report with `[PASS]`, `[WARN]`, or `[FAIL]` per check. Exits 0 when all checks pass or only warnings are present; exits 1 on any failure. Never performs automatic remediation — each failing check includes a remediation hint.
  - **Python**: version ≥ 3.11 required for TOML config support
  - **Claude CLI**: `claude` binary present on `$PATH`
  - **Config file**: existence, TOML validity, unknown section/key warnings, `TOWIT_DB_PATH` deprecation warning
  - **Database**: file exists, read/write permissions (600), directory permissions (700), required tables present, schema up to date
  - **Stop hook**: Claude Code `settings.json` exists, hook registered, hook script present on disk
- Color output in `towit doctor`: `[PASS]` in green, `[WARN]` in bold yellow, `[FAIL]` in red, remediation hints in dark yellow. Colors are applied only when stdout is a TTY; plain text otherwise.

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
