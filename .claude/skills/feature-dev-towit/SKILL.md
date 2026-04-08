---
name: feature-dev-towit
description: Use when developing a feature, fixing a bug, or making any code change in the to-wit project — when the user says "add", "implement", "fix", "change", or describes new behavior. Covers the full development lifecycle: plan, TDD, docs, commits.
---

# Feature Development — to-wit

Full lifecycle for any code change: plan → TDD (ZOMBIES) → docs → incremental commits.

## Step 1 — Plan First

Before touching code, produce a written plan. Ask clarifying questions until the requirements are unambiguous, then present the plan and **wait for explicit approval**.

The plan must include:

1. **What changes** — affected files in `bin/`, `libexec/towit/`, `tests/`
2. **New/changed CLI surface** — flags, subcommands, output format changes
3. **TDD order** — which ZOMBIES cases to write first (see Step 2)
4. **README delta** — exact sections that need updating for user-facing changes
5. **CHANGELOG entry** — draft of the `## [Unreleased]` bullet(s) under the appropriate heading (`Added`, `Changed`, `Fixed`, `Removed`, `Security`)
6. **Optimization notes** — proactively flag any simpler approaches, consolidation opportunities, or performance concerns noticed during planning

After drafting the plan, **critique it before presenting it**:

- What assumptions did you make about existing behavior, data shape, or user intent?
- Where could this approach fail silently or produce incorrect results?
- Are there edge cases the ZOMBIES order doesn't yet cover?
- Is any part of the plan under-specified — where you'd have to guess during implementation?

For each identified assumption or risk: either resolve it by reading the relevant code, add it as an explicit question to raise with the user, or note it as a known limitation in the plan. Do not present a plan that contains unresolved ambiguities you haven't acknowledged.

Do not proceed until the user approves the plan.

## Step 2 — TDD with ZOMBIES

Write tests before implementation. Follow the ZOMBIES order for each new unit of behavior:

| Letter | Case | Example |
|--------|------|---------|
| **Z** | Zero / null / empty | No args, empty DB, empty result set |
| **O** | One | Single conversation, single keyword |
| **M** | Many | Multiple results, pagination edge cases |
| **B** | Boundaries | Exact match limits, max keyword count, long strings |
| **I** | Interface | CLI flag combinations, `--format json/csv`, exit codes |
| **E** | Exceptions | Bad DB path, missing config, invalid input |
| **S** | Scenarios | Realistic end-to-end use (search + filter + format) |

**Test file conventions:**
- New subcommand helper → `tests/helpers/towit_<name>_test.py` (Python `unittest`)
- CLI integration → `tests/bin/towit.bats` (BATS)
- Run all tests: `./run-tests`
- Run one file: `./run-tests tests/helpers/towit_<name>_test.py`
- Run filtered: `./run-tests --filter "<pattern>"`

**Cycle for each behavior:**
1. Write the failing test (`./run-tests` → confirm RED)
2. Write the minimal implementation to pass it (`./run-tests` → confirm GREEN)
3. Refactor if needed; re-run tests

**Never commit with a failing test.**

## Step 3 — Implementation Guidelines

- **Dispatcher:** `bin/towit` routes to `libexec/towit/towit_<subcommand>.py`; new subcommands need an entry there
- **DB access:** all SQL lives in `towit_db.py` — no raw queries elsewhere
- **Config:** read via `towit_config.py`; never read env vars directly in subcommand modules
- **Helper text:** if a CLI flag or subcommand is added, changed, or removed, update the `help` output in `bin/towit` immediately — it is the canonical usage reference
- **Security:** parameterized queries only, no f-strings in SQL, path-validate any user-supplied file paths

## Step 4 — Commit Strategy

Slice work into logical feature units and commit each as a complete slice: **tests + implementation together**, never one without the other.

Target **≤ 300 lines changed** per commit. If a slice cannot fit within that limit, ask for permission before proceeding with the larger commit.

A separate final commit covers documentation: README, CHANGELOG, and helper text updates. If the helper text is tightly coupled to a code change (e.g. a new flag), it may go in the same slice commit instead.

**Commit message format:** `<type>: <short description>` where type is `feat`, `fix`, `refactor`, `test`, `docs`, or `chore`.

## Step 5 — Docs Updates

**README.md** — update for any user-facing change:
- New or changed subcommand → update the Usage table
- New or changed flag → update the flag list under the subcommand
- Behavioral change → update "How it works" if relevant

**CHANGELOG.md** — add a bullet under `## [Unreleased]` using the draft from the plan. Use Keep a Changelog headings: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.

**Helper text (`bin/towit`)** — keep in sync with README; both must match the implementation.

## Optimization Checklist

Proactively raise these during planning or implementation:

- Can a new flag reuse existing DB queries, or does it need a new one?
- Does new output format logic belong in `towit_db.py` (query) or the subcommand module (formatting)?
- Will the change impede or cause significant delay to the indexing hook (`towit_hook.py` → `towit_index.py`)?
- Will the change result in a significant increase in spend per indexing call (extra Claude API calls, larger prompts, more tokens)?
- Does anything in the change negatively affect performance or cross-platform deployability (macOS/Linux shell compatibility, Python stdlib vs. third-party dependencies, path assumptions)?
- Are there existing tests in adjacent test files that could share fixtures?

## Quick Reference

```bash
./run-tests                                        # full suite
./run-tests tests/helpers/towit_search_test.py     # one module
./run-tests --filter "search"                      # name filter
bin/towit help                                     # check helper text
```
