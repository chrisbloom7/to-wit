---
name: release-towit
description: Use when releasing a new version of to-wit — when the user asks to "cut a release", "release vX.Y.Z", "bump the version", "tag a release", "publish a new version", or "do a release".
---

# Release to-wit

Release a new version of the to-wit CLI: check preconditions, determine version, audit docs, update CHANGELOG, commit on a release branch, open a PR, (after the user merges it) tag and push the tag, and then update the Homebrew tap formula.

Never run `wt merge` and never push `main`. All merges into `main` come from remote branches via PR, merged by the user.

## Step 0 — Preconditions

Verify all of the following before doing anything else. If any fails, **stop and report it**.

```bash
git branch --show-current                  # must be main
git status --porcelain                     # must be empty
git fetch origin && git status -sb         # main must not be behind (or ahead of) origin/main
./run-tests                                # full suite green
TOWIT_RELEASE_CHECK=1 ./run-tests tests/helpers/docs_consistency_test.py   # docs consistency green
gh api repos/chrisbloom7/to-wit -q '"stars=\(.stargazers_count) forks=\(.forks_count) watchers=\(.subscribers_count)"'   # informational
```

The last command is not a gate: compare its numbers with the homebrew-core thresholds in `docs/homebrew-core.md` and tell the user if any is close to (or past) the bar. If the numbers changed since the table in that doc, mention it.

## Step 1 — Determine the Version

If the user provided an explicit version (e.g. `0.7.0`), use it. Otherwise:

1. Get the current version: `git tag --sort=-version:refname | head -1` → strips leading `v`
2. Ask the user: **"What's the release level — major, minor, or patch?"** (or accept a literal `X.Y.Z`)
3. Compute the new version by incrementing the appropriate semver component. Reset lower components to `0`.

Tags use a `v` prefix: `v0.7.0`.

Validate the version before continuing (stop if any check fails):

1. It matches the SemVer 2.0.0 pattern `^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$` (no leading `v`, no leading zeros, no pre-release or build suffix)
2. It is strictly greater than the latest tag (compare numerically per component, e.g. `sort -V`)
3. The tag is unused: `git tag -l vX.Y.Z` prints nothing and `git ls-remote --tags origin vX.Y.Z` is empty

Then create the release branch with `wt` (not `git worktree`) and do all remaining edits (Steps 2–4, including any `bin/towit` fixes) from the new worktree, never on `main`:

```bash
wt switch --create chore/release-vX.Y.Z --yes
```

Verify the `wt` hooks succeeded; if any failed, stop and report.

## Step 2 — Audit Help Text and Docs

### 2a — Validate `towit --help`

Run `bin/towit help` and compare its output against the Usage section of `README.md` and the actual subcommand implementations in `bin/towit` and `libexec/towit/`.

Check for:
- Subcommands or flags present in the implementation but missing from `--help`
- Subcommands or flags in `--help` that no longer exist
- Description or default values in `--help` that contradict the implementation

If any discrepancies are found, **stop and fix `bin/towit` before proceeding**. Help text must match the implementation before a release is tagged.

### 2b — Audit README.md

Read `README.md` and compare it against the `## [Unreleased]` section of `CHANGELOG.md` plus recent tagged releases.

Check for:
- New subcommands or flags that aren't documented in the Usage section
- Removed or renamed subcommands still listed
- Changed behavior (default scope, flag names, output format) that contradicts the README
- Installation or requirements notes that are out of date
- Usage section out of sync with `bin/towit help` output

Present a brief audit summary. If nothing is out of date, say so explicitly. If issues are found, propose edits and wait for approval before editing `README.md`.

### 2c — Audit SECURITY.md and AGENTS.md

Read `SECURITY.md` and `AGENTS.md` and compare them against the `## [Unreleased]` section of `CHANGELOG.md` and the implementation.

Check for:
- `SECURITY.md`: trust boundaries, stored data, redaction, or permission/hardening controls that changed but aren't reflected
- `AGENTS.md`: modules in `libexec/towit/`, database schema, environment variables, test layout, or security constraints that changed but aren't reflected

Present a brief audit summary. If issues are found, propose edits and wait for approval before editing either file.

## Step 3 — Update CHANGELOG.md

1. Read `CHANGELOG.md`.
2. Confirm there is content under `## [Unreleased]`. If it's empty, warn the user before proceeding.
3. Replace `## [Unreleased]` with two sections:

```markdown
## [Unreleased]

## [X.Y.Z] - YYYY-MM-DD
```

Use today's date from `gdate +%F` (GNU date on macOS). Move all existing Unreleased content under the new version heading. Do not alter the content itself.

## Step 4 — Commit on the Release Branch

Never commit the release to `main`. From the release worktree, stage only the files that were changed (CHANGELOG.md always; README.md, SECURITY.md, AGENTS.md if edited):

```bash
git add CHANGELOG.md README.md   # plus SECURITY.md / AGENTS.md if edited; just CHANGELOG.md if nothing else changed
git commit -m "chore: release vX.Y.Z"
```

## Step 5 — Open the PR

Push the release branch (never `main`) and open a PR with `gh`:

```bash
git push -u origin chore/release-vX.Y.Z
gh pr create --base main --title "chore: release vX.Y.Z" --body "<CHANGELOG entry for vX.Y.Z>"
```

**Stop here.** The user reviews and merges the PR. Do not merge it yourself and do not use `wt merge`.

## Step 6 — Tag and Push the Tag

Only after the user confirms the PR is merged, go to the main worktree (`main` is checked out there, so `git switch main` fails in the release worktree):

```bash
git switch main && git pull --ff-only
git log -1 --oneline                      # confirm this is the merged release commit
```

Ask the user to confirm before pushing the tag. Then tag the merged commit and push **only the tag**:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Confirm each command succeeded. Report the tag name and the commit SHA it points to.

## Step 7 — Update the Homebrew Tap

The formula lives in a separate repository, `chrisbloom7/homebrew-tap` (`Formula/towit.rb`, tap name `chrisbloom7/tap`). Nothing updates it automatically, so a release does not reach Homebrew users until this step is done. Do it right after the tag is pushed, and ask the user before pushing or opening the tap PR.

The tap's local checkout is Homebrew's own: `$(brew --repository chrisbloom7/tap)`. If it is not tapped, run `brew tap chrisbloom7/tap` first.

1. Make sure the tap checkout is clean and on `main`, then branch it (this is a normal branch, not a worktree):

```bash
TAP="$(brew --repository chrisbloom7/tap)"
git -C "${TAP}" switch main && git -C "${TAP}" pull --ff-only
git -C "${TAP}" switch -c towit-X.Y.Z
```

2. Rewrite the formula's `url` and `sha256` for the new tag (this downloads the tag tarball; it never runs git or commits):

```bash
.claude/skills/release-towit/bump-tap-formula X.Y.Z --tap-dir "${TAP}"
```

3. Verify the formula and show the diff to the user:

```bash
brew style chrisbloom7/tap/towit
brew reinstall chrisbloom7/tap/towit && brew test chrisbloom7/tap/towit
brew audit --strict --online chrisbloom7/tap/towit
git -C "${TAP}" diff
```

4. After the user approves the diff, commit and open the tap PR (the commit message is `towit X.Y.Z`). The user merges it; the tap's own CI (`brew test-bot`) runs on the PR.

```bash
git -C "${TAP}" commit -am "towit X.Y.Z"
git -C "${TAP}" push -u origin towit-X.Y.Z
gh pr create -R chrisbloom7/homebrew-tap --base main --head towit-X.Y.Z --title "towit X.Y.Z" --body "Bump towit to vX.Y.Z"
```

5. After the user confirms the tap PR is merged: `git -C "${TAP}" switch main && git -C "${TAP}" pull --ff-only`, delete the branch, then `brew update && brew upgrade towit` and confirm `towit doctor` still passes (a failing `claude` check is expected only if Claude Code is not installed).

Use `command cp -f` / `command rm -f` for any manual file replacement: `cp` and `rm` are interactive-aliased on the maintainer's machine and silently skip when there is no TTY.

## Done

Summarize: version released, release PR, tag pushed, tap PR (and whether it is merged), any README, SECURITY.md, or AGENTS.md changes made.
