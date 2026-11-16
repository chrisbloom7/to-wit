# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## What This Project Is

**To Wit** (`towit`) is a CLI tool that maintains a full-text SQLite archive of Claude Code conversations (message text, searchable with FTS5, that outlives Claude Code's own transcript retention) plus LLM-generated metadata (title, summary, keywords, topics). It archives sessions automatically through three Claude Code hooks (Stop, SessionEnd, SessionStart), and provides subcommands to search, list, show, resume, open, export, forget, prune, backfill and report on it (`stats`, `doctor`) and to manage the install (`setup`, `install-hook`, `uninstall-hook`, `teardown`, `implode`). `bin/towit help` is the canonical list.

- **Entry point:** `bin/towit` (bash dispatcher; symlinked to `~/.local/bin/towit`)
- **Version:** `libexec/towit/VERSION` (one line, no `v` prefix; `towit version` and `towit doctor` print it; the release skill writes it, and `docs_consistency_test.py` requires it to equal the newest `CHANGELOG.md` release)
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

# Lint like the CI ShellCheck job (every tracked shell script)
shellcheck --shell=bash --severity=warning bin/towit install uninstall run-tests completions/towit.bash tests/test_helper.bash .claude/hooks/docs-drift.sh
```

Requires python3 (3.11+, standard library only, built with SQLite FTS5), bats-core and jq (jq and `rg` are used by `.claude/hooks/docs-drift.sh`, not by the CLI or `./run-tests`). No build step required — it's a bash/Python CLI tool. CI (`.github/workflows/ci.yml`) runs the tests on macOS and Linux with Python 3.11 and 3.x, an install smoke test and the ShellCheck job; `ci-gate` is the single required check. `run-tests` still has Ruby spec handling, but the repo has no Ruby files, so ignore it.

## Architecture

### Dispatcher Pattern
`bin/towit` resolves its real path (symlink-safe), sets `HELPERS_DIR=libexec/towit/`, then dispatches to `towit_<subcommand>.py` via `python3 "$HELPERS_DIR/towit_$subcommand.py"`.

### Python Modules (libexec/towit/)

Subcommand modules map 1:1 to `bin/towit` cases (`towit_search.py`, `towit_show.py`, `towit_resume.py`, `towit_forget.py`, `towit_prune.py`, `towit_stats.py`, `towit_doctor.py`, `towit_teardown.py`, `towit_uninstall_hook.py`, ...). The modules below are not subcommands:

- `towit_config.py` — Loads `~/.towit/config.toml` (typed accessors, warnings for unknown keys), `safe_subprocess_env()`, session-id and transcript-path validation, the rotating error logger
- `towit_db.py` — Database abstraction layer; all SQL lives here (schema, migrations, search, forget, archive writes). Search ranking, `_repo_filter` (`--repo`), the optional `role` filter and `get_messages` are documented in the module and function docstrings; read them before changing a query (`_repo_filter` deliberately avoids `LIKE`, so wildcards in `--repo` stay literal). `towit_forget` prints `repo_keys_for_scope` before the prompt (also with `--yes`)
- `towit_ingest.py` — Archive ingest: parses JSONL into messages plus tool stubs, redacts, stores append-only, resolves `repo_key` (git common dir, else the cwd) once at first ingest (the stored key is kept afterwards unless it is NULL), runs the `SessionStart` catch-up scan. Its `main()` is the detached process the hook spawns (archive, then LLM indexing)
- `towit_pipe.py` — `run_cli(main)` and `quiet_broken_pipe()`: a closed stdout pipe (for example `| head`) ends the process quietly with status 141. Details in the module docstring
- `towit_sanitize.py` — Strips terminal control sequences from archived text before it is printed (`show` text output, and the table output of `search` and `list`, which also collapse newlines)
- `towit_table.py` — `fit_widths`, `truncate`, `pad` and `display_width` for the text tables of `search` and `list`; widths are measured in terminal display cells (CJK and wide emoji take two), not characters; never touches the ID column. Details in the module docstring
- `towit_redact.py` — Best-effort, pattern-based secret redaction (`[REDACTED:<kind>]`)
- `towit_index.py` — LLM indexing: parses JSONL prose, calls `claude -p` to generate title/summary/keywords/topics, filters trivial sessions
- `towit_install_hook.py` — Registers/repairs hooks; writes `TOWIT_PYTHON` (if valid) as the hook interpreter
- `towit_skill.py` — Installs, removes and checks the Claude Code plugin through `claude plugin ... --json` (user scope). `install(version)` pins the `to-wit` marketplace to `chrisbloom7/to-wit#v<version>` and, when the declared source or ref differs, removes the marketplace (which uninstalls its plugins), re-adds it and reinstalls. `status()` returns unavailable, missing, stale or ok for `towit_doctor`; `present()` and `uninstall()` serve `towit_implode`. Its `main()` (`install` or `uninstall`) is what `bin/towit setup --skill` runs
- `towit_implode.py` — Full uninstall; under a Homebrew Cellar it skips the binary symlink and prints `brew uninstall towit`
- `towit_hook.py` — Hook entry point for the Stop, SessionEnd, and SessionStart events; dispatches on the payload's `hook_event_name`, validates the transcript path, and spawns a detached `towit_ingest.py`. Guarded by `TOWIT_INDEXING=1` env var to prevent recursion
- `towit_backfill.py` (a subcommand) archives and indexes existing `~/.claude/projects/` sessions in batch; `towit_setup.py` creates the schema and runs migrations

### Shell Completions

`completions/towit.bash` and `completions/_towit` (Bash and Zsh, opt-in, static: they never read the archive) complete the subcommands, their flags and the fixed values of `--format`, `--role` and `--only`. Add a new or renamed flag to both files; `tests/helpers/towit_completion_test.py` compares them with the dispatcher and each module's argparse definitions and fails on drift

### Hook Flow

`towit install-hook` registers `towit_hook.py` for `Stop`, `SessionEnd`, and `SessionStart` (matcher `startup`). The hook reads the payload, and for `Stop`/`SessionEnd` validates `transcript_path` (inside `~/.claude/projects/`, not a subagent) and spawns `towit_ingest.py <path>` with `start_new_session=True`; for `SessionStart` it spawns `towit_ingest.py --catch-up`. The detached process archives the transcript, then runs LLM indexing unless `[indexing] enabled = false` or the session is a subagent. The catch-up scan archives (never calls the LLM) every transcript modified since the `last_catch_up` timestamp in the `meta` table, minus a 60 s slack; the stamp is not advanced when any transcript errors, so those files are retried on the next scan. The hook always exits 0.

### Claude Code Plugin

`.claude-plugin/marketplace.json` declares the `to-wit` marketplace with one plugin, `towit`, sourced from `plugins/towit/` (`.claude-plugin/plugin.json`, `skills/towit/SKILL.md`). The skill is guidance only: no hooks, no MCP server. `plugin.json` has no `version` key on purpose (the install is pinned by git tag, so there is no second version to keep in sync), which is also why the tests run `claude plugin validate` without `--strict`. `docs_consistency_test.py` (`TestPlugin`) checks that every subcommand and flag the skill mentions exists in the CLI and that the skill keeps its untrusted-data and no-destructive-commands guardrails; update `SKILL.md` when a flag it names changes. `towit setup --skill` installs it (opt-in, not part of `--full`), `towit doctor` reports it and `towit implode` removes it.

### Database Schema
`conversations` (id, folder, cwd, started_at, last_active, title, summary, message_count, indexed_at, plus archive columns `tail_hash`, `source_path`, `archived`, `archived_message_count`, `repo_key`), `topics` (id, name NOCASE), `conversation_topics` (many-to-many with CASCADE delete), `keywords` (id, name NOCASE), `conversation_keywords` (many-to-many with CASCADE delete), `messages` (id, conversation_id, seq, role, ts, text; `UNIQUE (conversation_id, seq)`, cascades from `conversations`), `messages_fts` (FTS5 external-content index over `messages.text`, tokenizer `porter unicode61 tokenchars '_-.'` (English stemming), kept in sync by insert/delete/update triggers), `forgotten` (tombstones: id, forgotten_at), and `meta` (key/value, e.g. the catch-up timestamp).

`message_count` is the LLM-facing prose-only count that drives `reindex_delta`. It is also recorded when the LLM skips a session or fails, so an unchanged session is not re-sent to `claude -p` until it grows by `reindex_delta` exchanges; `archived_message_count` counts archived rows including tool stubs. `archived` is 1 once messages are stored (0 for catalog rows that predate the archive). Schema changes are applied by `run_migrations` and stamped in `PRAGMA user_version` (`SCHEMA_VERSION`); `Database.validate()` migrates an older database automatically on first use. The v2 migration (Porter stemming) drops and recreates `messages_fts` and its three triggers and runs `rebuild` in the same transaction, gated on the index definition (no `porter` in its `sqlite_master` sql) rather than only the version, so it is idempotent and a fresh database is not rebuilt.

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
| `TOWIT_PYTHON` | Interpreter used by `bin/towit` and written into the hook command (absolute path; set by the Homebrew wrapper; defaults to `python3`) |
| `TOWIT_INDEXING=1` | Set on towit's own `claude -p` calls so the hooks do not recurse |
| `TOWIT_RELEASE_CHECK=1` | Test-only: enables the release-gate check that `CHANGELOG.md` has `[Unreleased]` content |

## Test Structure

- `tests/test_helper.bash` — Shared BATS setup/teardown (temp dirs, mocks, fixtures). `_setup_common` puts a stub `claude` on PATH that reports no plugins and accepts everything, so no test can query or remove the developer's real plugins; a test that needs another behavior writes its own `mock_bin/claude`, and one that needs `claude` absent must delete it. `setup` points `TOWIT_SETTINGS_PATH` at a temp file so no test can edit the real `~/.claude/settings.json`; pass your own value only when a test needs a specific settings file
- `tests/bin/towit.bats` — CLI integration tests
- `tests/bin/install.bats` — `install` script tests
- `tests/bin/uninstall.bats` — `uninstall` script tests
- `tests/helpers/towit_*_test.py` — Python unit tests per module (`towit_ingest_test.py`, `towit_redact_test.py`, `towit_show_test.py`, `towit_forget_test.py`, `towit_config_test.py`, ... alongside the original per-subcommand files). A test that can reach `get_error_logger()` must not write to the real `~/.towit/errors.log`: `towit_ingest_test.py` redirects `towit_config.CONFIG_PATH` and resets the `towit.hook` logger in `setUpModule` (the logger caches its handler per process)
- `tests/helpers/towit_completion_test.py` — Checks that the Bash and Zsh completion scripts list every subcommand, flag and fixed value in the CLI (read from the dispatcher and the argparse code). When it fails after you add or rename a flag, update `completions/towit.bash` and `completions/_towit`
- `tests/helpers/docs_consistency_test.py` — Checks that README, AGENTS.md, SECURITY.md, the help text, and the config template agree with the code (subcommands, flags, config keys, hook events, tables, env vars, the subprocess allowlist). When it fails after you add a flag, config key, table, or env var, update the docs it names. Run with `TOWIT_RELEASE_CHECK=1` to also require `CHANGELOG.md` `[Unreleased]` content (a release gate)

## Security Constraints

- DB directory created with `0700`, file with `0600` permissions
- Path validation on all transcript paths and session IDs
- SQL uses parameterized queries only (no string interpolation in WHERE clauses); FTS5 queries are built from quoted phrases (`build_match_expression`) bound as a parameter
- Subprocess environments (the `claude` calls and the `git rev-parse` in `resolve_repo_key`) are scoped to an allowlist of env var prefixes via `safe_subprocess_env()`; subprocesses use list form, never `shell=True`
- `towit_skill.py` (`claude plugin ...`, user scope, from `setup --skill`, `doctor` and `implode`, never from a hook) uses the same scoped environment plus exactly the names in `GIT_NETWORK_ENV` (`SSH_AUTH_SOCK`, `HTTP(S)_PROXY`, `ALL_PROXY`, `NO_PROXY` in both cases, `SSL_CERT_FILE`, `SSL_CERT_DIR`), matched by exact name, because the marketplace is a `git clone` that may need them to reach GitHub. Nothing else, such as tokens or keys, is passed
- Secrets are redacted (`towit_redact`) before text is stored and before the indexing transcript is sent to `claude -p`; redaction is best effort; stored rows are redacted at ingest and never rewritten, export prompts are redacted at send time. `towit export --summarize` (single and `--topic`) also redacts the prompt at send time when `ingest.redact` is on, so transcripts and stored summaries (including rows indexed by 0.8.2 or earlier) are covered
- `towit forget` tombstones ids in `forgotten`, and physically removes data (`secure_delete`, FTS `optimize`, `VACUUM`, WAL truncate)
- Symlinked JSONL files excluded from backfill, the catch-up scan, and ingest

## Release Process

Use the **`release-towit` skill** (`.claude/skills/release-towit/SKILL.md`, loaded automatically in Claude Code) for all releases: when the user asks to cut a release, bump a version, tag a release, or publish a new version. It is a thin overlay (the release parameters: gates, version file, audits, tag style, tap bump) on the shared `chrisbloom7-development:release` skill from the `ai-tools` plugin marketplace, which holds the generic steps: version choice, CHANGELOG, release PR, tagging, and pushing. Install it first (`/plugin marketplace add chrisbloom7/ai-tools`).

Never bypass the skill — it catches README drift and other issues that ad-hoc releases miss.

## Directives

Agents without the Claude skills must still follow these two. Claude Code agents: the `feature-dev-towit` skill has the detailed workflow.

- **Plan first:** Before implementing any non-trivial change, write out your plan and pause for acceptance before touching code.
- **Test-driven development:** Write failing tests before implementation code, confirm they fail, implement, then confirm they pass. No need to ask permission to move on.

## Claude tooling

- `.claude/hooks/docs-drift.sh` (a `Stop` hook in `.claude/settings.json`) runs `tests/helpers/docs_consistency_test.py` when code or docs changed in the working tree.
- `.claude/agents/security-reviewer.md` is a read-only reviewer; use it after touching db, ingest, index, forget, redact, config or subprocess code.
- `feature-dev-towit` (`.claude/skills/`) is the skill for any code change; `release-towit` is the release overlay described above.
- `.claude/settings.json` allows only `./run-tests` (with or without arguments) and `bin/towit help` without a prompt.
- **Reviewing outside PRs:** changes to `.claude/`, `CLAUDE.md` and `AGENTS.md` run or steer Claude Code on a reviewer's machine, so `.github/CODEOWNERS` routes them to the maintainer. Read the diff first (`gh pr diff <number> -- .claude CLAUDE.md AGENTS.md`) before checking an outside PR out and starting Claude Code there.
