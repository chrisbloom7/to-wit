# To Wit

> _to wit: to make clearer or more particular something that you have already said_

To Wit is a searchable catalog of your [Claude Code](https://claude.ai/code) conversations, organized by topic.

Claude Code conversations are analyzed, filtered for substance, and stored in a local SQLite database. A CLI lets you search, list, and export conversations. A stop hook keeps the catalog up to date automatically after each session.

```shell
towit search hook
/Users/chrisbloom7
  ID                                    Title                        Keywords      Date
  ------------------------------------  ---------------------------  ------------  ----------
  350fa22f-10b7-48ff-ac9d-bd9f1081c23b  Debugging non-firing Stop …  stop-hook     2026-03-31

towit resume 350fa22f-10b7-48ff-ac9d-bd9f1081c23b
# => switch to `/Users/chrisbloom7` and call `claude --resume 350fa22f-10b7-48ff-ac9d-bd9f1081c23b`
```


## Requirements

- [Claude Code](https://www.anthropic.com/claude-code) (`brew install claude-code`)
- Python 3.11+ (`brew install python`)

## Installation

> Homebrew tap coming soon. For now, clone and run the install script.

```bash
git clone https://github.com/chrisbloom7/to-wit.git ~/path/to/to-wit
~/path/to/to-wit/install
```

By default, `install` links into `/usr/local/bin`. Pass a different directory as the first argument if needed:

```bash
~/path/to/to-wit/install ~/.local/bin
```

## Quick start

```bash
# Full setup: generate config, initialize database, install stop hook, and index existing conversations
towit setup --full

# Or step by step:
towit setup --config  # Generate ~/.towit/config.toml (optional but recommended)
towit setup           # Initialize the database
towit install-hook    # Add stop hook to Claude Code (auto-indexes future sessions)
towit backfill        # Index all existing conversations (~4 sec/session on Apple M4 Pro)
```

## Usage

```
towit <subcommand> [options]

Subcommands:
  setup [--full | --hook | --config]  Initialize database
                                  --full    also generates config, installs hook, and runs backfill
                                  --hook    also installs the stop hook
                                  --config  generate ~/.towit/config.toml (skips if already exists)
  search <terms...>             Search conversations by keyword (default), topic, summary, or title
    [--or]                        Match any term instead of all (default: AND)
    [--topic]                     Also search conversation topics
    [--all]                       Search keywords, topics, summaries, and titles
    [--summary]                   Also search conversation summaries
    [--title]                     Also search conversation titles
    [--format json|csv]           Output format (default: table)
    [--folder <path>]             Scope to a working directory
  list                          List all indexed conversations
    [--format json|csv]           Output format (default: table)
    [--folder <path>]             Scope to a working directory
    [--topic <name>]              Filter by topic
    [--keyword <name>]            Filter by keyword
  resume <session-id>           Resume a session in its original working directory
    [--force]                     Recreate the working directory if it no longer exists
  prune [--dry-run]             Remove entries whose transcripts no longer exist
  export <session-id>           Export a conversation
    [--format md|json]            Output format: md (default) or json
    [--summarize]                 AI summary instead of full transcript
  export --topic <name>         Export all conversations matching a topic
    [--format md|json]            Output format: md (default) or json
    [--summarize]                 Meta-summary of all matching conversations
  backfill                      Index all existing conversations
    [--dry-run]                   Preview without writing
    [--force]                     Re-index already indexed conversations
    [--folder <path>]             Scope to one project folder
  install-hook                  Add To Wit stop hook to Claude Code settings
  uninstall-hook                Remove To Wit stop hook from Claude Code settings
  teardown [--yes]              Remove hook and delete database
  implode [--yes]               Full uninstall: remove hook, database, and binary symlink
    [--install-dir <dir>]         Directory where towit was installed (default: /usr/local/bin)
  stats                         Show catalog statistics
  doctor                        Verify setup: config, database, and hook
  help                          Show this message
```

## How it works

**Indexing:** Each conversation is parsed from Claude Code's JSONL transcript files (`~/.claude/projects/`). Short or purely operational sessions are filtered out. Substantive conversations are analyzed by Claude, which extracts a title, summary, 15–30 specific keywords (identifiers, method names, error messages, domain terms, filenames, etc.), and broad topic tags. Results are stored in `~/.towit/catalog.db` (SQLite, WAL mode).

**What gets indexed:** Deep explorations, research, TIL moments, technical discoveries, documentation writing, theoretical discussions, estimation with depth. Quick one-shots, command execution sessions, and subagent traces are skipped.

**Auto-indexing:** The stop hook (`towit install-hook`) fires after each Claude Code response and indexes the conversation in the background.

## Configuration

To Wit is configured via `~/.towit/config.toml`. Generate a starter file with all settings commented out:

```bash
towit setup --config
```

### `[indexing]` settings

These settings control how To Wit calls the Claude API during indexing and directly affect API spend.

| Key | Default | Description |
|---|---|---|
| `model` | `"haiku"` | Model passed to `claude -p`. Use `"default"` to inherit your Claude Code default, or any alias (`"sonnet"`, `"opus"`) or full model ID (`"claude-sonnet-4-6"`). |
| `reindex_delta` | `2` | Exchanges (user+assistant pairs) that must occur before a resumed session is re-analyzed. The stop hook fires after every response; this prevents re-indexing on every turn. Set to `1` for original behavior. |
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

### Cost estimates

Each indexing call sends roughly **2,000–4,000 input tokens** depending on transcript length and content (code-heavy conversations tokenize more densely than prose) plus prompt overhead of ~200 tokens. Output is roughly **300 tokens** (title + summary + keywords + topics JSON). The estimates below use a mid-range of ~2,200 input / 300 output tokens.

The stop hook fires after every Claude response. With `reindex_delta = 2` (default), a 10-exchange conversation triggers ~5 indexing calls instead of 10.

**Estimated cost — 100 conversations, 10 exchanges each:**

| Model | `reindex_delta = 1` (1,000 calls) | `reindex_delta = 2` (~500 calls) |
|---|---|---|
| Haiku 4.5 | ~$2.96 | ~$1.48 |
| Sonnet 4.6 | ~$11.10 | ~$5.55 |
| Opus 4.6 | ~$55.50 | ~$27.75 |

Pricing based on Anthropic's published rates as of April 2026: Haiku 4.5 at $0.80/$4.00 per million input/output tokens; Sonnet 4.6 at $3.00/$15.00; Opus 4.6 at $15.00/$75.00. Actual costs will vary.

## Uninstalling

To do a full uninstall in one step — removes the stop hook, database, and binary symlink:

```bash
towit implode
```

Or to remove just the hook and database while leaving the binary in place:

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
