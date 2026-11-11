# Security Policy

## Scope and Threat Model

To Wit (`towit`) is a single-user CLI tool. It runs entirely on your local machine, writes only to `~/.towit/` and `~/.claude/settings.json`, makes no network requests of its own, and has no server component. The primary assets it protects are your Claude Code conversations and the metadata extracted from them (titles, summaries, topics, keywords). The database holds the **full text of your messages** (user and assistant turns, plus one-line tool-call stubs and truncated tool errors), not just metadata, so it may contain proprietary code, internal URLs, API usage patterns, pasted secrets that redaction missed, and other sensitive work content. It keeps that text after Claude Code deletes the original transcripts.

### Trust Boundaries

| Boundary | Trust Level | Notes |
| --- | --- | --- |
| Claude Code JSONL transcripts | High | Written by Claude Code itself; may indirectly contain untrusted external data (e.g. pasted content) |
| Claude CLI responses (indexing) | Medium | Parsed with error handling; treated as structured JSON with graceful fallback |
| Hook payload (stdin JSON) | Medium | Provided by Claude Code for `Stop`, `SessionEnd`, and `SessionStart`; `session_id` format and the `transcript_path` filesystem path are validated before use (`SessionStart` uses no path from the payload) |
| Archived message text | Medium | Originates in transcripts, so it can carry tool output, web content, or terminal escape sequences; `towit show` strips control sequences before printing, and `towit search` and `towit list` do the same for their table output (JSON output ASCII-escapes instead; CSV is printed raw); never interpreted as SQL or FTS5 syntax |
| Search terms (CLI arguments) | Medium | Escaped into quoted FTS5 phrases and bound as parameters |
| Environment variables | Medium | Used for config overrides; subprocess env is scoped to an explicit allowlist |
| SQLite database | High | Local file; no network exposure; holds full message text |

### Out of Scope

- Attacks requiring physical access to your machine or control of your user account
- Vulnerabilities in Claude Code, the Anthropic API, or the `claude` CLI itself
- Issues in Python's standard library or the operating system

## Security Controls

### Data at Rest

- The database directory (`~/.towit/`) is created with mode `0700`; the database file is created with mode `0600` (owner-only, using `umask(0o077)` at creation time); `towit doctor` warns if either drifts
- No conversation content is written outside `~/.towit/` and `~/.claude/`
- **The archive outlives Claude Code's own retention.** `claude purge`, `claude rm`, and the `cleanupPeriodDays` retention sweep do **not** remove archived data. `towit prune` keeps archived conversations unless you pass `--archive`, and merely reports ones whose project folder has disappeared. `towit forget` (by session id, `--repo`, or `--folder`) is the removal path, and `towit teardown` / `towit implode` delete the whole database
- Secrets are redacted on a best-effort basis (see Secret Redaction); this is **not** a guarantee and does not reduce the sensitivity of the file itself

### Secret Redaction

- Message text is scanned for secret-shaped strings (AWS key ids, GitHub, Anthropic, OpenAI, Stripe, and Slack tokens, JWTs, private-key blocks, `Bearer` tokens, credentials embedded in URLs, and long `*_KEY` / `*_SECRET` / `*_TOKEN` / `*_PASSWORD` assignment values) and matches are replaced with `[REDACTED:<kind>]` **before** they are written to the database. The same redaction is applied to the transcript text sent to the `claude` CLI for metadata generation and for `export --summarize`. Add patterns with `[ingest] extra_patterns`; disable with `[ingest] redact = false`
- Redaction is pattern-based and best effort. It will miss secrets in unfamiliar formats, and it runs at ingest time only: archived rows are not rewritten if you change the setting later. Use `towit forget` to remove a conversation that contains a secret
- Only tool-call stubs (at most 200 characters of a description, command, or path) and truncated error results (at most 300 characters) are stored; tool results and file contents are not archived. A single message is capped at 50,000 characters

### Deleting Data (`towit forget`)

- `towit forget <session-id>`, `--repo <path|name>`, and `--folder <path>` permanently delete conversations with their messages, search-index entries, topics, and keywords, after a confirmation prompt (or `--yes`)
- A tombstone (the session id and a timestamp only) is kept so that `backfill`, the hooks, and the catch-up scan cannot re-ingest a conversation from a transcript that is still on disk
- Deletion is physical, not just logical: `PRAGMA secure_delete=ON` zeroes freed pages, the FTS5 index is merged (`optimize`), and a `VACUUM` plus write-ahead-log truncate follow (`towit prune --archive` deletes the same way, without a tombstone). If that cleanup cannot finish, `forget` warns on stderr and `towit forget <session-id>` can be re-run to retry
- The original transcripts under `~/.claude/projects/` are not touched

### Input Validation

- `session_id` values are validated against a strict alphanumeric pattern (`^[a-zA-Z0-9_-]{8,}\Z`) before being used in path construction
- `transcript_path` values from `Stop` and `SessionEnd` hook payloads, and the path handed to the detached ingest process, are resolved with `os.path.realpath()` and verified to be children of `~/.claude/projects/` before any file is read. The `SessionStart` catch-up scan walks `~/.claude/projects/` itself and uses nothing from the payload
- Symlinked JSONL files are excluded from backfill, the catch-up scan, and ingest to prevent traversal outside the expected directory tree
- `[ingest] folders` restricts archiving (and LLM indexing) to matching project folders; subagent transcripts are skipped unless `include_subagents` is set

### SQL Safety

- All database queries use parameterized statements (`?` placeholders) exclusively
- Dynamic WHERE clauses are built only from hardcoded string literals, enforced by a runtime `assert`; no user input ever enters the query structure
- Full-text search input is never passed to FTS5 as-is: each search term is wrapped into a quoted phrase (embedded quotes doubled) and bound as a single parameter, so operators, column filters, and punctuation are literal and cannot cause syntax errors or alter the query

### Subprocess Safety

- The `claude` subprocess is invoked with a list (never `shell=True`)
- The subprocess environment for indexing and export (the claude calls) is scoped to an explicit prefix allowlist (`HOME`, `PATH`, `USER`, `TMPDIR`, `TERM`, `LANG`, `LC_*`, `CLAUDE_*`, `ANTHROPIC_*`) to avoid leaking unrelated credentials.
- `towit resume` replaces itself with an interactive `claude --resume` and keeps your full environment by design; it is not a scoped subprocess
- `towit export --summarize` sends the original transcript to the `claude` CLI at your request, with the same scoped environment as indexing. When `[ingest] redact` is on (the default) the text is redacted at send time with the same patterns, including `extra_patterns`; with it off, the text is sent unchanged. `towit export --topic <name> --summarize` sends stored summaries, redacted at send time the same way, which also covers rows indexed by 0.8.2 or earlier whose summaries were generated from unredacted transcripts. Redaction is best effort (see Secret Redaction)
- Ingest runs `git -C <cwd> rev-parse --git-common-dir` to group worktrees of one repo. It is invoked with a list (never `shell=True`), with the same scoped environment, a 5-second timeout, and any failure falls back to the working directory

### Settings File Writes

- Writes to `~/.claude/settings.json` are atomic: a temp file is written and renamed via `os.replace()`
- The `TOWIT_SETTINGS_PATH` override is validated to be within `~/.claude/` or the system temp directory

### Error Handling

- The hooks (`Stop`, `SessionEnd`, `SessionStart`) catch all exceptions and never exit non-zero (to avoid interrupting Claude Code). Work runs in a detached background process, so a slow or failing ingest can never block a session or exceed `SessionEnd`'s time budget; a `TOWIT_INDEXING` guard stops towit's own `claude` calls from triggering the hooks recursively
- Errors are logged to `~/.towit/errors.log` (rotating, 100 KB max, 2 backups, owner-only `0600`) for post-hoc debugging

## Reporting a Vulnerability

This is a personal open-source project with no bug bounty program.

Please report security vulnerabilities through [GitHub Private Vulnerability Reporting](https://github.com/chrisbloom7/to-wit/security). This keeps the details confidential until a fix is available. Confirmed vulnerabilities will be published as GitHub Security Advisories in the same location.

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce or a minimal proof of concept
- The version or commit hash you tested against

I aim to acknowledge reports within a few days and resolve confirmed issues before the next release.
