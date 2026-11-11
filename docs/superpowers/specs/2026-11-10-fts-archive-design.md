# Full-Text Archive Design

**Date:** 2026-11-10
**Status:** Implemented
**Plan:** [2026-11-10-fts-archive.md](../plans/2026-11-10-fts-archive.md)

This document describes the design. Where the shipped behavior differs, see "Deviations and Notes" and "Live Trial Results" at the end; those sections, and the README, describe what the code does.

## Overview

Today To Wit stores only LLM-generated metadata (title, summary, keywords, topics). The message text is parsed, sent to Claude, and discarded. Search is `LIKE` over those four fields, so a conversation is only findable by what the model chose to extract. For long sessions the model sees only 8,000 characters (30% head / 70% tail), so the middle is invisible even to metadata.

This change makes the **raw conversation text the primary, searchable record**, stored in SQLite with FTS5. LLM-generated metadata stays, but stops being the only index and stops gating what is archived.

Claude Code deletes transcripts after `cleanupPeriodDays` (default 30), and its own `/resume` picker searches session names, not conversation content (verified; see "Verified: `/resume` does not search assistant text"). An archive that outlives the purge and searches message text is the capability To Wit adds that built-in tooling does not document.

## Goals

- Store user and assistant message text, plus short tool-call stubs, for every substantive session
- Search the full text with ranked results and readable snippets, in milliseconds, with no API calls
- Keep the archive after Claude Code purges the source transcript
- Ingest incrementally and cheaply so it can run inside the stop hook
- Redact secret-shaped strings before they reach the database or the LLM
- Let a user remove a conversation permanently (`forget`)
- Remain backward compatible: existing catalogs migrate in place and existing commands keep working

## Non-Goals

- **Enrichment redesign.** Decoupling the LLM step into a batch `towit enrich` command, and changing *when* the LLM runs (once at `SessionEnd` plus a bounded startup catch-up, replacing the per-turn `reindex_delta` throttle), is a separate follow-up spec. This spec leaves LLM indexing running as it does today (with one safety change, below).
- **MCP server or skill** for letting Claude query the archive. Also a follow-up; this spec only guarantees `--format json` output carries what such a layer needs.
- Semantic or embedding search
- Storing tool *results* or file contents (see Evidence)
- Guaranteeing secret removal. Redaction is best-effort

## Evidence from Prototype

A throwaway prototype (scratchpad, not in repo) ingested 31 real sessions (~6,300 messages, 8.7 MB of text). Findings that drive decisions below:

| Question | Result | Decision |
|---|---|---|
| Ingest speed | 0.9 s for the whole corpus, no network | Safe to run synchronously in the hook |
| Size | ~300 KB text and ~500 KB DB per session on average | Document in README. The live trial later measured ~0.7 MB per top-level session on a heavy-use project (see Live Trial Results) |
| Tokenizer | `unicode61` with `tokenchars '_-.'`: 14.7 MB, clean snippets. `trigram`: 33.4 MB, broken snippets, noisy substring hits | `unicode61` default; trigram not offered in this spec |
| Identifier search | `TOWIT_INDEXING` matched whole under `unicode61` | Required `tokenchars` setting |
| Unquoted multi-word | `stop hook` returned 37 hits, mostly the word "stop"; quoted returned 2 | Quoted input is a phrase query (see Search) |
| Tool stubs | +8% text, 6,289 → 14,237 rows | Store stubs |
| Incremental append | 30 sessions: stable prefix, identical to full ingest, no duplicate uuids | Append-only ingest by `seq` |
| Secrets | In stored text and stubs: 3 hits in ~6,300 messages (2 credentialed DB URLs, 1 assignment). In raw tool inputs/results: ~286 hits (crude regex, some false positives) | Store stubs only; run redaction at ingest |

Not covered by the prototype: Claude Code compaction/rewind behavior, ranking quality on a large corpus, subagent transcripts, backfill at scale.

## Schema

New tables, added by `towit setup` migrations (same add-if-missing pattern as existing migrations):

```sql
CREATE TABLE IF NOT EXISTS messages (
  id              INTEGER PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq             INTEGER NOT NULL,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
  ts              TEXT,
  text            TEXT NOT NULL,
  UNIQUE (conversation_id, seq)
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  text, content='messages', content_rowid='id',
  tokenize="unicode61 tokenchars '_-.'"
);
-- plus AFTER INSERT / DELETE / UPDATE triggers keeping messages_fts in sync,
-- so FK cascades from conversations also clean the index.

CREATE TABLE IF NOT EXISTS forgotten (id TEXT PRIMARY KEY, forgotten_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- e.g. last catch-up scan time
```

New nullable columns on `conversations`: `tail_hash TEXT` (hash of the last stored message, for the rewrite guard), `source_path TEXT`, `archived INTEGER NOT NULL DEFAULT 0` (1 once messages are stored), `repo_key TEXT` (see Decisions).

`title` and `summary` remain nullable in practice: when metadata is absent, display falls back to the first user message, truncated to 80 characters.

Tool stubs are stored as part of the message `text` of the assistant turn that made the call (`[Bash] <description or command, ≤200 chars>`, `[Edit] <file_path>`), not as separate rows. Failed tool results are appended as `[error] <≤300 chars>`.

## Ingest

New module `towit_ingest.py`, one function per concern (parse, redact, store), reusing `towit_db.py` for all SQL.

1. **Parse.** Extend `parse_jsonl` (or add a sibling) to emit text plus stubs and truncated error results, in order. Existing callers of `parse_jsonl` are unaffected by default.
2. **Skip rules.** Skip subagent paths unless `include_subagents` is set, symlinks, and sessions with fewer than 2 user messages. The LLM `skip` flag no longer affects archiving.
3. **Redact** each message (see Redaction).
4. **Append-only store.** Read `message_count` and `tail_hash` for the conversation. If the stored tail matches the message at `count-1`, append messages from `count` onward. If it does not match (compaction or rewrite), delete and re-ingest that conversation in one transaction.
5. **Forgotten check.** Never ingest an id present in `forgotten`.
6. Whole-session ingest runs in a single transaction.

Ingest is deterministic, needs no network, and is idempotent.

## Hooks and Capture

Capture must not depend on `Stop` alone. Findings from the Claude Code hook docs (code.claude.com/docs/en/hooks.md, fetched 2026-11-10):

| Situation | `Stop` | `SessionEnd` |
|---|---|---|
| Normal turn finishes | fires, once per turn | n/a |
| Exit, `/clear`, resume another session | no | fires (`reason`: clear, resume, logout, prompt_input_exit, other) |
| User interrupt (Esc) | does not fire | n/a |
| API error | `StopFailure` fires instead | n/a |
| Crash, `kill -9`, terminal closed, background (`--bg`) sessions | not documented | not documented |
| `--bare`, `--safe-mode`, `disableAllHooks: true` | skipped | skipped |

Also: the `Stop` payload docs warn the transcript file may not yet contain the final message when `Stop` fires; `SessionEnd` has a default budget of 1.5 s; no hook event fires when transcripts are deleted (sweep, `claude purge`, `claude rm`).

**`towit install-hook` registers three events**, all pointing at `towit_hook.py`, which dispatches on the payload's `hook_event_name`:

| Event | Matcher | Behavior |
|---|---|---|
| `Stop` | (all) | Spawn the detached background process: ingest, then LLM indexing as today. Keeps the archive fresh turn by turn |
| `SessionEnd` | (all) | Same as `Stop`. Captures the final state once the transcript is complete, including the last message `Stop` may have missed |
| `SessionStart` | `startup` | Spawn a detached **catch-up scan**: ingest-only (no LLM calls) for every transcript modified since the last scan, covering crashes and missed hooks |

Rules for all three: validate `transcript_path` as today, never block, never exit non-zero, log failures to `errors.log`, keep the `TOWIT_INDEXING` recursion guard. Work always runs in a detached process (`start_new_session=True`) so the `SessionEnd` budget is never an issue. The detached process ingests first, then, for `Stop` and `SessionEnd` only and when `[indexing] enabled` is true (default), runs the existing LLM indexer. `[indexing] enabled = false` gives archive-only operation at zero API cost.

The catch-up scan keeps its last-scan timestamp in a `meta` table (`get_meta`/`set_meta`). With no timestamp it scans every eligible transcript, as `backfill` would, ingest-only. `install-hook`, `uninstall-hook`, and `doctor` handle all three events; `doctor` also warns when `disableAllHooks` is true or `SessionEnd`/`SessionStart` is not registered. Known limits: the retention sweep's timing and age basis (file mtime or session start) are undocumented, so a session that was never captured by any hook and is older than `cleanupPeriodDays` can be lost before a catch-up runs; raising `cleanupPeriodDays` narrows that window.

## Search

`towit search` default scope becomes **message text plus keywords, title and summary**, ranked together by FTS5 `bm25` with column weights favoring metadata hits. Existing flags keep their meaning (`--topic`, `--summary`, `--title`, `--all`, `--or`, `--folder`, `--format`); a new `--only text|metadata` narrows scope. This changes default behavior from v0.6.0 ("keywords only"), so it must be called out in the changelog.

**Query handling:**
- Each argument is a term. Terms combine with AND (or OR with `--or`), as today.
- An argument containing whitespace is a **phrase**, so `towit search "stop hook"` is exact.
- User input is escaped before reaching FTS5 so operators and punctuation cannot raise syntax errors; parameterized queries only, per the security constraints.

**Output.** Results group by conversation and show the best-matching turn:

```
ID        Date        Title                           Turn  Snippet
350fa22f  2026-03-31  Debugging non-firing Stop …     14    …the [recursion] [guard] stays…
```

JSON/CSV include `conversation_id`, `seq`, `snippet`, `score`, and the metadata fields.

### `towit show <session-id> [--around <seq>] [--context N]`

Prints stored messages (default: the whole conversation, or N messages either side of `seq`). Replaces the need to `export` just to read a hit. Works after the source transcript is purged.

## Redaction

Applied to every message before it is written, and **also to the transcript sent to Claude** for metadata generation, so summaries cannot carry secrets.

Initial patterns (replaced with `[REDACTED:<kind>]`): AWS key ids, GitHub tokens, Anthropic and OpenAI-style keys, Stripe keys, Slack tokens, JWTs, private-key headers, `Bearer` tokens, credentials embedded in URLs, and `*_KEY|SECRET|TOKEN|PASSWORD` assignments with long values.

```toml
[ingest]
redact = true            # default
extra_patterns = []      # user-supplied regexes
```

Limitations stated in the README: best-effort, pattern-based, no guarantee. Redacted text cannot be searched by its original value.

### `towit forget`

`towit forget <session-id>` deletes the conversation, its messages and FTS rows, and records the id in `forgotten` so a later backfill, hook run, or catch-up scan cannot resurrect it from a still-present transcript. Bulk forms: `towit forget --repo <path|name>` and `towit forget --folder <path>` forget every matching conversation (`--folder` matches the conversation's working directory exactly, as in `search` and `list`; `--repo` matches `repo_key` exactly or by final path component). All forms print how many conversations will be deleted and ask for confirmation unless `--yes` is given.

## Retention and `prune`

`prune` currently deletes entries whose transcripts are missing. In an archive that is the wrong default.

- `prune` (new default) removes only conversations with `archived = 0` whose transcript is gone
- **Towit never mirrors Claude Code's deletions.** The retention sweep is the thing the archive exists to outlive, and no hook fires on deletion, so the archive keeps conversations by default
- `claude purge` is different in intent (an explicit user deletion) but looks the same afterwards. `claude purge <path>` removes a project's whole `~/.claude/projects/<project>/` folder at once, whereas the sweep removes individual old files from folders that still exist. So `prune` also **reports** archived conversations whose entire project folder (`conversations.folder`) is gone, under a heading "Likely removed by `claude purge`" with a count, and never deletes them without confirmation. A manually deleted folder looks identical, which is why this is a report and not an action. After `claude purge --all` the report will list everything, so the confirmation prompt shows the count
- `prune --archive` removes archived conversations with missing transcripts, after confirmation (`--yes` skips the prompt)
- README and SECURITY.md state plainly that **`claude purge` does not delete the towit archive**; users who want it gone use `towit forget --folder <path>` or `--repo`
- `stats` reports archived vs. metadata-only conversation counts and DB size

## Migration

- `towit setup` adds the tables and columns idempotently (existing `message_count` is reused).
- `towit backfill` gains ingest: for each transcript still on disk, it ingests messages whether or not the conversation already has LLM metadata. Without `--force` it does not re-run the LLM for already-indexed sessions.
- Existing rows whose transcripts are gone remain, metadata-only, still searchable by metadata. `archived = 0` marks them.
- Schema version check in `towit doctor` gains: FTS5 compiled into this SQLite, `messages_fts` present and consistent (`INSERT INTO messages_fts(messages_fts) VALUES('integrity-check')`).

## Configuration

```toml
[ingest]
redact = true
extra_patterns = []
include_subagents = false     # see Decisions
folders = []                  # empty = all; otherwise only project folders matching these globs

[indexing]
enabled = true                # false = archive only; no LLM calls
```

`folders` doubles as the scoping mechanism for the live trial below.

## Test Strategy

Per AGENTS.md: tests first, confirm failing, implement, confirm passing.

**Python unit tests** (`tests/helpers/`):
- `towit_ingest_test.py`: stubs and error truncation; ordering; skip rules; append-only equals full ingest; tail-hash mismatch triggers clean re-ingest; `forgotten` blocks ingest; transaction rollback on error
- `towit_redact_test.py`: each pattern; no false positive on ordinary prose and code; custom patterns; idempotence
- `towit_db_test.py`: FTS triggers on insert/delete/cascade; `bm25` ordering with weights; phrase vs AND vs OR; punctuation and operator characters in queries do not raise; identifier with underscores matches whole
- `towit_search_test.py`: default scope, `--only`, snippet and JSON fields, folder filter
- `towit_prune_test.py`, `towit_stats_test.py`, `towit_doctor_test.py`: new behavior

**BATS** (`tests/bin/towit.bats`): end-to-end `backfill` → `search` → `show` → `forget` → `search` on fixture transcripts containing a planted fake secret; `prune` leaves archived rows; migration from a v0.8.2-shaped DB.

**Fixtures:** small synthetic JSONL files only. Never commit real transcripts.

## Live Trial (Robinina-LLC)

The two repos in `../../Robinina-LLC` (`studio-app`, `studio-docs`) spawn many sibling worktrees and are a good test bed for three things the fixtures cannot cover: worktree grouping, subagent volume, and ranking against real queries.

1. **Isolated database.** Point `TOWIT_CONFIG_PATH` at a trial config with its own `[database] path` so the trial never touches a production catalog.
2. **Scoped.** `folders = ["*Robinina-LLC*"]` limits ingest, including the hook if installed, to those projects.
3. **Two passes.** Run once with `include_subagents = false` and once with `true`; compare size, ingest time, and whether the extra transcripts surface anything the user would want to find.
4. **Known-answer queries.** Before running, the user writes ~10 queries where they know which conversation should win. Acceptance: the intended session appears in the top 3 for at least 8 of 10, with a readable snippet.
5. **Hygiene scan.** After ingest, run the redaction scanner over the database and expect zero hits, counts only, never printing values.
6. **Measure and record:** DB size, ingest time, query latency, number of sessions, and whether `repo_key` groups worktree sessions correctly.

The trial is done when the acceptance bar is met or the shortfall is understood. Only then is a release cut via the `release-towit` skill.

## Risks

- **Privacy.** A durable full-text archive of everything said is more sensitive than metadata. Mitigations: 0600/0700 permissions (already enforced), redaction, `forget`, scoped `folders`, README disclosure.
- **Hook gaps.** `Stop` skips interrupts and API errors, and no hook is documented for crashes or `kill -9`. Mitigated by `SessionEnd` and the `SessionStart` catch-up scan, not eliminated
- **Transcript format drift.** The docs describe the JSONL format as internal. All parsing stays in one place, covered by fixtures, and `doctor` can warn when a transcript yields zero messages.
- **Compaction and rewind.** Untested. The `tail_hash` guard degrades to a safe re-ingest rather than corrupting the archive.
- **Default-behavior change** in `search`. Documented in the changelog; `--only metadata` restores the old scope.
- **Disk growth.** Prototype estimate ~0.5 MB per session; the live trial measured ~0.7 MB per top-level session (16.4 MB / 24 sessions). Surfaced in `stats`.

## Decisions

Resolved on 2026-11-10:

1. **Subagent transcripts: excluded by default.** `include_subagents = false` stays the default, matching current backfill. The Robinina trial ran both modes and the numbers support keeping it off (see Live Trial Results); the decision is confirmed pending the known-answer step.
2. **Worktree grouping: by git common dir.** At ingest, resolve `git rev-parse --git-common-dir` from the session `cwd` and store the result in a new nullable `conversations.repo_key` column (index it; `--repo <path|name>` filters on it). If `cwd` no longer exists or is not a git checkout, fall back to `cwd`. Resolution happens once at first ingest and is never recomputed, so deleted worktrees keep their key. `--folder` keeps its current meaning.
3. **Stub depth: `description`, falling back to `command`.** For `Bash` stubs. Other tools use the first available of the existing key list.
4. **Removed worktrees keep their transcripts.** Project folders for worktrees that no longer exist (e.g. `docs-beta-testing`, `studio-app-neato-logo-placements` under `~/.claude/projects`) are still present, so removal does not delete transcripts, only the 30-day purge does. The archive therefore matters for retention, not recovery from worktree removal. `prune` still must not treat a missing `cwd` as a reason to delete archived rows.
5. **Do not purge towit's data by default; detect and offer.** See Retention and `prune`. No hook exists for deletions, so towit cannot mirror them; an explicit `claude purge` is surfaced by `prune` (folder-gone heuristic) and by the documented `forget --folder`.
6. **Three hook events, not one.** `Stop`, `SessionEnd`, and a `SessionStart` catch-up scan; see Hooks and Capture. LLM trigger changes are deferred to the enrichment follow-up.

## Verified: `/resume` does not search assistant text

Tested 2026-11-10 on Claude Code 2.1.311 in an isolated directory, interactive session, two turns:

| Search | Exists in | Result |
|---|---|---|
| `xenraflliuq` | first user prompt (and generated title) | matched |
| `qiullfarex` | assistant reply only | **no match** |
| `zzvbntqplx` | nowhere | no match (search is not fuzzy) |

The first attempt used a string the model failed to produce (it mis-reversed the word), which was caught by checking the transcript JSONL. The valid assistant-only string was taken from the transcript itself. Conclusion: the picker matches the displayed fields (title, first prompt), not message bodies. Searching what Claude said or decided remains unserved by built-in tooling, which confirms the core pitch. Caveats: one tool version, one two-turn session, and the string was typed by hand.

## Open Questions

None blocking, except the pending known-answer step in Live Trial Results. Items 1–3 under "Not covered by the prototype" in Evidence (compaction/rewind, ranking at scale, backfill at scale) remain to be measured during the live trial.

## Follow-Up Specs

1. **Batch enrichment:** `towit enrich`, selection by `enriched_at`, `--limit`/`--dry-run`, locking, optional chunked summarization; move the LLM trigger from every `Stop` to `SessionEnd` plus the `SessionStart` catch-up (bounded by `--limit`), replacing the `reindex_delta` throttle
2. **Agent access:** skill and/or `towit mcp` stdio server exposing `search`, `show`, `list` with result-size caps and untrusted-content framing

## Deviations and Notes

What shipped differs from the text above in these ways. The first five were planned before implementation; the rest were found while building and documenting it.

| Spec says | Shipped | Why |
|---|---|---|
| Reuse `conversations.message_count` | New column `archived_message_count` | `message_count` is the prose-only count that drives `reindex_delta`; archive counts include stubs and would corrupt LLM re-index timing |
| Search ranked together with metadata weighting | Tiered: conversations with a metadata match first, then by best `bm25` | `bm25` scores and `LIKE` matches are not comparable. Revisit with real queries (see the pending known-answer step) |
| (silent) | Per-message cap of 50,000 characters | A pasted log must not bloat the archive |
| JSON output includes `conversation_id` | JSON keeps the existing `id` key and adds `seq`, `snippet`, `score` (`show --format json` is an array of `seq`, `role`, `ts`, `text`) | Avoids breaking existing consumers |
| (silent) | `Database.is_indexed` means "has a non-null title" | Ingest creates rows with no title; backfill's dry run must not call them indexed |
| Search output example (`ID` truncated to 8 characters, Date before Title) | Table columns are ID (full), Title, Keywords, Turn, Snippet, Date, grouped by working directory; "Turn" is the 0-based `seq` | Kept the existing table layout and added columns |
| `repo_key` is "resolved once at first ingest and never recomputed" | `towit_ingest` re-resolves it on every ingest of a session, and `archive_session` overwrites the stored value. A later `backfill` (or any hook run) after a worktree was deleted replaces a good key with the now-missing `cwd` | Observed in the final audit. Sessions from already-deleted worktrees (live trial: `studio-app.phase-2a-payments`) therefore do not group under the main repo. Not fixed here; documented in the README |
| (silent) | `include_subagents` affects `backfill` and the `SessionStart` catch-up scan only. The `Stop` and `SessionEnd` hooks never ingest subagent transcripts, and subagent sessions are never LLM-indexed | Subagent sessions are not interactive conversations |
| (silent) | Text-only search results are capped at 50 conversations; metadata results are never capped; search arguments with no letter or digit are dropped | Bounded output; FTS5 cannot tokenize them |
| Schema "added by migrations" | `PRAGMA user_version` / `SCHEMA_VERSION`; `Database.validate()` migrates an older database in place on first use | Existing catalogs upgrade without running `towit setup` |
| `forget` deletes rows | Also zeroes freed pages (`secure_delete`), merges the FTS index, runs `VACUUM` and a WAL truncate (cost is proportional to database size). `forget <id>` on an already-forgotten id re-runs that cleanup, which is the retry named in warnings; a failed cleanup warns on stderr and exits 0 | Deleted text must not linger in the file |
| `doctor` gains FTS5 and integrity checks | Also checks all three hook events, that hook command paths exist (fail if none resolve, warn if partial), and `disableAllHooks` in the settings file it is given; the integrity check fails only on corruption and warns if the database is locked or read-only. Up to 17 checks in total | Hook coverage is the main way capture silently fails |
| `prune` reports "Likely removed by `claude purge`" | Subagent conversations have folder `<project>/<session>/subagents`, so a purged subagent session directory also appears in that report | Follows from how folders are stored |
| One LLM call per hook | `Stop` and `SessionEnd` are separate processes; if both run before the first finishes, both may call the LLM for the same session | Cost only; not worth a lock |

## Live Trial Results

Run 2026-11-10 against `../../Robinina-LLC` with an isolated database, `folders = ["*Robinina-LLC*"]`, and `[indexing] enabled = false` (no LLM calls):

| | `include_subagents = false` | `include_subagents = true` |
|---|---|---|
| Conversations | 24 | 597 (568 subagent) |
| Messages archived | 14,003 | 35,203 |
| Database size | 16.4 MB | 27.5 MB |
| Backfill time | 2.8 s (2 skipped) | 8.3 s (3 skipped) |

- **Disk:** about 0.68 MB per top-level session without subagents (16.4 MB / 24); the 568 subagent transcripts add about 11 MB (about 20 KB each). The README states this, not the prototype's 0.5 MB.
- **Query latency:** 60-100 ms per search on the 597-conversation database.
- **Hygiene scan:** 0 unredacted secret-pattern hits in either database (counts only; no values printed).
- **Worktree grouping:** sessions whose worktree had already been deleted when first archived keep their `cwd` as `repo_key` and do not group under the main repo (for example `studio-app.phase-2a-payments` is its own key). See Deviations and Notes.
- **Known-answer queries (~10 queries, intended session in the top 3 for at least 8):** pending; to be recorded by the maintainer. No result is claimed here.

**Decision:** `include_subagents` stays `false`. Archiving subagents multiplies the conversation count about 25x for about 1.7x the disk, mostly transcripts that are not interactive conversations. This is confirmed pending the known-answer step.
