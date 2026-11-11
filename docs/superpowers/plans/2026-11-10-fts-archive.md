# Full-Text Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store conversation message text in SQLite FTS5 so `towit search` finds what was said, keep the archive after Claude Code purges transcripts, and make LLM metadata optional.

**Architecture:** A new deterministic ingest path (`towit_ingest.py`) parses transcripts into redacted message rows (text plus tool-call stubs) and appends them by `seq` inside one write transaction. `towit_db.py` owns all SQL, including the FTS5 index kept in sync by triggers. Search, `show`, `forget`, `prune`, `stats`, and `doctor` are extended on top. The existing LLM indexer keeps running, gated by a new `[indexing] enabled` setting.

**Tech Stack:** Python 3.11+ stdlib only (`sqlite3` with FTS5, `hashlib`, `dataclasses`, `fnmatch`, `subprocess`, `argparse`, `tomllib`); `unittest` for unit tests; BATS for CLI tests. Run with `./run-tests`.

**Spec:** `docs/superpowers/specs/2026-11-10-fts-archive-design.md`

**Workflow:** Do the work in a worktree branch created with `wt switch --create feat/fts-archive --yes` (never raw `git worktree add`). Merge into `main` only through a PR from the remote branch (never `wt merge`). Tasks 0–16 happen on the branch and ship in one PR (Task 17's skill edits in their own PR); Task 18 (release) happens on `main` after those PRs are merged.

## Deviations From the Spec (confirm before executing)

Reading the code showed these spec statements need adjusting. The plan implements the right-hand column.

| Spec says | Plan does | Why |
|---|---|---|
| Reuse `conversations.message_count` | New column `archived_message_count` | `message_count` is the text-only count that drives `reindex_delta`. Archive counts include stubs and differ, so sharing the column would corrupt LLM re-index timing. |
| Search ranked together with metadata weighting | Tiered: conversations with a metadata match first, then by best `bm25` | `bm25` scores and `LIKE` matches are not comparable. Revisit after the live trial. |
| (silent) | Per-message cap of 50,000 chars | A pasted log must not bloat the archive. |
| JSON output includes `conversation_id` | JSON keeps the existing `id` key and adds `seq`, `snippet`, `score` | Avoids breaking existing consumers. |
| (silent) | `Database.is_indexed` now means "has a non-null title" | Ingest creates rows with no title; backfill's dry run must not call them indexed. |

## Project-Skill Compliance (`feature-dev-towit`)

The project skill requires these in any plan; they are collected here so a reviewer can check them in one place.

- **Help text delta:** `bin/towit` usage gains `show <session-id> [--around <seq>] [--context <n>] [--format json]`, `forget <session-id> | --repo <path|name> | --folder <path> [--yes]`, `search ... [--only text|metadata] [--repo <path|name>]`, `prune [--archive] [--yes] [--dry-run]`; descriptions of `search` and `backfill` change (Tasks 9–13, finalized in Task 16 Slice A)
- **README delta, CHANGELOG draft:** Task 16 Slice A Step 3 and Slice D Step 3
- **ZOMBIES mapping:** Z: empty transcript, no messages, empty `terms`, empty DB. O: one message, one conversation. M: many sessions, appended batches. B: 50,000-char cap, 200/300-char stub caps, exactly-2-user-message threshold. I: every new flag and `--format json`. E: partial JSONL line, missing git, invalid extra regex, unknown id, FTS operator characters. S: the Task 14 end-to-end BATS flow
- **Optimization notes:** the hook stays non-blocking (ingest runs in the detached process); LLM spend per call is unchanged and drops to zero with `[indexing] enabled = false`; re-parsing the whole transcript on each stop is measured at under a second per 30 sessions, so incremental file offsets are deliberately not added (YAGNI); stdlib only
- **Commit size:** the skill caps commits at ~300 changed lines and requires asking before exceeding it. Tasks 6, 7, and 10 may exceed that; split at the test/implementation boundary (e.g. 10a database layer, 10b CLI) or ask for permission before committing a larger slice

## Global Constraints

- Python 3.11+, stdlib only; no new dependencies
- FTS5 tokenizer is exactly `unicode61 tokenchars '_-.'`
- Stub value cap 200 chars; failed-result cap 300 chars (`[error] ` prefix); stub format `[<ToolName>] <value>`
- Stub value is the first non-empty string among keys `description`, `command`, `file_path`, `pattern`, `query`, `url`, `skill`, `path`
- Redaction replaces matches with `[REDACTED:<kind>]`
- `include_subagents` defaults to `false`; `redact` defaults to `true`; `[indexing] enabled` defaults to `true`; `folders` defaults to `[]` (all)
- All SQL parameterized; user text never concatenated into SQL (see the `assert` pattern in `Database.search`)
- DB file `0600`, directory `0700` (already enforced; do not regress)
- Hooks (`Stop`, `SessionEnd`, `SessionStart` matcher `startup`) always exit 0, never block (work runs in a detached process), validate `transcript_path`, and keep the `TOWIT_INDEXING` recursion guard; the `SessionStart` catch-up is ingest-only and never calls the LLM
- Subprocess environments are built only by `towit_config.safe_subprocess_env()` (Task 5), never inline
- Documentation (`README.md`, `SECURITY.md`, `AGENTS.md`, `CHANGELOG.md`, `bin/towit` help text) must match the source; `tests/helpers/docs_consistency_test.py` (Task 16) enforces the mechanical parts and Task 16 Slice E audits the rest
- Version tag is `vMAJOR.MINOR.PATCH` (SemVer 2.0.0, no pre-release or build metadata), created only through the `release-towit` skill
- Tests use synthetic fixtures only. Fake secrets in tests are assembled from string pieces so scanners don't flag the test source. Never commit real transcripts
- TDD per AGENTS.md: failing test, confirm failure, implement, confirm pass, commit

## Review Focus

Inputs the spec implies but the task tests wouldn't otherwise exercise, most likely first. Each has a test in the owning task.

1. **FTS5 operator characters in user queries** (`"`, `*`, `NEAR`, `AND`, unbalanced quotes, punctuation-only): must return results or none, never raise (Task 10)
2. **Transcript mid-write**: hook fires while the last JSONL line is partial; parse must skip it and a later run must pick it up (Task 4)
3. **Compaction/rewrite**: stored tail no longer matches; clean re-ingest, no duplicated or orphaned rows (Task 6)
4. **Oversized single message**: stored truncated with a marker, never fails the ingest (Task 4)
5. **Concurrent ingest of one session** (rapid stop-hook firings): no duplicate `seq`, no crash (Task 7)

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `libexec/towit/towit_db.py` | Schema, migrations, archive/search/show/forget SQL |
| Modify | `libexec/towit/towit_config.py` | New `[ingest]` and `[indexing] enabled` settings |
| Create | `libexec/towit/towit_redact.py` | `redact()` |
| Create | `libexec/towit/towit_ingest.py` | Transcript parsing, repo key, `ingest_transcript`, background entry point |
| Modify | `libexec/towit/towit_index.py` | Redact before LLM; forgotten guard |
| Modify | `libexec/towit/towit_hook.py`, `towit_install_hook.py`, `towit_uninstall_hook.py`, `towit_backfill.py` | Wire ingest in; three hook events; catch-up scan |
| Modify | `libexec/towit/towit_search.py` | New scope, snippets, `--only`, `--repo` |
| Create | `libexec/towit/towit_show.py`, `towit_forget.py` | New subcommands |
| Modify | `libexec/towit/towit_prune.py`, `towit_stats.py`, `towit_doctor.py`, `towit_setup.py` | Archive-aware behavior and config template |
| Modify | `bin/towit` | Dispatcher cases, usage text |
| Modify | `README.md`, `SECURITY.md`, `AGENTS.md`, `CHANGELOG.md`, `docs/superpowers/specs/2026-11-10-fts-archive-design.md` | Documentation updated to match the source |
| Create | `tests/helpers/docs_consistency_test.py` | Mechanical docs-vs-source checks |
| Create/Modify | `tests/helpers/towit_{redact,ingest,show,forget}_test.py`, existing `*_test.py`, `tests/bin/towit.bats`, `tests/test_helper.bash` | Tests |

---

### Task 0: Fix `towit setup --full` not generating the config (independent bug fix)

Reported from real use: `towit setup --full` initializes the DB, installs the hook, and backfills, but leaves no `~/.towit/config.toml`, although the help text, README, and CHANGELOG say `--full` generates one first (`towit doctor` then warns "Config file not found"). Root cause: `bin/towit` consumes `--full` and `--hook` in its own argument loop and forwards only the remaining arguments to `towit_setup.py`, so that script's `args.full` is always false and `generate_config()` never runs for `--full`. Separately, `towit_setup.py`'s own `--full`/`--hook` branches call `install_hook()` and `backfill()`, whose `argparse` re-parse `sys.argv` and reject the leftover flag; they are unreachable through the CLI, which is why this went unnoticed.

Ship as its own commit (`fix:`), first on the branch, so it can be cherry-picked or released alone.

**Files:**
- Modify: `bin/towit` (the `setup)` case)
- Test: `tests/bin/towit.bats`

**Interfaces:**
- Produces: `towit setup --full` forwards `--config` to `towit_setup.py`. `setup --hook` and plain `setup` still generate no config

- [ ] **Step 1: Write failing BATS tests.** Run each with `HOME="${TEST_TMPDIR}/home"` (containing an empty `.claude/projects`), `TOWIT_SETTINGS_PATH` inside `TEST_TMPDIR`, and `TOWIT_CONFIG_PATH` pointing at a file that does **not** exist yet (the shared helper pre-creates one, so override it; the DB then lands under the temp `HOME`):
  - `towit: setup --full generates the config file`: exit 0; the config file now exists with mode `600`; output contains `Config file created at`; output also contains `Database initialized`, `stop hook installed`, and `Backfill`/`No JSONL files found` (all four steps ran)
  - `towit: setup --full leaves an existing config untouched`: pre-write a config with a sentinel line; after the run it is byte-identical and output contains `Config file already exists`
  - `towit: setup --hook does not generate a config file`: the config path still does not exist afterward
  - `towit: setup with no flags does not generate a config file`
- [ ] **Step 2: Run** `./run-tests tests/bin/towit.bats --filter "setup --full"`. Expected: the first test FAILS (config missing); the other three pass today and pin existing behavior
- [ ] **Step 3: Implement** in the `setup)` case of `bin/towit`: when `--full` is seen, also `_setup_args+=(--config)`. Do not change the `--hook` handling. Leave `towit_setup.py`'s unreachable `--full`/`--hook` install and backfill branches alone in this task (removing dead code is a separate cleanup); add a one-line comment in `bin/towit` explaining why `--config` is forwarded
- [ ] **Step 4: Run** `./run-tests tests/bin/towit.bats --filter setup`. Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "fix: setup --full now generates the config file"`

---

### Task 1: Archive schema and migration

**Files:**
- Modify: `libexec/towit/towit_db.py` (`SCHEMA`, `run_migrations`)
- Test: `tests/helpers/towit_db_test.py`

**Interfaces:**
- Produces: tables `messages(id, conversation_id, seq, role, ts, text, UNIQUE(conversation_id, seq))`, FTS5 table `messages_fts`, tables `forgotten(id, forgotten_at)` and `meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)`; columns on `conversations`: `tail_hash TEXT`, `source_path TEXT`, `archived INTEGER NOT NULL DEFAULT 0`, `archived_message_count INTEGER NOT NULL DEFAULT 0`, `repo_key TEXT` (indexed); `messages.role` CHECK in (`user`,`assistant`)

- [ ] **Step 1: Write failing tests** in a new `TestArchiveSchema` class (use a fresh temp DB via `Database(path).create_schema()`):
  - `test_create_schema_adds_archive_objects`: `messages`, `messages_fts`, `forgotten`, `meta` in `sqlite_master`; the five new columns in `PRAGMA table_info(conversations)`
  - `test_migration_from_legacy_db_is_idempotent`: build a DB with only the v0.8.2 tables via raw `executescript`, call `run_migrations()` twice, assert no exception and new objects exist
  - `test_fts_triggers_track_insert_update_delete`: insert a conversation and a message `"the TOWIT_INDEXING guard"`; `SELECT rowid FROM messages_fts WHERE messages_fts MATCH '"TOWIT_INDEXING"'` returns that id; after `UPDATE messages SET text='changed'` the match returns none and `'"changed"'` matches; after `DELETE` it returns none
  - `test_deleting_conversation_cascades_into_fts`: delete the conversation; MATCH returns none and `INSERT INTO messages_fts(messages_fts) VALUES('integrity-check')` does not raise
  - `test_unique_conversation_seq`: inserting the same `(conversation_id, seq)` twice raises `sqlite3.IntegrityError`
  - `test_identifier_tokenizes_whole`: `"reindex_delta"` and `"TOWIT_INDEXING"` each match as a single token
- [ ] **Step 2: Run** `./run-tests tests/helpers/towit_db_test.py --filter ArchiveSchema`. Expected: FAIL (no such table)
- [ ] **Step 3: Implement** the DDL in `SCHEMA` for fresh DBs and the same objects in `run_migrations` (guard each `ALTER TABLE ADD COLUMN` with the existing `try/except sqlite3.OperationalError` pattern; use `IF NOT EXISTS` for tables, indexes, triggers). External-content FTS5 with the three standard sync triggers (`AFTER INSERT`, `AFTER DELETE`, `AFTER UPDATE`, using the `'delete'` command form)
- [ ] **Step 4: Run** the same command. Expected: PASS; then `./run-tests tests/helpers/towit_db_test.py` all pass
- [ ] **Step 5: Commit** `git commit -m "feat: add archive schema with FTS5 index"`

---

### Task 2: Config settings

**Files:**
- Modify: `libexec/towit/towit_config.py`, `libexec/towit/towit_setup.py` (`_CONFIG_TEMPLATE`)
- Test: `tests/helpers/towit_config_test.py`, `tests/helpers/towit_setup_test.py`

**Interfaces:**
- Produces on `Config`: `ingest_redact -> bool` (True), `ingest_extra_patterns -> list[str]` ([]), `ingest_include_subagents -> bool` (False), `ingest_folders -> list[str]` ([]), `indexing_enabled -> bool` (True)

- [ ] **Step 1: Write failing tests:** defaults for all five; values read from a temp TOML file; `ingest_redact = "yes"` warns and returns default; `[ingest] bogus = 1` warns about an unknown key; `ingest_folders = "x"` (not a list) warns and returns `[]`; `towit setup --config` output contains `[ingest]`, `include_subagents`, and `enabled`
- [ ] **Step 2: Run** `./run-tests tests/helpers/towit_config_test.py`. Expected: FAIL
- [ ] **Step 3: Implement** the properties and extend `_KNOWN_KEYS` with `'ingest': {'redact','extra_patterns','include_subagents','folders'}` and `'enabled'` under `'indexing'`. **Note:** `Config._get` currently rejects `bool` for every expected type (`isinstance(value, bool)` guard); change it so a `bool` is accepted when `expected_type is bool`, and add a `list` getter that checks every element is `str`. Add commented entries to `_CONFIG_TEMPLATE`. Check whether `towit_doctor.check_config_unknown_keys` reads `_KNOWN_KEYS` or keeps its own list; update whichever it uses
- [ ] **Step 4: Run** config, setup, and doctor tests. Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: add [ingest] and [indexing] enabled config settings"`

---

### Task 3: Redaction

**Files:**
- Create: `libexec/towit/towit_redact.py`
- Test: `tests/helpers/towit_redact_test.py`

**Interfaces:**
- Produces: `REDACTION_PATTERNS: dict[str, str]` (kind → regex); `redact(text: str, extra_patterns: Sequence[str] = ()) -> str`
- Kinds: `aws_key_id`, `github_token`, `anthropic_key`, `openai_key`, `stripe_key`, `slack_token`, `jwt`, `private_key`, `bearer_token`, `url_credentials`, `secret_assignment`; extra patterns use kind `custom`

- [ ] **Step 1: Write failing tests:**
  - one test per kind using a fake secret built as `"AKIA" + "A" * 16` etc.: output contains `[REDACTED:<kind>]` and not the secret
  - `test_url_credentials_keep_scheme_and_host`: `"postgresql://user:pw123456@db.internal:5432/x"` → `"postgresql://[REDACTED:url_credentials]@db.internal:5432/x"`
  - `test_secret_assignment`: `"STRIPE_WEBHOOK_SECRET=" + "a1b2c3d4" * 3` redacts the value and keeps the key name
  - `test_benign_text_unchanged`: ordinary prose, a file path, a git SHA, and `reindex_delta = 2` come back identical
  - `test_idempotent`: `redact(redact(x)) == redact(x)`
  - `test_extra_pattern`: `redact("order 99-ABC", [r"\d{2}-[A-Z]{3}"])` → `"order [REDACTED:custom]"`
  - `test_invalid_extra_pattern_is_ignored_with_warning`: `"("` neither raises nor changes text; stderr has a warning
- [ ] **Step 2: Run** `./run-tests tests/helpers/towit_redact_test.py`. Expected: FAIL (module missing)
- [ ] **Step 3: Implement** with precompiled regexes; seed patterns from the prototype set in the spec's Redaction section
- [ ] **Step 4: Run.** Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: add secret redaction"`

---

### Task 4: Transcript parsing with stubs

**Files:**
- Create: `libexec/towit/towit_ingest.py` (parsing portion)
- Test: `tests/helpers/towit_ingest_test.py` (new; add a `_write_jsonl(path, entries)` helper)

**Interfaces:**
- Produces: `MAX_MESSAGE_CHARS = 50_000`; `@dataclass ArchiveMessage(role: str, ts: str | None, text: str)`; `@dataclass ParsedTranscript(session_id: str, cwd: str, started_at: str | None, last_active: str | None, messages: list[ArchiveMessage])`; `parse_transcript(path: str) -> ParsedTranscript`
- `parse_jsonl` in `towit_index.py` is left unchanged

- [ ] **Step 1: Write failing tests** (`class TestParseTranscript`):
  - `test_text_and_tool_stub_in_order`: assistant entry with a text item `"Running tests"` and a `Bash` tool_use `{description: "Run tests", command: "pytest"}` → one message, text `"Running tests\n[Bash] Run tests"`
  - `test_bash_falls_back_to_command`: no description → `"[Bash] pytest -x"`
  - `test_stub_value_capped_at_200`: `Edit` with a 500-char `file_path` → text length `len("[Edit] ") + 200`
  - `test_error_result_truncated_to_300`: user entry with `tool_result`, `is_error: True`, 500-char content → text is `"[error] " + "x" * 300`
  - `test_non_error_results_and_thinking_ignored`: entry containing only those yields no message
  - `test_partial_last_line_is_ignored`: file ending in `{"type": "assi` parses without raising and returns the earlier messages (Review Focus 2)
  - `test_oversized_message_truncated_with_marker`: 120,000-char text → stored text length ≤ `MAX_MESSAGE_CHARS + 60`, ends with `chars truncated ...]` (Review Focus 4)
  - `test_metadata_fields`: `session_id` from file name, `cwd` from first entry, `started_at`/`last_active` from first/last timestamps
- [ ] **Step 2: Run** `./run-tests tests/helpers/towit_ingest_test.py`. Expected: FAIL
- [ ] **Step 3: Implement** `parse_transcript`: one `ArchiveMessage` per `user`/`assistant` entry whose joined parts are non-empty; skip entries whose JSON does not parse; join text and stub parts with `\n`
- [ ] **Step 4: Run.** Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: parse transcripts into archive messages with tool stubs"`

---

### Task 5: Repo key resolution

**Files:**
- Modify: `libexec/towit/towit_ingest.py`
- Test: `tests/helpers/towit_ingest_test.py`

**Interfaces:**
- Produces: `towit_config.safe_subprocess_env(extra: dict | None = None) -> dict` (the `_PASS_THROUGH_PREFIXES` filter currently inline at `towit_index.py:204-212`, with `extra` merged in; `towit_index.py` is changed to call it, so there is one allowlist); `resolve_repo_key(cwd: str) -> str`: the repo root containing the git common dir, else `cwd` unchanged

- [ ] **Step 1: Write failing tests:** (a) real `git init` in a temp dir → key equals `os.path.realpath(dir)`; (b) subprocess mocked to return `"/repo/.git\n"` for a cwd that exists (simulating a linked worktree) → `"/repo"`; (c) non-git temp dir → the dir itself; (d) nonexistent path → the path itself; (e) `subprocess.run` raising `FileNotFoundError` (git missing) → `cwd`; (f) empty `cwd` → `""`; `safe_subprocess_env()` drops `AWS_SECRET_ACCESS_KEY` and keeps `PATH`, `CLAUDE_X`, and `LC_ALL`, and `towit_index` still passes `TOWIT_INDEXING=1` through `extra`. Do not create worktrees with `git worktree add` in fixtures
- [ ] **Step 2: Run.** Expected: FAIL
- [ ] **Step 3: Implement** with `git -C <cwd> rev-parse --git-common-dir`, 5-second timeout, `env=safe_subprocess_env()`; move the allowlist out of `towit_index.py` into `towit_config.py` and call it from both; resolve a relative result against `cwd`; strip a trailing `/.git`; never raise
- [ ] **Step 4: Run.** Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: resolve repo key for worktree grouping"`

---

### Task 6: Atomic archive write

**Files:**
- Modify: `libexec/towit/towit_db.py`
- Test: `tests/helpers/towit_db_test.py`

**Interfaces:**
- Produces: `message_hash(role: str, text: str) -> str` (sha256 hex of `role + "\0" + text`); `Database.archive_session(conv: dict, messages: list[dict]) -> str`; `Database.is_forgotten(conv_id: str) -> bool`
- `conv` keys: `id, folder, cwd, started_at, last_active, repo_key, source_path`. Each message dict: `role, ts, text`
- Returns one of `'ingested'`, `'appended'`, `'rewritten'`, `'unchanged'`

- [ ] **Step 1: Write failing tests** (`class TestArchiveSession`):
  - first call stores rows with `seq` 0..n-1, sets `archived=1`, `archived_message_count=n`, `tail_hash == message_hash(last)`, leaves `title` and `summary` NULL, returns `'ingested'`
  - same messages again → `'unchanged'`, row count unchanged
  - messages plus two more → `'appended'`, total n+2, `seq` contiguous
  - same count but different last message → `'rewritten'`, rows equal the new list (Review Focus 3)
  - fewer messages than stored → `'rewritten'`
  - existing LLM metadata (title, summary, keywords, topics) survives all four outcomes
  - `is_forgotten` False, then True after inserting into `forgotten`
- [ ] **Step 2: Run.** Expected: FAIL
- [ ] **Step 3: Implement** `archive_session` inside one `BEGIN IMMEDIATE` transaction that reads state, decides, writes, and updates the conversation row (insert if absent; update only `last_active`, `cwd`, `repo_key`, `source_path`, and archive columns, never `title`/`summary`). Append decision: stored tail hash equals hash of `messages[count-1]`
- [ ] **Step 4: Run.** Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: atomic append-only archive writes"`

---

### Task 7: Ingest a transcript

**Files:**
- Modify: `libexec/towit/towit_ingest.py`
- Test: `tests/helpers/towit_ingest_test.py`

**Interfaces:**
- Consumes: `parse_transcript`, `resolve_repo_key`, `redact`, `Database.archive_session`, `Database.is_forgotten`, config properties from Task 2
- Produces: `ingest_transcript(jsonl_path: str, db: Database | None = None) -> str` returning `'ingested' | 'appended' | 'rewritten' | 'unchanged' | 'skipped' | 'forgotten'`

- [ ] **Step 1: Write failing tests** (`class TestIngestTranscript`, patch config properties with `unittest.mock.patch.object`):
  - fresh transcript → `'ingested'`, messages stored with `repo_key` set and `folder` equal to the transcript's directory
  - second call → `'unchanged'`; grown file → `'appended'`
  - fewer than 2 user messages → `'skipped'`, no rows
  - path containing `/subagents/` → `'skipped'`; with `ingest_include_subagents` True → stored
  - symlinked transcript → `'skipped'`
  - id in `forgotten` → `'forgotten'`, no rows
  - `ingest_folders = ["*Robinina*"]` and a non-matching folder → `'skipped'`; matching → stored (`fnmatch` against the transcript's directory)
  - fake secret in a message is stored as `[REDACTED:...]`; with `ingest_redact` False it is stored raw
  - two threads ingesting the same file: results sorted equal `['ingested', 'unchanged']` and row count equals parsed count (Review Focus 5)
- [ ] **Step 2: Run.** Expected: FAIL
- [ ] **Step 3: Implement** skip rules, then `parse_transcript`, redact each message's `text` (and the stored `cwd` untouched), then `archive_session`
- [ ] **Step 4: Run.** Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: ingest transcripts into the archive"`

---

### Task 8: LLM path changes

**Files:**
- Modify: `libexec/towit/towit_index.py` (`index_conversation`), `libexec/towit/towit_db.py` (`is_indexed`)
- Test: `tests/helpers/towit_index_test.py`, `tests/helpers/towit_db_test.py`

**Interfaces:**
- Consumes: `redact`, `Database.is_forgotten`, `config.ingest_redact`, `config.ingest_extra_patterns`
- Produces: `index_conversation` returns `'skipped'` for forgotten ids; the transcript passed to `analyze_with_claude` is redacted; `Database.is_indexed` is True only when `title IS NOT NULL`

- [ ] **Step 1: Write failing tests:** with `analyze_with_claude` mocked, a transcript containing a fake secret reaches the mock redacted; a forgotten id returns `'skipped'` and the mock is not called; an archive-only row (`title` NULL) is not `is_indexed`, a titled row is; an archive-only row **is** analyzed by `index_conversation` (stored `message_count` is NULL, so it falls through to analysis, as for pre-migration rows)
- [ ] **Step 2: Run** index and db tests. Expected: FAIL
- [ ] **Step 3: Implement** the three changes with minimal edits
- [ ] **Step 4: Run** index, db, backfill tests. Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: redact transcripts sent to Claude and respect forget"`

---

### Task 9: Hook and backfill integration

**Files:**
- Modify: `libexec/towit/towit_ingest.py` (add `main()`), `libexec/towit/towit_hook.py`, `libexec/towit/towit_backfill.py`
- Modify: `tests/test_helper.bash` (add `write_fixture_session <dir> <session-id>`)
- Test: `tests/helpers/towit_ingest_test.py`, `tests/helpers/towit_backfill_test.py`, `tests/bin/towit.bats`

**Interfaces:**
- Consumes: `ingest_transcript`, `index_conversation`, `config.indexing_enabled`
- Produces: `python3 towit_ingest.py <jsonl_path>` runs `ingest_transcript`, then `index_conversation` unless the result is `'forgotten'`/`'skipped'` or `indexing_enabled` is False; the hook spawns this instead of `towit_index.py`

- [ ] **Step 1: Write failing tests:** `main()` with `indexing_enabled` False never calls `index_conversation`; with True it calls it after ingest; `'forgotten'` result never calls it; the hook (existing test style) spawns `towit_ingest.py` with the validated path and still exits 0 when ingest raises; backfill ingests each non-subagent, non-symlink file then indexes unless `indexing_enabled` is False; BATS: with `[indexing] enabled = false` in the temp config, `towit backfill` over two fixture sessions reports ingestion and `towit stats` shows 2 conversations
- [ ] **Step 2: Run** `./run-tests --filter ingest` and `./run-tests tests/bin/towit.bats --filter backfill`. Expected: FAIL
- [ ] **Step 3: Implement.** Hook change is the single `Popen` target. Backfill prints the ingest status in its per-file line and counts it in the summary
- [ ] **Step 4: Run** the full suite. Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: ingest from the stop hook and backfill"`

---

### Task 9b: Register `SessionEnd` and `SessionStart` hooks; catch-up scan

**Files:**
- Modify: `libexec/towit/towit_hook.py`, `libexec/towit/towit_ingest.py`, `libexec/towit/towit_install_hook.py`, `libexec/towit/towit_uninstall_hook.py`, `libexec/towit/towit_db.py`
- Test: hook tests (create `tests/helpers/towit_hook_test.py` if absent, else extend), `towit_install_hook_test.py`, `towit_uninstall_hook_test.py`, `towit_ingest_test.py`, `towit_db_test.py`

**Interfaces:**
- Consumes: `ingest_transcript`, `index_conversation`, `config.indexing_enabled`
- Produces: `towit_install_hook.HOOK_EVENTS: dict[str, str]` (event → matcher: `{'Stop': '', 'SessionEnd': '', 'SessionStart': 'startup'}`); `Database.get_meta(key: str) -> str | None`; `Database.set_meta(key: str, value: str) -> None`; `towit_ingest.catch_up(root: str | None = None, db: Database | None = None) -> dict[str, int]` (counts keyed by `ingest_transcript` status; scans `root`, default `~/.claude/projects`, for `*.jsonl` modified after the `last_catch_up` meta stamp minus 60 s, or all when unset; skips symlinks and `/subagents/`; stores the scan start time as an ISO-8601 UTC stamp when done; never calls the LLM); `python3 towit_ingest.py --catch-up` runs it
- Hook dispatch on the payload's `hook_event_name`: `Stop` and `SessionEnd` validate `transcript_path` and spawn `towit_ingest.py <path>` detached; `SessionStart` spawns `towit_ingest.py --catch-up` detached (no `transcript_path` needed); any other event exits 0 without spawning

- [ ] **Step 1: Write failing tests:**
  - meta: `get_meta('x')` is None; after `set_meta('x','1')` returns `'1'`; a second `set_meta` overwrites
  - install: installs one entry per event in `HOOK_EVENTS` (the `SessionStart` entry has matcher `startup`); running twice leaves exactly one towit entry per event; unrelated existing hooks are preserved; the write stays atomic (existing test pattern); uninstall removes all three towit entries and leaves unrelated hooks
  - hook (mock `subprocess.Popen`): `Stop` and `SessionEnd` payloads with a valid transcript path spawn `towit_ingest.py <path>` with `start_new_session=True`; `SessionStart` spawns with `--catch-up`; an unknown event spawns nothing and exits 0; an invalid or out-of-tree `transcript_path` for `Stop`/`SessionEnd` spawns nothing and exits 0; an exception inside the hook is logged to `errors.log` and the exit code is still 0
  - catch-up: with no stamp it ingests every fixture transcript and sets the stamp; an immediate second run reports zero `ingested`/`appended`; touching one file (newer mtime) re-processes only that file; subagent and symlinked files are skipped; `index_conversation` is patched and asserted not called
- [ ] **Step 2: Run** the new tests. Expected: FAIL
- [ ] **Step 3: Implement.** Reuse the existing settings merge and atomic `os.replace` write in `towit_install_hook.py`, extending its empty-matcher merge logic per event. The hook stays a thin dispatcher; all work happens in the detached process
- [ ] **Step 4: Run** hook, install, uninstall, ingest, and db tests. Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: capture on SessionEnd and catch up on SessionStart"`

---

### Task 10: Search

**Files:**
- Modify: `libexec/towit/towit_db.py`, `libexec/towit/towit_search.py`
- Test: `tests/helpers/towit_db_test.py`, `tests/helpers/towit_search_test.py`

**Interfaces:**
- Produces: `build_match_expression(terms: list[str], mode: str = 'and') -> str | None` (module-level; each term quoted as an FTS5 phrase with embedded `"` doubled; joined with `AND`/`OR`; `None` when nothing tokenizable remains); `Database.search_archive(terms: list[str], mode: str = 'and', folder: str | None = None, repo: str | None = None, scope: str = 'all', include_topics: bool = False, include_summary: bool = False, include_title: bool = False, limit: int = 50) -> list[dict]`
- Result dict: existing keys from `_row_to_dict` plus `seq: int | None`, `snippet: str`, `score: float | None`, with `title` falling back to the first user message (80 chars) when null
- CLI: new `--only text|metadata` and `--repo <path|name>`; `--repo` matches `repo_key` exactly or by final path component

- [ ] **Step 1: Write failing tests:**
  - `build_match_expression(['stop hook'])` is a single phrase; `(['a', 'b'], 'or')` joins with `OR`; `(['"'])`, `(['***'])`, `([])` return `None`
  - Review Focus 1: searching for each of `'"'`, `'*'`, `'NEAR('`, `'AND'`, `'a"b'`, `'"unbalanced'` returns a list and raises nothing
  - text hit in an assistant message is found with a snippet containing `[` `]` highlights and the right `seq`; `"stop hook"` as one argument is exact where `stop hook` as two arguments is AND
  - tiering: a conversation with a keyword match ranks above a text-only match; `scope='text'` ignores metadata; `scope='metadata'` reproduces the old results
  - `repo` filter by exact key and by basename; `folder` filter unchanged
  - null-title conversation shows first user message as title
  - CLI: table has `Turn` and `Snippet` columns; `--format json` entries include `id`, `seq`, `snippet`, `score`; `--only metadata` output matches the pre-change behavior for the existing search fixtures
- [ ] **Step 2: Run.** Expected: FAIL
- [ ] **Step 3: Implement** the text query as a join of `messages_fts`, `messages`, `conversations` using `snippet(messages_fts, 0, '[', ']', '…', 12)` and `bm25`; keep the best row per conversation; reuse the existing metadata `LIKE` logic and its parameterization assertion. Keep `Database.search` for the metadata path. Table output shows the text snippet, else the matched keyword (existing `_filter_keywords`)
- [ ] **Step 4: Run** all search and db tests. Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: full-text search over archived messages"`

---

### Task 11: `towit show`

**Files:**
- Create: `libexec/towit/towit_show.py`; Modify: `libexec/towit/towit_db.py`, `bin/towit`
- Test: `tests/helpers/towit_show_test.py`, `tests/bin/towit.bats`

**Interfaces:**
- Produces: `Database.get_messages(conv_id: str, around: int | None = None, context: int = 5) -> list[dict]` (keys `seq, role, ts, text`; all messages when `around` is None); CLI `towit show <session-id> [--around <seq>] [--context <n>] [--format json]`

- [ ] **Step 1: Write failing tests:** full conversation in `seq` order; `around=10, context=2` returns seq 8–12; `around` near the ends clamps; unknown id exits 1 with `not found`; known id with no archived messages exits 1 with a message pointing to `towit backfill`; `--format json` is a valid array; BATS: `towit show` works after the fixture transcript file is deleted
- [ ] **Step 2: Run.** Expected: FAIL
- [ ] **Step 3: Implement**; add the `show` case and a usage line to `bin/towit`
- [ ] **Step 4: Run.** Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: add towit show"`

---

### Task 12: `towit forget`

**Files:**
- Create: `libexec/towit/towit_forget.py`; Modify: `libexec/towit/towit_db.py`, `bin/towit`
- Test: `tests/helpers/towit_forget_test.py`, `tests/bin/towit.bats`

**Interfaces:**
- Produces: `Database.forget_conversation(conv_id: str) -> bool` (deletes the conversation, cascading to messages and FTS rows, and inserts into `forgotten`; False if the id was unknown); `Database.conversation_ids_for_scope(repo: str | None = None, folder: str | None = None) -> list[str]` (`repo` matches `repo_key` exactly or by final path component, as in search; `folder` matches `cwd` exactly, as in search and list); CLI `towit forget <session-id> | --repo <path|name> | --folder <path> [--yes]` (exactly one selector is required; every form prints how many conversations it will delete and prompts unless `--yes`)

- [ ] **Step 1: Write failing tests:** after forget, `search_archive` for a phrase from that conversation returns nothing and `messages` has no rows for it; `ingest_transcript` on the still-present transcript returns `'forgotten'`; unknown id exits 1; without `--yes` and with input `n` nothing is deleted; bulk forms: `--folder` deletes only conversations whose `cwd` equals the path and leaves others, `--repo` matches by basename, no selector or two selectors exits 2 with usage, a selector matching nothing exits 1 with `no conversations match`, the prompt shows the count and `n` deletes nothing; BATS: forget then `backfill` and the `SessionStart` catch-up do not restore it
- [ ] **Step 2: Run.** Expected: FAIL
- [ ] **Step 3: Implement**; add dispatcher case and usage line
- [ ] **Step 4: Run.** Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: add towit forget"`

---

### Task 13: prune, stats, doctor

**Files:**
- Modify: `libexec/towit/towit_prune.py`, `towit_stats.py`, `towit_doctor.py`, `towit_db.py` (`all_conversation_stubs` also returns `archived`)
- Test: `tests/helpers/towit_prune_test.py`, `towit_stats_test.py`, `towit_doctor_test.py`

**Interfaces:**
- Produces: `prune [--archive] [--yes] [--dry-run]`: default removes only `archived = 0` entries with missing transcripts and **reports** (never deletes) a section `Likely removed by claude purge: N archived conversations whose project folder no longer exists` (`conversations.folder` not a directory); `--archive` also removes archived entries with missing transcripts after a confirmation prompt that shows the count (`--yes` skips it). `Database.archive_stats() -> dict` (keys `archived`, `metadata_only`, `messages`, `db_bytes`; all stats SQL stays in `towit_db.py` per the skill's DB rule; `doctor` keeps its direct `sqlite3` diagnostics because it must work when the DB is broken). `stats` adds `Archived conversations`, `Metadata-only conversations`, `Archived messages`, `Database size`. `doctor` adds `check_fts5_available() -> CheckResult`, `check_archive_schema(db_path: str) -> CheckResult`, `check_hook_events(settings_path: str) -> CheckResult` (WARN naming each of `Stop`, `SessionEnd`, `SessionStart` that is not registered with the towit hook; PASS when all three are), and `check_hooks_not_disabled(settings_path: str) -> CheckResult` (WARN when `disableAllHooks` is true) (tables present and FTS `integrity-check` passes); `check_db_schema` warns when archive tables are missing

- [ ] **Step 1: Write failing tests:** archived row with missing transcript survives default prune and is listed (not removed) in `--dry-run`; an archived row whose `folder` directory is gone appears under `Likely removed by claude purge` with the right count in default and `--dry-run` output and is not deleted, while an archived row whose file is missing but whose folder exists is not listed there; `--archive` without `--yes` shows the count in its prompt; hook-event doctor checks: all three registered → PASS, only `Stop` registered → WARN naming `SessionEnd` and `SessionStart`, `disableAllHooks: true` → WARN; `--archive --yes` removes it; `--archive` without `--yes` and input `n` removes nothing; metadata-only row with missing transcript is still pruned by default; stats output contains the four new labels with correct counts; doctor: FTS5 check PASS on this machine and FAIL when `sqlite3.connect` is patched to raise `OperationalError("no such module: fts5")`; archive schema WARN on a legacy DB, PASS after migration
- [ ] **Step 2: Run.** Expected: FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** the full suite. Expected: PASS
- [ ] **Step 5: Commit** `git commit -m "feat: archive-aware prune, stats, and doctor"`

---

### Task 14: End-to-end coverage

**Files:**
- Test: `tests/bin/towit.bats`

- [ ] **Step 1: Write the end-to-end BATS tests** (config sets `[indexing] enabled = false`; the fixture session contains a planted fake secret and the unique phrase `zephyr marker`): `backfill` → `search "zephyr marker"` finds it with a snippet → `show` prints it → stored text contains `[REDACTED:` and not the fake secret → `forget --yes` → `search` finds nothing → `backfill` again does not restore it. Migration BATS: start from a DB created with the v0.8.2 schema, run `towit setup`, and confirm existing rows remain searchable by metadata and `towit stats` runs
- [ ] **Step 2: Run** `./run-tests tests/bin/towit.bats`. Expected: PASS, since these exercise behavior built in Tasks 1–13. A failure here is an integration bug to fix in the owning task's code, not a reason to weaken the test
- [ ] **Step 3: Commit** `git commit -m "test: end-to-end coverage for the archive"`

---

### Task 15: Live trial (Robinina-LLC)

No code. Follow the spec's "Live Trial" section.

- [ ] **Step 1:** Create a trial config with its own `[database] path` and `[ingest] folders = ["*Robinina-LLC*"]`; export `TOWIT_CONFIG_PATH` for the trial shell only
- [ ] **Step 2:** `towit setup`, then `towit backfill` with `include_subagents = false`; record DB size, wall time, conversation and message counts via `towit stats`
- [ ] **Step 3:** Repeat in a second DB with `include_subagents = true`; compare
- [ ] **Step 4:** User supplies ~10 known-answer queries; record the rank of the intended session for each. Acceptance: top 3 for at least 8 of 10
- [ ] **Step 5:** Run the secret-shaped-string scan from the prototype over the trial DB's `messages.text`; expect zero hits (print counts only)
- [ ] **Step 6:** Check `repo_key` groups worktree sessions as expected (`SELECT repo_key, COUNT(*) FROM conversations GROUP BY 1`)
- [ ] **Step 7:** Record the results and the final decisions (the `include_subagents` default, ranking tiers) in the spec under a "Live Trial Results" heading. If a decision changes behavior, fix the code and its tests first

---

### Task 16: Update documentation and validate it against the source

**Files:**
- Create: `tests/helpers/docs_consistency_test.py`
- Modify: `README.md`, `SECURITY.md`, `AGENTS.md`, `CHANGELOG.md`, `bin/towit` (usage comment), `libexec/towit/towit_setup.py` (`_CONFIG_TEMPLATE`), `docs/superpowers/specs/2026-11-10-fts-archive-design.md`

Edit each document to describe the code as it is after Task 15, validated mechanically by a test written first for each slice. **Never commit a failing test** (project skill): each slice below adds its tests, sees them fail, updates its document, sees them pass, and is committed as one slice. The first slice creates the test module.

**Interfaces (test helpers, in `docs_consistency_test.py`):** `_read(rel_path: str) -> str`; `_help_output() -> str` (runs `bin/towit help`); `_dispatcher_subcommands() -> set[str]` (labels in the `case "${subcommand}"` block of `bin/towit`, excluding the deprecated `open` alias, `help`, and the empty/default cases)

**Slice A: README and help text**
- [ ] **Step 1: Write tests** `test_every_subcommand_in_help_and_readme` (each dispatcher subcommand appears in `_help_output()` and in the README Usage block); `test_help_flags_match_readme_usage` (set of `--flag` tokens equal in both); `test_every_config_key_documented` (every key in `towit_config._KNOWN_KEYS` appears in `README.md` and in `towit_setup._CONFIG_TEMPLATE`); `test_every_hook_event_documented` (every key of `towit_install_hook.HOOK_EVENTS` appears in `README.md` and `AGENTS.md`)
- [ ] **Step 2: Run** `./run-tests tests/helpers/docs_consistency_test.py`. Expected: FAIL for the new subcommands and config keys
- [ ] **Step 3: Update** the README Usage block (`show`, `forget`, `search --only/--repo`, `prune --archive/--yes`); rewrite "How it works" (ingest of text plus stubs, FTS5, optional LLM metadata, redaction, archive-only mode); document every `[ingest]` key and `[indexing] enabled`; split cost text into LLM-only costs versus the roughly 0.5 MB-per-session disk figure measured in Task 15; document the three hook events and what each does (`Stop` per turn, `SessionEnd` final state, `SessionStart` catch-up), including that `Stop` does not fire on interrupts or API errors and that hooks are skipped under `--bare` and `disableAllHooks`; state that **`claude purge` and the retention sweep do not delete the towit archive** and show `towit forget --folder <path>` for removing it; Requirements notes FTS5 (checked by `towit doctor`); "Uninstalling" warns that `teardown` and `implode` delete the archive, which may be the only copy once Claude Code purges transcripts. Update the `bin/towit` usage comment and `_CONFIG_TEMPLATE` to match
- [ ] **Step 4: Run** the tests. Expected: PASS. **Step 5: Commit** `git commit -m "docs: document the full-text archive in README and help text"`

**Slice B: AGENTS.md** (also fixes drift that predates this feature)
- [ ] **Step 1: Write tests** `test_every_env_var_documented_in_agents_md` (every `TOWIT_[A-Z_]+` read from `os.environ` under `libexec/towit/` appears in the AGENTS.md environment table; `TOWIT_CONFIG_PATH` and `TOWIT_DB_PATH` are missing today); `test_every_schema_table_in_agents_md` (each `CREATE [VIRTUAL] TABLE` name in `towit_db.py`; `keywords` and `conversation_keywords` are missing today); `test_every_non_subcommand_module_in_agents_md` (each `libexec/towit/towit_*.py` not invoked by a dispatcher case); `test_claude_md_imports_agents_md`
- [ ] **Step 2: Run.** Expected: FAIL (the first three)
- [ ] **Step 3: Update** AGENTS.md: project description; hook flow (three events, detached process, catch-up scan, `meta` table); module list (add `towit_ingest`, `towit_redact`, `towit_show`, `towit_forget`, `towit_config`); Database Schema (all tables plus FTS and the new columns); "JSONL Parsing" (stubs, 50,000-char cap, partial-line tolerance, subagents skipped unless configured); "Re-indexing" (append-only archive plus the separate LLM reindex delta); env-variable table (add `TOWIT_CONFIG_PATH`, `TOWIT_DB_PATH` as deprecated); Security Constraints (redaction, `safe_subprocess_env`); Test Structure (new files). Release Process section unchanged unless Task 17 changes the skill
- [ ] **Step 4: Run.** Expected: PASS. **Step 5: Commit** `git commit -m "docs: update AGENTS.md for the archive and fix schema and env drift"`

**Slice C: SECURITY.md**
- [ ] **Step 1: Write tests** `test_security_allowlist_matches_source` (prefixes in SECURITY.md's subprocess-allowlist sentence equal `_PASS_THROUGH_PREFIXES` in `towit_config.py`; compare as sets after normalizing `LC_*`/`LC_`); `test_security_documents_archive_controls` (mentions `redact`, `forget`, `FTS5`, `claude purge`, `SessionEnd`)
- [ ] **Step 2: Run.** Expected: FAIL on the second
- [ ] **Step 3: Update** SECURITY.md: the database now holds full message text, not just metadata; state that `claude purge` and the retention sweep do not remove archived data and that `forget` (including `--repo`/`--folder`) is the removal path, and that hook payload `transcript_path` is validated for all three events; add controls: best-effort secret redaction (explicitly not a guarantee), `forget` with its tombstone, FTS5 queries built from quoted phrases with bound parameters, the `git rev-parse` subprocess (list form, scoped env, 5 s timeout, never `shell=True`), the per-message size cap, folder scoping; update the trust-boundary table. Keep the allowlist sentence identical to the source
- [ ] **Step 4: Run.** Expected: PASS. **Step 5: Commit** `git commit -m "docs: update SECURITY.md for the full-text archive"`

**Slice D: CHANGELOG, spec, and release gate**
- [ ] **Step 1: Write test** `test_changelog_has_unreleased_content` (the `## [Unreleased]` section is non-empty; skipped unless `TOWIT_RELEASE_CHECK=1`, so it gates releases only). It fails with `TOWIT_RELEASE_CHECK=1` until Step 3
- [ ] **Step 2: Run** `TOWIT_RELEASE_CHECK=1 ./run-tests tests/helpers/docs_consistency_test.py`. Expected: FAIL
- [ ] **Step 3: Update** `CHANGELOG.md` under `## [Unreleased]`: **Added** (archive, `show`, `forget`, `search --only/--repo`, `[ingest]` settings, `[indexing] enabled`, redaction, `doctor` FTS5 and archive checks, `stats` archive counts); **Changed** (search default scope now includes message text, `prune` no longer removes archived rows by default, `backfill` ingests messages, LLM transcripts are redacted, the hook ingests in the background; state that these are behavior changes made in a 0.x release); **Fixed** (`towit setup --full` now generates `~/.towit/config.toml` as documented); **Security** (redaction and `forget`). Update the spec: `Status: Implemented`, fold in every row of the "Deviations" table and the Task 15 decisions, link this plan
- [ ] **Step 4: Run** the same command. Expected: PASS. **Step 5: Commit** `git commit -m "docs: update CHANGELOG and spec for the full-text archive"`

**Slice E: claim-by-claim audit (what tests cannot see)**
- [ ] **Step 1:** For each of `README.md`, `SECURITY.md`, `AGENTS.md`, `CHANGELOG.md`, list every factual claim (defaults, numbers, file modes, flag behavior, exit codes, paths, version requirements) and verify it against the code with `rg` or by running the command. Examples, not exhaustive: SECURITY's file modes against `towit_setup.py` and `towit_db.py`; README defaults against `towit_config.py`; README's `doctor` check count against `towit_doctor.py`; every README and AGENTS example command runs against a temp DB
- [ ] **Step 2:** Fix discrepancies (docs, or code if the doc was right) with tests where the check is mechanical; **Step 3: Run** `./run-tests` and `TOWIT_RELEASE_CHECK=1 ./run-tests tests/helpers/docs_consistency_test.py`. Expected: all pass
- [ ] **Step 4:** Push the branch, open a PR, and wait for the user to merge it

---

### Task 17: Update the project skills (approved by the user for both skills)

The existing skills conflict with this work in the ways below. The user approved editing both skills on 2026-11-10; the edits ship in their own PR, separate from the archive PR.

**Files:** `.claude/skills/release-towit/SKILL.md`, `.claude/skills/feature-dev-towit/SKILL.md`

- [ ] **Step 1: `release-towit`:** (a) add a preconditions step: on `main`, clean, up to date with `origin`, `./run-tests` and `TOWIT_RELEASE_CHECK=1 ./run-tests tests/helpers/docs_consistency_test.py` green; (b) validate the version: SemVer 2.0.0 pattern `^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$`, strictly greater than the latest tag, tag unused; (c) extend the audit to `SECURITY.md` and `AGENTS.md`; (d) replace the direct `git push origin main` with: release commit on `chore/release-vX.Y.Z`, PR, merge by the user, then tag the merged commit on `main` and push only the tag; (e) date via `gdate +%F`
- [ ] **Step 2: `feature-dev-towit`:** (a) widen Step 5 docs scope to `SECURITY.md` (trust boundaries or controls change) and `AGENTS.md` (modules, schema, env vars, constraints change), with the docs-consistency test as the check; (b) update the optimization-checklist hook path to `towit_hook.py` → `towit_ingest.py` → `towit_index.py` and add "Does this store new user content? If so, redaction, `forget`, and SECURITY.md"; (c) note the `towit_doctor.py` exception to "all SQL in `towit_db.py`"
- [ ] **Step 3:** Re-read both skills end to end for contradictions with AGENTS.md and the user's global rules; **Step 4: Commit** `git commit -m "chore: update project skills for the archive and PR-only merges"` (on a branch, via PR)

---

### Task 18: Release (on `main`, via the `release-towit` skill)

Prerequisites: the PRs from Tasks 16 and 17 are merged into `main`; local `main` is up to date and clean; `./run-tests` and `TOWIT_RELEASE_CHECK=1 ./run-tests tests/helpers/docs_consistency_test.py` pass. Read `.claude/skills/release-towit/SKILL.md` with the Read tool and follow it exactly; do not bypass it. Task 17 must be merged first so the skill no longer pushes `main` directly; if it was not, stop and ask the user before Step 5.

- [ ] **Step 1: Determine the version.** Current tag is `v0.8.2` (`git tag --sort=-version:refname | head -1`). Ask the user the release level, recommending **minor → `0.9.0`**: new subcommands and a new storage layer are features, and because MAJOR is `0` SemVer 2.0.0 allows the changed `search` and `prune` defaults in a minor release (patch would be wrong; `1.0.0` is a separate user decision about declaring a stable API). Validate: matches `^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$`, strictly greater than the latest tag, and `git tag -l v0.9.0` is empty
- [ ] **Step 2: Audit help and README (skill Step 2).** `bin/towit help` against README Usage and the implementation; stop and fix `bin/towit` before proceeding if they disagree. Present the README audit summary and wait for approval before any README edit. Also re-run the `SECURITY.md` and `AGENTS.md` checks against the final tree
- [ ] **Step 3: Update `CHANGELOG.md` (skill Step 3).** Replace `## [Unreleased]` with an empty `## [Unreleased]` followed by `## [0.9.0] - <today, from gdate +%F>`, moving the content unchanged
- [ ] **Step 4: Commit (skill Step 4).** Show the diff and wait for approval, then `git add CHANGELOG.md` (plus README.md if edited) and `git commit -m "chore: release v0.9.0"`
- [ ] **Step 5: Tag and push (skill Step 5), with explicit user approval before each push.** `git tag v0.9.0`, then push per the updated skill (tag only, after the release commit is on `main` via PR); if the skill is unchanged, ask first
- [ ] **Step 6: Verify.** `git tag -l v0.9.0` prints the tag; `git rev-parse v0.9.0^{commit}` equals the intended release commit; `git ls-remote --tags origin v0.9.0` shows it on the remote; report the tag name and commit SHA
