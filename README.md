# claudecat

A searchable catalog of your [Claude Code](https://claude.ai/code) conversations, organized by topic.

Claude Code conversations are analyzed, filtered for substance, and stored in a local SQLite database. A CLI lets you search, list, and export conversations. A stop hook keeps the catalog up to date automatically after each session.

## Requirements

- [Claude Code](https://www.anthropic.com/claude-code) (`brew install claude-code`)
- Python 3 (`brew install python`)

## Installation

> Homebrew tap coming soon. For now, clone and link manually.

```bash
git clone https://github.com/chrisbloom7/claudecat.git ~/path/to/claudecat
ln -sf ~/path/to/claudecat/bin/claudecat /usr/local/bin/claudecat
```

## Quick start

```bash
# Full setup: initialize database, install stop hook, and index existing conversations
claudecat setup --full

# Or step by step:
claudecat setup          # Initialize the database
claudecat install-hook   # Add stop hook to Claude Code (auto-indexes future sessions)
claudecat backfill       # Index all existing conversations (~30–60 min first run)
```

## Usage

```
claudecat <subcommand> [options]

Subcommands:
  setup [--full | --hook]       Initialize database
                                  --full  also installs hook and runs backfill
                                  --hook  also installs hook
  search <terms...>             Search conversations by topic or summary
    [--or]                        Match any term instead of all (default: AND)
    [--csv]                       Output as CSV
    [--folder <path>]             Scope to a working directory
  list                          List all indexed conversations
    [--csv]                       Output as CSV
    [--folder <path>]             Scope to a working directory
    [--topic <name>]              Filter by topic
  export <session-id>           Export a conversation
    [--format md|json]            Output format (default: md)
    [--summarize]                 AI summary instead of full transcript
  export --topic <name>         Export all conversations matching a topic
    [--summarize]                 Meta-summary of all matching conversations
  backfill                      Index all existing conversations
    [--dry-run]                   Preview without writing
    [--force]                     Re-index already indexed conversations
    [--folder <path>]             Scope to one project folder
  install-hook                  Add claudecat stop hook to Claude Code settings
  uninstall-hook                Remove claudecat stop hook from Claude Code settings
  teardown [--yes]              Remove hook and delete database
  stats                         Show catalog statistics
  help                          Show this message
```

## How it works

**Indexing:** Each conversation is parsed from Claude Code's JSONL transcript files (`~/.claude/projects/`). Short or purely operational sessions are filtered out. Substantive conversations are analyzed by Claude, which extracts a title, summary, and topic tags. Results are stored in `~/.claude/catalog/catalog.db` (SQLite, WAL mode).

**What gets indexed:** Deep explorations, research, TIL moments, technical discoveries, documentation writing, theoretical discussions, estimation with depth. Quick one-shots, command execution sessions, and subagent traces are skipped.

**Auto-indexing:** The stop hook (`claudecat install-hook`) fires after each Claude Code session and indexes the conversation in the background.

## Uninstalling

Run teardown before uninstalling to clean up the hook and database:

```bash
claudecat teardown
```

Then remove the binary (or `brew uninstall claudecat` when available).

## Development

```bash
git clone https://github.com/chrisbloom7/claudecat.git
cd claudecat

# Run tests (requires bats-core: brew install bats-core)
./run-tests

# Run a specific test file
./run-tests tests/bin/claudecat.bats
./run-tests tests/helpers/claudecat_db_test.py
./run-tests --filter "search"
```

## License

MIT — see [LICENSE](LICENSE).
