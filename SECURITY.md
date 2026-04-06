# Security Policy

## Scope and Threat Model

To Wit (`towit`) is a single-user CLI tool. It runs entirely on your local machine, writes only to `~/.towit/` and `~/.claude/settings.json`, makes no network requests of its own, and has no server component. The primary assets it protects are your Claude Code conversation transcripts and the metadata extracted from them (titles, summaries, topics), which may contain proprietary code, internal URLs, API usage patterns, and other sensitive work content.

### Trust Boundaries

| Boundary | Trust Level | Notes |
| --- | --- | --- |
| Claude Code JSONL transcripts | High | Written by Claude Code itself; may indirectly contain untrusted external data (e.g. pasted content) |
| Claude CLI responses (indexing) | Medium | Parsed with error handling; treated as structured JSON with graceful fallback |
| Hook payload (stdin JSON) | Medium | Provided by Claude Code; `session_id` format and filesystem path are validated before use |
| Environment variables | Medium | Used for config overrides; subprocess env is scoped to an explicit allowlist |
| SQLite database | High | Local file; no network exposure |

### Out of Scope

- Attacks requiring physical access to your machine or control of your user account
- Vulnerabilities in Claude Code, the Anthropic API, or the `claude` CLI itself
- Issues in Python's standard library or the operating system

## Security Controls

### Data at Rest

- The database directory (`~/.towit/`) is created with mode `0700`; the database file is created with mode `0600` (owner-only, using `umask(0o077)` at creation time)
- No conversation content is written outside `~/.towit/` and `~/.claude/`

### Input Validation

- `session_id` values from the hook payload are validated against a strict alphanumeric pattern (`^[a-zA-Z0-9_-]{8,}$`) before being used in path construction
- All constructed filesystem paths are resolved with `os.path.realpath()` and verified to be children of `~/.claude/projects/` before any file is read
- Symlinked JSONL files are excluded from backfill to prevent traversal outside the expected directory tree

### SQL Safety

- All database queries use parameterized statements (`?` placeholders) exclusively
- Dynamic WHERE clauses are built only from hardcoded string literals, enforced by a runtime `assert`; no user input ever enters the query structure

### Subprocess Safety

- The `claude` subprocess is invoked with a list (never `shell=True`)
- The subprocess environment is scoped to an explicit prefix allowlist (`HOME`, `PATH`, `USER`, `TMPDIR`, `TERM`, `LANG`, `LC_*`, `CLAUDE_*`, `ANTHROPIC_*`) to avoid leaking unrelated credentials

### Settings File Writes

- Writes to `~/.claude/settings.json` are atomic: a temp file is written and renamed via `os.replace()`
- The `TOWIT_SETTINGS_PATH` override is validated to be within `~/.claude/` or the system temp directory

### Error Handling

- The stop hook catches all exceptions and never exits non-zero (to avoid interrupting Claude Code)
- Errors are logged to `~/.towit/errors.log` (rotating, 100 KB max, 2 backups) for post-hoc debugging

## Reporting a Vulnerability

This is a personal open-source project with no bug bounty program.

Please report security vulnerabilities through [GitHub Private Vulnerability Reporting](https://github.com/chrisbloom7/to-wit/security). This keeps the details confidential until a fix is available. Confirmed vulnerabilities will be published as GitHub Security Advisories in the same location.

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce or a minimal proof of concept
- The version or commit hash you tested against

I aim to acknowledge reports within a few days and resolve confirmed issues before the next release.
