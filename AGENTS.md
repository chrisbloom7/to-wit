# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## What This Project Is

**To Wit** (`towit`) is a CLI tool that maintains a full-text SQLite archive of Claude Code conversations (message text, searchable with FTS5, that outlives Claude Code's own transcript retention) plus LLM-generated metadata (title, summary, keywords, topics). It archives sessions automatically through three Claude Code hooks (Stop, SessionEnd, SessionStart), and provides search, show, list, export, forget, prune, and stats subcommands.

- **Entry point:** `bin/towit` (bash dispatcher; symlinked to `~/.local/bin/towit`)
- **Helpers:** `libexec/towit/*.py` (Python modules, one per subcommand)
- **Database:** `~/.towit/catalog.db` (SQLite WAL mode; set `[database] path` in `~/.towit/config.toml`, or the deprecated `TOWIT_DB_PATH`)
- **Tests:** `tests/` (BATS integration tests + Python unit tests)

## Commands

```bash
# Run all tests (BATS + Python)
./run-tests

# Run a specific test file
./run-tests tests/bin/towit.bats
./run-tests tests/helpers/towit_search_test.py

# Filter tests by name pattern
./run-tests --filter "setup"

# Install test dependency (once)
brew install bats-core
```

No build step required — it's a bash/Python CLI tool.

## Architecture

### Dispatcher Pattern
`bin/towit` resolves its real path (symlink-safe), sets `HELPERS_DIR=libexec/towit/`, then dispatches to `towit_<subcommand>.py` via `python3 "$HELPERS_DIR/towit_$subcommand.py"`.

### Python Modules (libexec/towit/)

Subcommand modules map 1:1 to `bin/towit` cases (`towit_search.py`, `towit_show.py`, `towit_forget.py`, `towit_prune.py`, `towit_stats.py`, `towit_doctor.py`, ...). The modules below are not subcommands:

- `towit_config.py` — Loads `~/.towit/config.toml` (typed accessors, warnings for unknown keys), `safe_subprocess_env()`, session-id and transcript-path validation, the rotating error logger
- `towit_db.py` — Database abstraction layer; all SQL lives here (schema, migrations, search, forget, archive writes)
- `towit_ingest.py` — Archive ingest: parses JSONL into messages plus tool stubs, redacts, stores append-only, resolves `repo_key` (git common dir, else the cwd) once at first ingest (the stored key is kept afterwards unless it is NULL), runs the `SessionStart` catch-up scan. Its `main()` is the detached process the hook spawns (archive, then LLM indexing)
- `towit_sanitize.py` — Strips terminal control sequences from archived text before it is printed (`show` text output, and the table output of `search` and `list`, which also collapse newlines)
- `towit_redact.py` — Best-effort, pattern-based secret redaction (`[REDACTED:<kind>]`)
- `towit_index.py` — LLM indexing: parses JSONL prose, calls `claude -p` to generate title/summary/keywords/topics, filters trivial sessions
- `towit_hook.py` — Hook entry point for the Stop, SessionEnd, and SessionStart events; dispatches on the payload's `hook_event_name`, validates the transcript path, and spawns a detached `towit_ingest.py`. Guarded by `TOWIT_INDEXING=1` env var to prevent recursion
- `towit_backfill.py` (a subcommand) archives and indexes existing `~/.claude/projects/` sessions in batch; `towit_setup.py` creates the schema and runs migrations

### Hook Flow

`towit install-hook` registers `towit_hook.py` for `Stop`, `SessionEnd`, and `SessionStart` (matcher `startup`). The hook reads the payload, and for `Stop`/`SessionEnd` validates `transcript_path` (inside `~/.claude/projects/`, not a subagent) and spawns `towit_ingest.py <path>` with `start_new_session=True`; for `SessionStart` it spawns `towit_ingest.py --catch-up`. The detached process archives the transcript, then runs LLM indexing unless `[indexing] enabled = false` or the session is a subagent. The catch-up scan archives (never calls the LLM) every transcript modified since the `last_catch_up` timestamp in the `meta` table, minus a 60 s slack. The hook always exits 0.

### Database Schema
`conversations` (id, folder, cwd, started_at, last_active, title, summary, message_count, indexed_at, plus archive columns `tail_hash`, `source_path`, `archived`, `archived_message_count`, `repo_key`), `topics` (id, name NOCASE), `conversation_topics` (many-to-many with CASCADE delete), `keywords` (id, name NOCASE), `conversation_keywords` (many-to-many with CASCADE delete), `messages` (id, conversation_id, seq, role, ts, text; `UNIQUE (conversation_id, seq)`, cascades from `conversations`), `messages_fts` (FTS5 external-content index over `messages.text`, tokenizer `unicode61 tokenchars '_-.'`, kept in sync by insert/delete/update triggers), `forgotten` (tombstones: id, forgotten_at), and `meta` (key/value, e.g. the catch-up timestamp).

`message_count` is the LLM-facing prose-only count that drives `reindex_delta`; `archived_message_count` counts archived rows including tool stubs. `archived` is 1 once messages are stored (0 for catalog rows that predate the archive). Schema changes are applied by `run_migrations` and stamped in `PRAGMA user_version` (`SCHEMA_VERSION`); `Database.validate()` migrates an older database automatically on first use.

### JSONL Parsing
Reads from `~/.claude/projects/<encoded-path>/<session-id>.jsonl`. The archive parser (`towit_ingest.parse_transcript`) stores user and assistant text, one-line tool stubs (`[Tool] <value>`, 200-char cap) and failed tool results (`[error] ...`, 300-char cap); a single message is capped at 50,000 characters; a partial last line (transcript mid-write) is tolerated. Sessions under `subagents/` are skipped unless `[ingest] include_subagents = true`, and are never LLM-indexed. Symlinked JSONL files and folders not matching `[ingest] folders` are skipped, as are sessions with fewer than 2 user turns. `towit_index.parse_jsonl` is a separate prose-only parser for the LLM; Claude analyzes each session and returns `{"skip": true}` for trivial sessions, which only suppresses metadata and never archiving.

### Re-indexing
The archive is append-only: each ingest compares the stored tail hash to the transcript and stores only new messages by `seq`; a mismatch (compaction or rewrite) deletes and re-ingests that conversation in one transaction. This is independent of the LLM reindex: resumed conversations are re-analyzed only when `reindex_delta` exchanges have been added, and previously assigned topics are passed as a hint to preserve continuity. `forgotten` ids are never ingested or indexed.

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `TOWIT_CONFIG_PATH` | Override `~/.towit/config.toml` path (used in tests) |
| `TOWIT_DB_PATH` | Override database path (deprecated in favor of `[database] path`; used in tests) |
| `TOWIT_SETTINGS_PATH` | Override `~/.claude/settings.json` path (used in tests) |
| `TOWIT_INDEXING=1` | Set on towit's own `claude -p` calls so the hooks do not recurse |
| `TOWIT_RELEASE_CHECK=1` | Test-only: enables the release-gate check that `CHANGELOG.md` has `[Unreleased]` content |

## Test Structure

- `tests/test_helper.bash` — Shared BATS setup/teardown (temp dirs, mocks, fixtures)
- `tests/bin/towit.bats` — CLI integration tests
- `tests/bin/uninstall.bats` — Install/uninstall tests
- `tests/helpers/towit_*_test.py` — Python unit tests per module (`towit_ingest_test.py`, `towit_redact_test.py`, `towit_show_test.py`, `towit_forget_test.py`, `towit_config_test.py`, ... alongside the original per-subcommand files)
- `tests/helpers/docs_consistency_test.py` — Checks that README, AGENTS.md, SECURITY.md, the help text, and the config template agree with the code (subcommands, flags, config keys, hook events, tables, env vars, the subprocess allowlist). When it fails after you add a flag, config key, table, or env var, update the docs it names. Run with `TOWIT_RELEASE_CHECK=1` to also require `CHANGELOG.md` `[Unreleased]` content (a release gate)

## Security Constraints

- DB directory created with `0700`, file with `0600` permissions
- Path validation on all transcript paths and session IDs
- SQL uses parameterized queries only (no string interpolation in WHERE clauses); FTS5 queries are built from quoted phrases (`build_match_expression`) bound as a parameter
- Subprocess environments (the `claude` calls and the `git rev-parse` in `resolve_repo_key`) are scoped to an allowlist of env var prefixes via `safe_subprocess_env()`; subprocesses use list form, never `shell=True`
- Secrets are redacted (`towit_redact`) before text is stored and before the indexing transcript is sent to `claude -p`; redaction is best effort and ingest-time only. `towit export --summarize` sends the original, unredacted transcript, and `export --topic --summarize` sends stored titles and summaries (which rows indexed by 0.8.2 or earlier may have derived from unredacted transcripts)
- `towit forget` tombstones ids in `forgotten`, and physically removes data (`secure_delete`, FTS `optimize`, `VACUUM`, WAL truncate)
- Symlinked JSONL files excluded from backfill, the catch-up scan, and ingest

## Release Process

Use the **`release-towit` skill** (`.claude/skills/release-towit/SKILL.md`) for all releases. Read and follow it with the Read tool when the user asks to cut a release, bump a version, tag a release, or publish a new version. It covers: determining the version, auditing help text and README, updating CHANGELOG, committing with diff approval, tagging, and pushing.

Never bypass the skill — it catches README drift and other issues that ad-hoc releases miss.

## Directives

- **Plan first:** Before implementing any non-trivial change, write out your plan and pause for acceptance before touching code.
- **Test-driven development:** Write failing tests before writing implementation code. Run tests to confirm they fail, implement, then confirm they pass.
