# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## What This Project Is

**To Wit** (`towit`) is a CLI tool that maintains a searchable SQLite catalog of Claude Code conversations, organized by topic. It auto-indexes sessions via a Claude Code stop hook, and provides search, list, export, and stats subcommands.

- **Entry point:** `bin/towit` (bash dispatcher; symlinked to `~/.local/bin/towit`)
- **Helpers:** `libexec/towit/*.py` (Python modules, one per subcommand)
- **Database:** `~/.towit/catalog.db` (SQLite WAL mode, overridable via `TOWIT_DB_PATH`)
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

- `towit_db.py` — Database abstraction layer; all SQL lives here
- `towit_setup.py` — Schema creation and migrations (adds columns if missing)
- `towit_index.py` — Core indexing: parses JSONL transcripts, calls `claude -p` to generate title/summary/topics, filters trivial sessions
- `towit_backfill.py` — Batch indexes existing `~/.claude/projects/` sessions
- `towit_hook.py` — Stop hook entry point; guarded by `TOWIT_INDEXING=1` env var to prevent recursion
- All other modules map 1:1 to subcommands

### Database Schema
Three tables: `conversations` (id, folder, cwd, started_at, last_active, title, summary, message_count, indexed_at), `topics` (id, name NOCASE), `conversation_topics` (many-to-many with CASCADE delete).

### JSONL Parsing
Reads from `~/.claude/projects/<encoded-path>/<session-id>.jsonl`. Sessions under `subagents/` subdirectories are skipped. Sessions with fewer than 2 user turns are skipped. Claude analyzes each session and returns `{"skip": true}` for trivial sessions.

### Re-indexing
Resumed conversations are re-indexed when new messages are detected. Previously assigned topics are passed as a hint to preserve continuity.

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `TOWIT_DB_PATH` | Override database path (used in tests) |
| `TOWIT_SETTINGS_PATH` | Override `~/.claude/settings.json` path (used in tests) |
| `TOWIT_INDEXING=1` | Set by hook to prevent recursive triggering |

## Test Structure

- `tests/test_helper.bash` — Shared BATS setup/teardown (temp dirs, mocks, fixtures)
- `tests/bin/towit.bats` — CLI integration tests
- `tests/bin/uninstall.bats` — Install/uninstall tests
- `tests/helpers/towit_*_test.py` — Python unit tests per module

## Security Constraints

- DB directory created with `0700`, file with `0600` permissions
- Path validation on all transcript paths and session IDs
- SQL uses parameterized queries only (no string interpolation in WHERE clauses)
- Subprocess environments scoped to an allowlist of env var prefixes
- Symlinked JSONL files excluded from backfill

## Release Process

Always update `CHANGELOG.md` before tagging and pushing a release.

## Directives

- **Plan first:** Before implementing any non-trivial change, write out your plan and pause for acceptance before touching code.
- **Test-driven development:** Write failing tests before writing implementation code. Run tests to confirm they fail, implement, then confirm they pass.
