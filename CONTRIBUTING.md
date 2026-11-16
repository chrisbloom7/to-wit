# Contributing to To Wit

Thanks for helping. Issues labeled `good first issue` and `help wanted` are the best places to start.

## Before you start

Comment on the issue so two people don't pick up the same one. For anything larger than a bug fix or a flag, open an issue first and describe the change.

## Tests first

The project is test-driven: write a failing test, then the code that makes it pass.

```bash
brew install bats-core      # once
./run-tests                 # everything
./run-tests tests/helpers/towit_search_test.py
./run-tests --filter "search"
```

## Keep these in step with your change

A change to the command line surface touches more than the code. Each item below has a test that fails when it drifts, except the CHANGELOG, which a maintainer checks:

- The help text in `bin/towit` and the Usage block in `README.md` (`tests/helpers/docs_consistency_test.py`).
- The shell completions in `completions/towit.bash` and `completions/_towit` when you add or rename a flag (`tests/helpers/towit_completion_test.py`).
- `plugins/towit/skills/towit/SKILL.md` when it names a flag you changed.
- An entry under `## [Unreleased]` in `CHANGELOG.md`, under the right heading (`Added`, `Changed`, `Fixed`, `Removed` or `Security`).

## Signed commits

`main` requires verified commit signatures. If your commits are not signed, you don't need to do anything: a maintainer re-signs them when merging, and you stay the author.

## AI-assisted contributions

Welcome. Say so in the pull request, and review the code yourself before you open it.

## Review and merging

One maintainer reviews and merges every pull request. Changes to `.claude/`, `CLAUDE.md` and `AGENTS.md` need the maintainer's explicit approval, because they steer coding agents on a reviewer's machine.
