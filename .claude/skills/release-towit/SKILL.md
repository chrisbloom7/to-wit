---
name: release-towit
description: Use when releasing a new version of to-wit - "cut a release", "release vX.Y.Z", "bump the version", "tag a release", "publish a new version", or "do a release".
---

# Release to-wit

Use the `chrisbloom7-development:release` skill with the parameters below. That skill holds the
generic steps and the safety rules (never `wt merge`, never push `main`, the owner merges the release
PR, confirm before pushing the tag). If it is not available, stop and tell the owner to install it
(`/plugin marketplace add chrisbloom7/ai-tools`, then install `chrisbloom7-development`).

## Release parameters

- project: to-wit
- flow: release-branch; base_branch: main
- preconditions:
  - `./run-tests` green
  - `TOWIT_RELEASE_CHECK=1 ./run-tests tests/helpers/docs_consistency_test.py` green
  - `claude plugin validate . && claude plugin validate plugins/towit` (skip if `claude` is not installed)
- informational: `gh api repos/chrisbloom7/to-wit -q '"stars=\(.stargazers_count) forks=\(.forks_count) watchers=\(.subscribers_count)"'`. Compare with the homebrew-core thresholds in `docs/homebrew-core.md` and say if any is close to or past the bar.
- version_file: `libexec/towit/VERSION`, version with no `v` prefix (`docs_consistency_test.py` fails if it differs from the newest CHANGELOG release)
- tag_style: lightweight, `vX.Y.Z`
- commit_message and pr_title: `chore: release vX.Y.Z`; branch `chore/release-vX.Y.Z`; the PR body is the CHANGELOG entry
- audit:
  - (blocking) `bin/towit help` vs the README Usage section and the implementation in `bin/towit` and `libexec/towit/`. Fix `bin/towit` before proceeding.
  - (advisory, propose edits and wait for approval) README.md vs `[Unreleased]` and recent releases, including `plugins/towit/skills/towit/SKILL.md` for new flags and subcommands.
  - (advisory, propose edits and wait for approval) SECURITY.md and AGENTS.md vs the changes.
- post_tag:
  1. Verify the plugin pins to the new tag, using an isolated config: `export CLAUDE_CONFIG_DIR="$(mktemp -d)"`, then `claude plugin marketplace add "chrisbloom7/to-wit#vX.Y.Z" --json` and `claude plugin install towit@to-wit --json` must both report "ok". Report any failure.
  2. Tap bump: formula `towit`, repo `chrisbloom7/to-wit`. After the tap merge, `brew update && brew upgrade towit` and confirm `towit doctor` passes (a failing `claude` check is expected only if Claude Code is not installed).
