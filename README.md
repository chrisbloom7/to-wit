# To Wit

> _to wit: to make clearer or more particular something that you have already said_

To Wit keeps a private, searchable archive of your sessions on your machine, so you can answer "where did I decide that three weeks ago?" even when it was in another worktree, and even after Claude Code has deleted the transcript. You get full-text search of every substantive session, plus LLM-generated metadata (title, summary, keywords, and topics) for each, kept current by [Claude Code](https://www.anthropic.com/claude-code) hooks.

**Terms.** A *session* is one Claude Code conversation. The *archive* is the stored message text of your sessions. *Metadata* is the LLM-generated title, summary, keywords, and topics.

![A terminal recording: towit search finds a past session by one word, towit show reads the decision in context, and towit resume picks the conversation back up](docs/demo/demo.gif)

## Table of contents

- [Why](#why)
- [Privacy and cost](#privacy-and-cost)
- [Requirements](#requirements)
- [Get started](#get-started)
- [Core commands](#core-commands)
- [Searching and reading the archive](#searching-and-reading-the-archive)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Claude Code skill](#claude-code-skill)
- [Retention and removing data](#retention-and-removing-data)
- [Upgrading](#upgrading)
- [Configuration](#configuration)
- [Uninstalling](#uninstalling)
- [Development](#development)
- [License](#license)

## Why

I was constantly losing track of which conversations happened in which project, and which insight happened in which conversation. To Wit keeps what was said and makes it searchable:

- **It finds the conversation wherever it happened.** One archive covers every project; `--repo` narrows a search to one repository and all of its worktrees (see [Searching and reading the archive](#searching-and-reading-the-archive)).
- **It outlives Claude Code's retention.** The archive is yours; `claude purge` and the retention sweep do not touch it (see [Retention and removing data](#retention-and-removing-data)).
- **It stays local and private.** No service and no account; see [Privacy and cost](#privacy-and-cost).
- **It keeps itself current.** Hooks archive each session as it ends, so there is nothing to remember to run.
- **Claude can search it too.** The optional [Claude Code skill](#claude-code-skill) lets Claude look up earlier sessions for you.

## Privacy and cost

- **Where it lives.** By default everything is in one SQLite file, `~/.towit/catalog.db`; the `~/.towit` directory is created owner-only (`0700`) and the file `0600`, and `towit doctor` checks both. The original transcripts are never touched. The archive holds the full text of your sessions, so treat it as sensitive.
- **What leaves your machine.** Searching, showing, listing and archiving make no network calls. Calls out go only through the `claude` CLI (`claude -p`): LLM indexing and `towit export --summarize` send (redacted) session text to Claude through the `claude` CLI, with an allowlisted environment. Installing the optional skill also fetches the plugin from GitHub.
- **Redaction is best effort.** On by default, secret-shaped strings are replaced with `[REDACTED:<kind>]` before storage and before anything is sent to Claude. It is pattern based, not a guarantee (see [How it works](#how-it-works)).
- **Zero API cost is one setting away.** `[indexing] enabled = false` archives and searches message text with no Claude calls at all (you lose metadata for new sessions).
- **What indexing costs.** About $1.48 per 100 ten-exchange sessions with the default model and settings (Haiku, `reindex_delta = 2`); see [Cost estimates](#cost-estimates) for other models. [SECURITY.md](SECURITY.md) has the full threat model.

## Requirements

- **macOS or Linux.** To Wit is developed on macOS. CI runs the test suite and an install smoke test (`install`, `setup --hook`, `doctor`, `stats`) on both macOS and Ubuntu, but that CI does not cover the Homebrew formula, and other platforms (including Windows) are untested.
- **Python 3.11+** built with FTS5, which is SQLite's full-text search (`brew install python`; Homebrew's Python has it, and `towit doctor` checks).
- **[Claude Code](https://www.anthropic.com/claude-code)** (`brew install claude-code`), which is where the conversations come from: its hooks trigger archiving and its transcripts are what gets archived. The `claude` CLI is also what LLM indexing and `export --summarize` call (`claude -p`), and what `towit resume` and the skill use. Without it you can still search, show and list what is already archived, and archive in text-only mode with `[indexing] enabled = false`, but you get no metadata.

## Get started

The shortest path is three commands, ending in your first search:

```bash
brew install chrisbloom7/tap/towit
towit setup --full
towit search <a word you remember>
```

`towit setup --full` generates `~/.towit/config.toml`, creates the database, installs the Claude Code hooks, and archives and indexes your existing sessions. **It processes all of your past sessions, and unless `[indexing] enabled = false` is set it calls `claude -p` for every session that is not yet indexed, which costs API tokens** (see [Cost estimates](#cost-estimates)). To archive with no API calls, run `towit setup --config` first, set `enabled = false` under `[indexing]` in the file it generates, then run `towit setup --full`. Archiving itself is free and fast.

Installing by the full formula name trusts only this formula. Homebrew requires explicit trust for third-party taps, so if you run `brew tap chrisbloom7/tap` first, trust the formula with `brew trust --formula chrisbloom7/tap/towit` before installing. The formula brings a Homebrew Python (3.11+ with SQLite FTS5). Claude Code is optional for searching what is already archived (see [Requirements](#requirements) for what needs it).

### From source

```bash
git clone https://github.com/chrisbloom7/to-wit.git ~/path/to/to-wit
~/path/to/to-wit/install
towit setup --full
```

By default, `install` links into `~/.local/bin` (creating it if needed) and tells you if that directory is not on your `PATH`. Pass a different directory as the first argument if needed (for example `/usr/local/bin`, which is root-owned on Apple Silicon Macs, so it needs `sudo`):

```bash
~/path/to/to-wit/install /some/other/dir
```

### Step by step

Instead of `--full`, run the pieces yourself:

```bash
towit setup --config  # Generate ~/.towit/config.toml (optional but recommended)
towit setup           # Initialize the database
towit install-hook    # Add the hooks to Claude Code (archives future sessions automatically)
towit backfill        # Archive and index existing sessions (LLM indexing takes ~4 sec/session on Apple M4 Pro; archiving alone is far faster)
```

Skip `backfill` if you only want sessions from now on.

## Core commands

| Command | What it does |
|---|---|
| `towit search <terms...>` | Find sessions by words in their messages, keywords, titles, and summaries |
| `towit show <session-id>` | Print a session's archived messages, or just those around a search hit |
| `towit list` | Browse sessions, filtered by folder, topic, or keyword |
| `towit resume <session-id>` | Resume a session in its original working directory |
| `towit export <session-id>` | Export a session as Markdown or JSON, or as an AI summary (needs the original transcript) |
| `towit doctor` | Check the config, database, hooks, and skill |

New here? Run `towit setup --full` (see [Get started](#get-started)). Use `towit setup --hook` instead to install only the hooks, without backfilling (and so without paying to index) your old sessions. `--skill` is separate and opt-in (see [Claude Code skill](#claude-code-skill)). Every subcommand and flag is listed under [Usage](#usage).

## Searching and reading the archive

`towit search` finds sessions by the words in their messages (and by their keywords, titles, and summaries). Each result shows its best-matching message: the **Msg** (the 0-based message number, which is what `towit show --around` takes) and a snippet with the matching words in `[brackets]`:

```shell
towit search recursion
/tmp/demo
  ID                                    Title                      Msg  Snippet                     Date
  ------------------------------------  -------------------------  ---  --------------------------  ----------
  aaaaaaaa-1111-2222-3333-444444444444  How does the stop hook r…  0    How does the stop hook [r…  2026-03-31

towit show aaaaaaaa-1111-2222-3333-444444444444 --around 1 --context 1
```

In `towit search` and `towit list` text tables, **Keywords** appears when at least one result has a keyword to display and there is room for the column.

### Finding a prompt in a long session

`towit search` ranks whole conversations and shows one representative message, which is often an assistant reply or a `[Bash]` stub rather than the prompt you remember. Restrict the match to your own messages, then narrow the session down:

```shell
towit search --role user "migration plan"      # finds the session: ID and Msg of your own prompt
towit show <id> --role user --match migration  # every prompt of yours in that session that mentions it
towit show <id> --around 812 --context 3       # read it in context
```

Msg numbers are used throughout (never line numbers), and `towit show <id> --role user` on its own is an outline of the session's prompts.

### More examples

```shell
# Search one repo (its worktrees too) and print a compact list: date, id, title
towit search "stop hook" --repo to-wit --format json | jq -r '.[] | "\(.date)  \(.id)  \(.title)"'

# Match any of several terms instead of all of them
towit search redis timeout connection --or

# An exact phrase, in your own prompts only (skips assistant replies and tool stubs)
towit search "retry budget" --role user

# Browse by topic or keyword instead of searching
towit list --topic hooks
towit list --keyword stop-hook --format json | jq -r '.[].id'

# Every prompt you wrote in one session, with the Msg number to pass to `show --around`
towit show <id> --role user --format json | jq -r '.[] | "\(.seq)\t\(.text | split("\n")[0])"'

# Titles, summaries and keywords only: quick, and ignores message text
towit search --only metadata --title stemming
```

### Reference: search and show options

`towit search` looks in message text, keywords, titles, and summaries by default, and ranks conversations with a metadata match first, then those covering more of your terms, then by relevance and how many messages match, then the newest..

- Every argument is a term and terms are combined with AND (`--or` for OR). A conversation matches when every term appears somewhere in its messages, even in different messages. With more than 8 distinct terms (ignoring case duplicates and terms with no letter or digit), all terms must appear in one message. If an AND search finds nothing and there are two or more terms, it is retried with OR and `No results for all terms; showing results matching any term.` is printed to stderr (so `--format json` and `csv` output on stdout stays parseable). The retry does not apply with `--or` or `--only metadata`. An argument that contains a space is an exact phrase: `towit search "stop hook"`. Punctuation and FTS5 operators in your input are treated literally.
- Terms match message text as English-stemmed words, so `test` also finds "tests" and "tested", and `remove` finds "removed" and "removing". A `_`, `-` or `.` inside a word keeps it one token (`towit_db.py` and `my-var` match as written, not as their parts), and quoting a phrase still applies the stemmer to each word. Stemming can over-match (`university` and `universal` both reduce to `univers`) and it is English only. Keyword, topic, title, and summary matching is a case-insensitive substring match and is not stemmed. `towit show --match` is likewise a literal substring filter.
- `--only text` searches message text alone. `--only metadata` restores the pre-archive scope: keywords only, plus titles, summaries, and topics when you add `--title`, `--summary`, `--all`, or `--topic`. `--topic` adds topics to any scope.
- Tool calls are stored only as short stubs (at most 200 characters) and tool results are not stored, except failures as `[error]` lines of at most 300 characters, so the output of commands is not searchable. Within a message, relevance favors short messages, so a brief mention can outrank a long message about the term; conversations with many matching messages are boosted; scan past the top few results.
- `--role user` (or `assistant`) matches text only in messages of that role. Ranking, coverage, relevance, the Msg and the snippet then come only from those messages, so `--role user` skips assistant replies and the `[Bash]`-style tool stubs inside them, and a hit's Msg is your own prompt. Keyword, title, summary, and topic matches are not affected and still rank first (a conversation that matches only by metadata shows an empty Msg and snippet). AND means every term appears in that role's messages, and the OR retry keeps the role. `--role` with `--only metadata` is an error, because it would do nothing.
- Text matches are capped at 50 conversations. Metadata matches are never capped.
- `--folder` matches a conversation's working directory exactly. `--repo` matches a repo by its key (the exact path) or by its final path component, e.g. `--repo to-wit`. The name also matches keys whose final component starts with `name.`, so `--repo studio-app` finds `studio-app.phase-2a-payments` (the worktree of a repo whose directory had already been deleted). It does not match `studio-app2`, `other-studio-app.x`, or a `studio-app.x` that is only a parent directory. `towit forget --repo` lists the matched repo keys (up to 10, then `+N more`) before it asks you to confirm (and before deleting, even with `--yes`), so check them when a name matches more than you expect.
- `--format json` and `--format csv` add `seq` (the message number), `snippet`, and `score` to each result (the conversation's id stays in `id`).

**Repo grouping.** A conversation's repo key is the git common directory of its working directory, so all the worktrees of a repo group under the main checkout. The key is resolved once, when the session is first archived, and kept on later ingests (a resumed session, a `towit backfill`), so deleting a worktree afterwards does not change it. If the working directory no longer exists (or is not a git checkout) at that first archive, the working directory itself becomes the key; for example `studio-app.phase-2a-payments` is its own stored key. Only the `--repo` match widens: `--repo studio-app` matches that key by its `studio-app.` prefix, so such sessions are found without having to name the worktree.

`towit show <session-id>` prints the stored messages (`--around <msg> --context <n>` narrows it to the messages near a search hit, where `<msg>` is the Msg column of `towit search`; `--format json` prints an array of `seq`, `role`, `ts`, and `text`). `--role user|assistant` keeps only messages of that role (on its own, `towit show <id> --role user` is an outline of your prompts with their Msg numbers), and `--match TERM` keeps only messages containing the term as a literal substring, ignoring case and diacritics (so `--match migrat` finds "migration"; unlike `search`, which matches whole words). Repeat it (`--match a --match b`) to require every term in the same message; `%` and `_` are literal. With `--around`, the window is chosen first by message number and `--role`/`--match` then filter it, and the `>> ` marker appears only if that message itself passes. Msg numbers stay the original ones, in text and `--format json` alike. When nothing matches, `show` prints `No messages match the given filters.` to stderr and exits 1. Two quirks: under `--role user`, `[error]` rows (failed tool results are stored as user messages) can still appear, and under `--role assistant`, tool stubs stay because they sit inside assistant messages. It works after Claude Code has deleted the transcript. The text is archive content (including tool output and web content), so `show` strips terminal control sequences before printing it. The table output of `search` and `list` (titles, keywords, snippets, working directories) is sanitized the same way and kept on one line per row; `--format json` escapes non-ASCII characters and `--format csv` is printed as stored, so a cell can start with `=`, `+`, `-` or `@` (a spreadsheet runs it as a formula) or carry terminal escapes; review a CSV before opening it in a spreadsheet or printing it to a terminal. With no results `--format csv` prints nothing on stdout (no header row), while `--format json` prints `[]`.

### Stats and version

`towit stats` prints conversation counts, then a block with the number of archived and metadata-only conversations, archived messages, and the database size.

`towit version` (also `--version` and `-v`) prints the installed version, for example `towit 0.10.0`; `towit doctor` reports it as its first line. The version comes from the `libexec/towit/VERSION` file that ships with the install, and reads `towit unknown` if that file is missing.

## Usage

The full command reference, as printed by `towit help`:

```
towit <subcommand> [options]

Subcommands:
  setup [--full | --hook | --skill | --config]  Initialize database
                                  --full    also generates config, installs hooks, and runs backfill (not the skill: add --skill)
                                  --hook    also installs the Claude Code hooks
                                  --skill   also installs the Claude Code skill plugin, pinned to
                                            this version (rerun after an upgrade to repin; not in --full)
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
    [--role user|assistant]       Match message text only in messages of this role (metadata matches are unaffected)
    [--limit N]                   Cap text-only results at a positive integer (default: 50)
  show <session-id>             Print the archived messages of a conversation
    [--around <msg>]              Only messages near this message number (0-based; the Msg column in `towit search` results)
    [--context <n>]               Messages either side of --around (default: 5); the window is counted by message number before --role applies
    [--role user|assistant]       Only messages of this role (alone, an outline of your prompts with their Msg numbers)
    [--match <term>]...           Only messages containing the term (literal, case-insensitive substring, unlike `search`, which stems words); repeat to require all terms in one message
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
  implode [--yes]               Full uninstall: remove hooks, skill plugin, database (including the archive), and binary symlink
    [--install-dir <dir>]         Directory where towit was installed (default: ~/.local/bin)
  stats                         Show catalog statistics
  doctor                        Verify setup: config, database (FTS5, archive schema), hooks, and the Claude Code skill
  version | --version | -v      Print the installed version
  help                          Show this message
```

### Shell completion

Bash and Zsh can complete commands, options, and fixed values such as
`--format`, `--role`, and `--only`. Point your shell startup file at the
`completions/` directory in your To Wit source checkout.

For Bash, add this to `~/.bashrc` and open a new shell.

```bash
source "/path/to/to-wit/completions/towit.bash"
```

For Zsh, add the directory to `fpath` in `~/.zshrc` before initializing
completion. If your configuration already runs `compinit`, put the
`fpath` line before that call.

```zsh
fpath=("/path/to/to-wit/completions" $fpath)
autoload -Uz compinit
compinit
```

## How it works

**Archiving.** Each session is parsed from Claude Code's JSONL transcript files (`~/.claude/projects/`). The text of every user and assistant message is stored in `~/.towit/catalog.db` (SQLite, WAL mode) and indexed with FTS5, so searching needs no API calls and takes milliseconds. Tool calls are kept as one-line stubs inside the assistant turn that made them (`[Bash] <description or command>`, `[Edit] <file path>`, each capped at 200 characters), and failed tool results as `[error] <first 300 characters>`. Tool results and file contents are not stored. A single message is capped at 50,000 characters, so a pasted log cannot bloat the archive. Sessions with fewer than two user messages are not archived, and subagent sessions are skipped unless you set `include_subagents`. Archiving is incremental and append-only: each run stores only the messages added since the last one.

**Redaction.** Before text is stored, secret-shaped strings (AWS keys, GitHub, Anthropic, OpenAI, Stripe, and Slack tokens, JWTs, private-key blocks, `Bearer` tokens, credentials in URLs, and long values assigned to `*_KEY`, `*_SECRET`, `*_TOKEN`, or `*_PASSWORD` names) are replaced with `[REDACTED:<kind>]`. The same redaction is applied to the transcript sent to Claude for analysis, and, at send time, to what `towit export --summarize` and `export --topic --summarize` send (so stored summaries from older versions are covered too). It is best effort and pattern based, **not a guarantee**: treat the archive as sensitive. Stored rows are redacted once, at ingest, and never rewritten, so turning `ingest.redact` off or on later does not change rows that are already archived (use `towit forget` to remove them), and a redacted value cannot be searched by its original text. Add your own patterns with `ingest.extra_patterns`.

**LLM metadata (optional).** After archiving, Claude analyzes substantive sessions and extracts a title, summary, 15-30 specific keywords (identifiers, method names, error messages, domain terms, filenames, etc.), and broad topic tags. Claude may decide a session is trivial (a quick one-shot or a command-execution session); the session is still archived and searchable by its text, it just has no title, summary, or keywords, and search results fall back to its first user message as the title. Set `[indexing] enabled = false` to archive only, with no API calls at all.

**Hooks.** `towit install-hook` registers one script, `towit_hook.py`, for three Claude Code hook events, and it does the real work in a detached background process so it never slows Claude Code down:

| Event | What To Wit does |
|---|---|
| `Stop` | Fires after each response (not on interrupts or API errors). Archives the new messages, then runs LLM indexing (subject to `reindex_delta`). |
| `SessionEnd` | Fires when a session ends (exit, `/clear`, resuming another session). Archives the final state of the transcript, then runs LLM indexing. |
| `SessionStart` (matcher `startup`) | Runs a catch-up scan: archives, with no LLM calls, every transcript modified since the last scan. This recovers sessions that ended without a hook (a crash, a closed terminal). |

Hooks are skipped when Claude Code runs with `--bare` and when `disableAllHooks` is true; `towit doctor` warns about the latter. `Stop` and `SessionEnd` run as separate background processes, so if both fire before the first finishes, both may call Claude for the same session. That costs a little extra API spend and nothing else. Run `towit backfill` to archive transcripts that existed before you installed the hooks.

## Claude Code skill

The repo is also a Claude Code plugin marketplace with one plugin, `towit`, whose skill teaches Claude how to use the archive: search with `towit search`, read around a hit with `towit show --around`, fall back to `towit show --role user --match` when a search misses, and hand a session back to you with `towit resume`. Ask Claude something like "find the session where we fixed the Redis timeout" and it loads the skill on its own (see [Example prompts](#example-prompts)).

```bash
towit setup --skill     # installs towit@to-wit, pinned to this version of towit
```

or, without the pin (it then follows `main`, so it can describe flags newer than your towit):

```bash
claude plugin marketplace add chrisbloom7/to-wit
claude plugin install towit@to-wit
```

`towit setup --skill` pins the plugin to the tag matching your installed version, so the skill never mentions a flag your towit lacks. After `brew upgrade towit` or `git pull`, run it again to repin; `towit doctor` warns when the pin and the CLI disagree. Replacing a pin removes and re-adds the `to-wit` marketplace (Claude Code uninstalls a marketplace's plugins when it is removed), and the command then reinstalls the plugin. `towit setup --full` does not install the plugin, and `towit implode` removes it.

The skill is read-only guidance: it treats archived text as untrusted data and never runs `forget`, `prune` or `implode` unless you ask for that exact action. `towit setup --skill` runs `claude plugin ...` with the same scoped environment as indexing (see SECURITY.md) plus your ssh agent socket, proxy settings and CA bundle locations, which the marketplace's `git` clone may need. If the clone fails on your network, run the two `claude plugin` commands above by hand.

### Example prompts

Ask in plain language; Claude picks the commands. What you ask, and roughly what happens:

| You ask | Claude typically runs |
|---|---|
| "Find the session where we fixed the Redis timeout" | `towit search redis timeout --format json`, then `towit show <id> --around <msg>` to read the hit in context |
| "What did I originally ask for when we built the export command?" | `towit search --role user export`, then `towit show <id> --role user --match export` for your own prompts |
| "Where did we talk about pricing with Dana?" | `towit search pricing dana --format json`, then `towit show <id> --match pricing --match dana` on each candidate, because a search hit may have the two words in different messages |
| "Does session `<id>` include a decision about switching databases?" | `towit show <id> --match database --match switch` for the messages with both words, then `towit show <id> --around <msg>` to read the surrounding turns. Claude says which messages it read and which it did not |
| "Which of my sessions in this repo touched the release process?" | `towit search release --repo <repo> --format json` |
| "Show me everything filed under the hooks topic" | `towit list --topic hooks --format json` |
| "Resume the session where we debugged the Stop hook" | finds the id with `towit search`, then gives you `towit resume <id>` to run; it does not resume a session for you |

Claude reports the session id, date, title and the message numbers it read so you can check them, and says so when nothing matched instead of answering from memory.

## Retention and removing data

**`claude purge` and Claude Code's retention sweep do not delete the To Wit archive.** That is the point of the archive, but it also means data you deliberately deleted from Claude Code is still here. To remove it:

```bash
towit forget <session-id>            # one conversation
towit forget --repo my-repo          # every conversation in a repo
towit forget --folder /path/to/dir   # every conversation whose working directory is exactly this path
```

`forget` shows how many conversations it will delete and asks for confirmation unless you pass `--yes`. It removes the messages, search-index entries, topics, and keywords, and keeps only the session id in a tombstone so `backfill`, the hooks, and the catch-up scan never re-archive it from a transcript that is still on disk. `forget <session-id>` also forgets that session's subagent conversations (archived under their own ids), and says how many. The transcript under `~/.claude/projects/` is not touched. To really remove the text from disk, `forget` also zeroes freed pages (`secure_delete`), merges the FTS index, and runs `VACUUM` and a write-ahead-log truncate. `VACUUM` rewrites the whole database file, so a `forget` takes time proportional to the database size. If the physical cleanup could not finish (for example another towit process was busy), `forget` prints a warning on stderr but still exits 0; running `towit forget <session-id>` again on that already-forgotten id re-runs the cleanup. Exit codes: `0` success, `1` unknown id / nothing matched / you declined the prompt, `2` usage error (no selector, or more than one).

`towit prune` removes catalog entries whose transcripts are gone, but by default only those that were never archived (`archived = 0`); archived conversations are kept because their messages are the point. `towit prune --archive` also removes archived conversations with missing transcripts, including those in the purge report below (after a confirmation, or with `--yes`), and `--dry-run` previews. Archived rows are removed physically, the same way `forget` does it (FTS merge, `VACUUM`, WAL truncate), but without a tombstone, so a session whose transcript reappears can be archived again (metadata-only rows hold no message text and are deleted plainly, so a default `prune` stays fast). `prune` also prints a **Likely removed by claude purge** section that lists archived conversations whose whole project folder no longer exists. It is only a report, because a manually deleted folder looks identical; for subagent sessions the "project folder" is the session's `subagents` directory, so a purged session directory shows up there too.

## Upgrading

**Homebrew:** `brew upgrade towit`. The hooks point at Homebrew's version-independent path, so they keep working across upgrades. Your database upgrades itself the first time any `towit` command runs.

**From source:** `install` symlinks into your clone, so updating the code is a `git pull`; there is nothing to reinstall:

```bash
git -C ~/path/to/to-wit pull
```

Your database upgrades itself the first time any `towit` command runs, and your config and existing data are kept. If you installed the Claude Code skill (`towit setup --skill`), run it again after upgrading to repin the plugin to the new version; `towit doctor` tells you when it is out of date. If you move your clone, re-run `towit install-hook`: it repairs hooks that point at the old location. New `[ingest]` and `[indexing]` settings use their defaults until you add them; see [Configuration](#configuration).

<details>
<summary>Coming from an older version or a source install</summary>

**From 0.8.x or earlier (Homebrew or source):** also run:

```bash
towit install-hook   # adds the SessionEnd and SessionStart hooks; keeps your Stop hook
towit backfill       # archives the transcripts still on disk (Claude Code eventually purges them)
towit doctor         # confirms hooks, FTS5, and the archive schema
```

**Switching from a source install to Homebrew:** your data and config are kept. Remove the old symlink (`rm ~/.local/bin/towit`; do not run `./uninstall`, which also deletes the archive), then run `towit install-hook` to point the hooks at the Homebrew install.

If you originally installed into `/usr/local/bin`, the symlink keeps working, but `towit implode --install-dir /usr/local/bin` (or `./uninstall /usr/local/bin`) needs the directory spelled out now that the default is `~/.local/bin`.

</details>

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

With a Homebrew install, `towit implode` removes the hooks and database, then reminds you to finish with `brew uninstall towit`.

Or to remove just the hooks and database while leaving the binary in place:

```bash
towit teardown
```

Then remove the binary manually (or `brew uninstall towit` when available).

## Development

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).

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

GPL-3.0-only — see [LICENSE](LICENSE).
