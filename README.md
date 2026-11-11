# To Wit

> _to wit: to make clearer or more particular something that you have already said_

To Wit is a searchable catalog of your [Claude Code](https://claude.ai/code) conversations, organized by topic. It keeps a local, full-text archive of your Claude Code conversations. The text of every substantive session is stored in a SQLite database with FTS5 search, so you can find what was said or decided long after Claude Code has deleted the transcript. Stored conversations are enriched with title, summary, keywords, and topics, which are searchable too. A CLI lets you search, show, list, and export conversations. Claude Code hooks keep the archive up to date automatically.

```shell
towit search hook
/Users/chrisbloom7
  ID                                    Title                        Keywords   Turn  Snippet                          Date
  ------------------------------------  ---------------------------  ---------  ----  -------------------------------  ----------
  350fa22f-10b7-48ff-ac9d-bd9f1081c23b  Debugging non-firing Stop …  stop-hook  14    …why the Stop [hook] never ran…  2026-03-31

towit show 350fa22f-10b7-48ff-ac9d-bd9f1081c23b --around 14 --context 2
# => turn 14 and two messages either side, straight from the archive

towit resume 350fa22f-10b7-48ff-ac9d-bd9f1081c23b
# => switch to `/Users/chrisbloom7` and call `claude --resume 350fa22f-10b7-48ff-ac9d-bd9f1081c23b`
```


## Requirements

- [Claude Code](https://www.anthropic.com/claude-code) (`brew install claude-code`)
- Python 3.11+ (`brew install python`), built with SQLite FTS5 (Homebrew's Python is; `towit doctor` checks)

## Installation

> Homebrew tap coming soon. For now, clone and run the install script.

```bash
git clone https://github.com/chrisbloom7/to-wit.git ~/path/to/to-wit
~/path/to/to-wit/install
```

By default, `install` links into `~/.local/bin` (creating it if needed) and tells you if that directory is not on your `PATH`. Pass a different directory as the first argument if needed (for example `/usr/local/bin`, which is root-owned on Apple Silicon Macs, so it needs `sudo`):

```bash
~/path/to/to-wit/install /some/other/dir
```

## Upgrading

`install` symlinks into your clone, so updating the code is a `git pull`; there is nothing to reinstall:

```bash
git -C ~/path/to/to-wit pull
```

Your database upgrades itself the first time any `towit` command runs, and your config and existing data are kept. Coming from 0.8.x or earlier, also run:

```bash
towit install-hook   # adds the SessionEnd and SessionStart hooks; keeps your Stop hook
towit backfill       # archives the transcripts still on disk (Claude Code eventually purges them)
towit doctor         # confirms hooks, FTS5, and the archive schema
```

New `[ingest]` and `[indexing]` settings use their defaults until you add them; see [Configuration](#configuration). If you originally installed into `/usr/local/bin`, the symlink keeps working, but `towit implode --install-dir /usr/local/bin` (or `./uninstall /usr/local/bin`) needs the directory spelled out now that the default is `~/.local/bin`.

## Quick start

```bash
# Full setup: generate config, initialize database, install hooks, and archive and index existing conversations
towit setup --full

# Or step by step:
towit setup --config  # Generate ~/.towit/config.toml (optional but recommended)
towit setup           # Initialize the database
towit install-hook    # Add the hooks to Claude Code (archives future sessions automatically)
towit backfill        # Archive and index existing conversations (LLM indexing takes ~4 sec/session on Apple M4 Pro; archiving alone is far faster)
```

## Usage

```
towit <subcommand> [options]

Subcommands:
  setup [--full | --hook | --config]  Initialize database
                                  --full    also generates config, installs hooks, and runs backfill
                                  --hook    also installs the Claude Code hooks
                                  --config  generate ~/.towit/config.toml (skips if already exists)
  search <terms...>             Search message text, keywords, titles, and summaries
    [--or]                        Match any term instead of all (default: AND, with an automatic OR retry)
    [--topic]                     Also search conversation topics
    [--all]                       Search topics too (and, with --only metadata, summaries and titles)
    [--summary]                   Also search conversation summaries
    [--title]                     Also search conversation titles
    [--only text|metadata]        Search only message text, or only metadata (the old scope)
    [--format json|csv]           Output format (default: table)
    [--folder <path>]             Scope to a working directory
    [--repo <path|name>]          Scope to a repo (its key, directory name, or `name.<branch>` worktrees)
  show <session-id>             Print the archived messages of a conversation
    [--around <seq>]              Only messages near this 0-based message number
    [--context <n>]               Messages either side of --around (default: 5)
    [--format text|json]          Output format (default: text)
  list                          List all indexed conversations
    [--format json|csv]           Output format (default: table)
    [--folder <path>]             Scope to a working directory
    [--topic <name>]              Filter by topic
    [--keyword <name>]            Filter by keyword
  resume <session-id>           Resume a session in its original working directory
    [--force]                     Recreate the working directory if it no longer exists
  prune                         Remove entries whose transcripts no longer exist
    [--dry-run]                   Show what would be removed without deleting
    [--archive]                   Also remove archived conversations (and their messages)
    [--yes]                       Skip the --archive confirmation
  forget <session-id>           Permanently delete a conversation from the archive
  forget --repo <path|name>     Permanently delete every conversation in a repo
  forget --folder <path>        Permanently delete every conversation in a working directory
    [--yes]                       Skip the confirmation prompt
  export <session-id>           Export a conversation
    [--format md|json]            Output format: md (default) or json
    [--summarize]                 AI summary instead of full transcript
  export --topic <name>         Export all conversations matching a topic
    [--format md|json]            Output format: md (default) or json
    [--summarize]                 Meta-summary of all matching conversations
  backfill                      Archive and index existing transcripts
    [--dry-run]                   Preview without writing
    [--force]                     Re-index already indexed conversations
    [--folder <path>]             Scope to one project folder
  install-hook                  Add the To Wit hooks (Stop, SessionEnd, SessionStart) to Claude Code settings
  uninstall-hook                Remove the To Wit hooks from Claude Code settings
  teardown [--yes]              Remove hooks and delete database (including the archive)
  implode [--yes]               Full uninstall: remove hooks, database (including the archive), and binary symlink
    [--install-dir <dir>]         Directory where towit was installed (default: ~/.local/bin)
  stats                         Show catalog statistics
  doctor                        Verify setup: config, database (FTS5, archive schema), and hooks
  help                          Show this message
```

## How it works

**Archiving.** Each conversation is parsed from Claude Code's JSONL transcript files (`~/.claude/projects/`). The text of every user and assistant message is stored in `~/.towit/catalog.db` (SQLite, WAL mode) and indexed with FTS5, so searching needs no API calls and takes milliseconds. Tool calls are kept as one-line stubs inside the assistant turn that made them (`[Bash] <description or command>`, `[Edit] <file path>`, each capped at 200 characters), and failed tool results as `[error] <first 300 characters>`. Tool results and file contents are not stored. A single message is capped at 50,000 characters, so a pasted log cannot bloat the archive. Sessions with fewer than two user messages are not archived, and subagent sessions are skipped unless you set `include_subagents`. Archiving is incremental and append-only: each run stores only the messages added since the last one.

**Redaction.** Before text is stored, secret-shaped strings (AWS keys, GitHub, Anthropic, OpenAI, Stripe, and Slack tokens, JWTs, private-key blocks, `Bearer` tokens, credentials in URLs, and long values assigned to `*_KEY`, `*_SECRET`, `*_TOKEN`, or `*_PASSWORD` names) are replaced with `[REDACTED:<kind>]`. The same redaction is applied to the transcript sent to Claude for analysis, and to what `towit export --summarize` and `export --topic --summarize` send (at send time, so stored summaries from older versions are covered too). It is best effort and pattern based, **not a guarantee**: treat the archive as sensitive. Stored rows are redacted once, at ingest, and never rewritten; export prompts are redacted at send time. Turning `ingest.redact` off or on later does not rewrite rows that are already archived (use `towit forget` to remove them), and a redacted value cannot be searched by its original text. Add your own patterns with `ingest.extra_patterns`.

**LLM metadata (optional).** After archiving, Claude analyzes substantive conversations and extracts a title, summary, 15-30 specific keywords (identifiers, method names, error messages, domain terms, filenames, etc.), and broad topic tags. Claude may decide a session is trivial (a quick one-shot or a command-execution session); the session is still archived and searchable by its text, it just has no title, summary, or keywords, and search results fall back to its first user message as the title. Set `[indexing] enabled = false` to archive only, with no API calls at all.

**Hooks.** `towit install-hook` registers one script, `towit_hook.py`, for three Claude Code hook events, and it does the real work in a detached background process so it never slows Claude Code down:

| Event | What To Wit does |
|---|---|
| `Stop` | Fires after each response (not on interrupts or API errors). Archives the new messages, then runs LLM indexing (subject to `reindex_delta`). |
| `SessionEnd` | Fires when a session ends (exit, `/clear`, resuming another session). Archives the final state of the transcript, then runs LLM indexing. |
| `SessionStart` (matcher `startup`) | Runs a catch-up scan: archives, with no LLM calls, every transcript modified since the last scan. This recovers sessions that ended without a hook (a crash, a closed terminal). |

Hooks are skipped when Claude Code runs with `--bare` and when `disableAllHooks` is true; `towit doctor` warns about the latter. `Stop` and `SessionEnd` run as separate background processes, so if both fire before the first finishes, both may call Claude for the same session. That costs a little extra API spend and nothing else. Run `towit backfill` to archive transcripts that existed before you installed the hooks.

## Searching and reading the archive

`towit search` looks in message text, keywords, titles, and summaries by default, and ranks conversations with a metadata match first and then by relevance (`bm25`) of the best-matching message. Each result shows the **Turn** (the 0-based message number) and a snippet with the matching words in `[brackets]`:

```shell
towit search recursion
/tmp/demo
  ID                                    Title                      Keywords  Turn  Snippet                     Date
  ------------------------------------  -------------------------  --------  ----  --------------------------  ----------
  aaaaaaaa-1111-2222-3333-444444444444  How does the stop hook r…            0     How does the stop hook [r…  2026-03-31

towit show aaaaaaaa-1111-2222-3333-444444444444 --around 1 --context 1
```

- Every argument is a term and terms are combined with AND (`--or` for OR). If an AND search finds nothing and there are two or more terms, it is retried with OR and `No results for all terms; showing results matching any term.` is printed to stderr (so `--format json` and `csv` output on stdout stays parseable). The retry does not apply with `--or` or `--only metadata`. An argument that contains a space is an exact phrase: `towit search "stop hook"`. Punctuation and FTS5 operators in your input are treated literally.
- `--only text` searches message text alone. `--only metadata` restores the pre-archive scope: keywords only, plus titles, summaries, and topics when you add `--title`, `--summary`, `--all`, or `--topic`. `--topic` adds topics to any scope.
- Tool calls are stored only as short stubs (at most 200 characters) and tool results are not stored, except failures as `[error]` lines of at most 300 characters, so the output of commands is not searchable. Ranking favors short matching messages: a brief passing mention can outrank the long message that is really about the term, so scan past the top few results.
- Text matches are capped at 50 conversations. Metadata matches are never capped.
- `--folder` matches a conversation's working directory exactly. `--repo` matches a repo by its key (the exact path) or by its final path component, e.g. `--repo to-wit`. The name also matches keys whose final component starts with `name.`, so `--repo studio-app` finds `studio-app.phase-2a-payments` (the worktree of a repo whose directory had already been deleted). It does not match `studio-app2`, `other-studio-app.x`, or a `studio-app.x` that is only a parent directory. `towit forget --repo` lists the matched repo keys (up to 10, then `+N more`) before it asks you to confirm (and before deleting, even with `--yes`), so check them when a name matches more than you expect.
- `--format json` and `--format csv` add `seq`, `snippet`, and `score` to each result (the conversation's id stays in `id`).

**Repo grouping.** A conversation's repo key is the git common directory of its working directory, so all the worktrees of a repo group under the main checkout. The key is resolved once, when the session is first archived, and kept on later ingests (a resumed session, a `towit backfill`), so deleting a worktree afterwards does not change it. If the working directory no longer exists (or is not a git checkout) at that first archive, the working directory itself becomes the key; for example `studio-app.phase-2a-payments` is its own stored key. Only the `--repo` match widens: `--repo studio-app` matches that key by its `studio-app.` prefix, so such sessions are found without having to name the worktree.

`towit show <session-id>` prints the stored messages (`--around <seq> --context <n>` narrows it to the messages near a search hit; `--format json` prints an array of `seq`, `role`, `ts`, and `text`). It works after Claude Code has deleted the transcript. The text is archive content (including tool output and web content), so `show` strips terminal control sequences before printing it. The table output of `search` and `list` (titles, keywords, snippets, working directories) is sanitized the same way and kept on one line per row; `--format json` escapes non-ASCII characters and `--format csv` is printed as stored.

`towit stats` prints conversation counts, then a block with the number of archived and metadata-only conversations, archived messages, and the database size.

## Retention and removing data

**`claude purge` and Claude Code's retention sweep do not delete the To Wit archive.** That is the point of the archive, but it also means data you deliberately deleted from Claude Code is still here. To remove it:

```bash
towit forget <session-id>            # one conversation
towit forget --repo my-repo          # every conversation in a repo
towit forget --folder /path/to/dir   # every conversation whose working directory is exactly this path
```

`forget` shows how many conversations it will delete and asks for confirmation unless you pass `--yes`. It removes the messages, search-index entries, topics, and keywords, and keeps only the session id in a tombstone so `backfill`, the hooks, and the catch-up scan never re-archive it from a transcript that is still on disk. `forget <session-id>` also forgets that session's subagent conversations (archived under their own ids), and says how many. The transcript under `~/.claude/projects/` is not touched. To really remove the text from disk, `forget` also zeroes freed pages (`secure_delete`), merges the FTS index, and runs `VACUUM` and a write-ahead-log truncate. `VACUUM` rewrites the whole database file, so a `forget` takes time proportional to the database size. If the physical cleanup could not finish (for example another towit process was busy), `forget` prints a warning on stderr but still exits 0; running `towit forget <session-id>` again on that already-forgotten id re-runs the cleanup. Exit codes: `0` success, `1` unknown id / nothing matched / you declined the prompt, `2` usage error (no selector, or more than one).

`towit prune` removes catalog entries whose transcripts are gone, but by default only those that were never archived (`archived = 0`); archived conversations are kept because their messages are the point. `towit prune --archive` also removes archived conversations with missing transcripts, including those in the purge report below (after a confirmation, or with `--yes`), and `--dry-run` previews. Archived rows are removed physically, the same way `forget` does it (FTS merge, `VACUUM`, WAL truncate), but without a tombstone, so a session whose transcript reappears can be archived again (metadata-only rows hold no message text and are deleted plainly, so a default `prune` stays fast). `prune` also prints a **Likely removed by claude purge** section that lists archived conversations whose whole project folder no longer exists. It is only a report, because a manually deleted folder looks identical; for subagent sessions the "project folder" is the session's `subagents` directory, so a purged session directory shows up there too.

## Configuration

To Wit is configured via `~/.towit/config.toml`. Generate a starter file with all settings commented out:

```bash
towit setup --config
```

### `[database]` settings

| Key | Default | Description |
|---|---|---|
| `path` | `"~/.towit/catalog.db"` | Database file path. |

### `[indexing]` settings

These settings control how To Wit calls the Claude API during indexing and directly affect API spend.

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Set to `false` to archive only: the hooks and `backfill` store message text but make no Claude calls (no titles, summaries, keywords, or topics for new conversations). |
| `model` | `"haiku"` | Model passed to `claude -p`. Use `"default"` to inherit your Claude Code default, or any alias (`"sonnet"`, `"opus"`) or full model ID (`"claude-sonnet-4-6"`). |
| `reindex_delta` | `2` | Exchanges (user+assistant pairs) that must occur before a resumed session is re-analyzed. The `Stop` hook fires after every response; this prevents re-indexing on every turn. Set to `1` for original behavior. |
| `min_topics` | `1` | Minimum topic tags Claude should assign per conversation. |
| `max_topics` | `5` | Maximum topic tags Claude should assign per conversation. |
| `min_keywords` | `15` | Minimum keywords Claude should extract per conversation. |
| `max_keywords` | `30` | Maximum keywords Claude should extract per conversation. |
| `min_summary_sentences` | `3` | Minimum sentences in the generated summary. |
| `max_summary_sentences` | `6` | Maximum sentences in the generated summary. |
| `transcript_max_chars` | `8000` | Character cap on the transcript excerpt sent to Claude. When the transcript exceeds this limit, the middle is dropped and replaced with an omission marker; the budget is split 30% from the start and 70% from the end. |

**Example:**

```toml
[indexing]
model = "haiku"
reindex_delta = 2
min_topics = 1
max_topics = 5
min_keywords = 10
max_keywords = 20
min_summary_sentences = 2
max_summary_sentences = 4
transcript_max_chars = 8000
```

### `[ingest]` settings

These settings control what is archived. Searching and archiving make no API calls.

| Key | Default | Description |
|---|---|---|
| `redact` | `true` | Redact secret-shaped strings before archiving and before sending the indexing transcript to Claude. Best effort. Stored rows are redacted at ingest and never rewritten; export prompts are redacted at send time (see above). |
| `extra_patterns` | `[]` | Extra regular expressions to redact, in addition to the built-in set. Invalid or empty-matching patterns are ignored with a warning. |
| `include_subagents` | `false` | Also archive subagent sessions. Applies to `backfill` and the `SessionStart` catch-up scan; the `Stop` and `SessionEnd` hooks never archive them. Subagent sessions are archived only, never analyzed by Claude. |
| `folders` | `[]` | Only archive sessions from matching project folders. Shell-style globs matched against the folder under `~/.claude/projects` that holds the transcript, for example `["*my-repo*"]`. Empty means all folders. |

### Cost estimates

**Archiving costs no API tokens.** Only LLM indexing does. Setting `[indexing] enabled = false` removes API spend entirely.

Each LLM indexing call sends roughly **2,000-4,000 input tokens** depending on transcript length and content (code-heavy conversations tokenize more densely than prose) plus prompt overhead of ~200 tokens. Output is roughly **300 tokens** (title + summary + keywords + topics JSON). The estimates below use a mid-range of ~2,200 input / 300 output tokens.

The `Stop` hook fires after every Claude response. With `reindex_delta = 2` (default), a 10-exchange conversation triggers ~5 indexing calls instead of 10. `SessionEnd` can add a call (see Hooks above) when the two hooks overlap.

**Estimated cost — 100 conversations, 10 exchanges each:**

| Model | `reindex_delta = 1` (1,000 calls) | `reindex_delta = 2` (~500 calls) |
|---|---|---|
| Haiku 4.5 | ~$2.96 | ~$1.48 |
| Sonnet 4.6 | ~$11.10 | ~$5.55 |
| Opus 4.6 | ~$55.50 | ~$27.75 |

Pricing based on Anthropic's published rates as of April 2026: Haiku 4.5 at $0.80/$4.00 per million input/output tokens; Sonnet 4.6 at $3.00/$15.00; Opus 4.6 at $15.00/$75.00. Actual costs will vary.

### Disk usage

The archive grows with how much you talk to Claude. Measured on one heavy-use project (24 top-level sessions, 14,003 messages), the database was 16.4 MB, about **0.7 MB per top-level session** including the search index. Archiving the same project with `include_subagents = true` added 568 subagent sessions and roughly 11 MB (about 20 KB each), so subagents are off by default. `towit stats` shows the current size. Backfilling those 24 sessions took about 3 seconds.

## Uninstalling

**`teardown` and `implode` delete the database, and with it the archive.** Once Claude Code has purged the original transcripts, the archive may be the only copy of those conversations. Save what you want to keep first: `towit show <session-id> --format json > session.json` prints the archived text even after the transcript is gone, whereas `towit export` needs the original transcript to still exist.

To do a full uninstall in one step — removes the hooks, database (including the archive), and binary symlink:

```bash
towit implode
```

Or to remove just the hooks and database while leaving the binary in place:

```bash
towit teardown
```

Then remove the binary manually (or `brew uninstall towit` when available).

## Development

```bash
git clone https://github.com/chrisbloom7/to-wit.git
cd to-wit

# Run tests (requires bats-core: brew install bats-core)
./run-tests

# Run a specific test file
./run-tests tests/bin/towit.bats
./run-tests tests/helpers/towit_db_test.py
./run-tests --filter "search"
```

## License

MIT — see [LICENSE](LICENSE).
