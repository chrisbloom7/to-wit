---
name: release-towit
description: Use when releasing a new version of to-wit — when the user asks to "cut a release", "release vX.Y.Z", "bump the version", "tag a release", "publish a new version", or "do a release".
---

# Release to-wit

Release a new version of the to-wit CLI: determine version, audit README, update CHANGELOG, commit, tag, and push.

## Step 1 — Determine the Version

If the user provided an explicit version (e.g. `0.7.0`), use it. Otherwise:

1. Get the current version: `git tag --sort=-version:refname | head -1` → strips leading `v`
2. Ask the user: **"What's the release level — major, minor, or patch?"** (or accept a literal `X.Y.Z`)
3. Compute the new version by incrementing the appropriate semver component. Reset lower components to `0`.

Tags use a `v` prefix: `v0.7.0`.

## Step 2 — Audit the README

Read `README.md` and compare it against the `## [Unreleased]` section of `CHANGELOG.md` plus recent tagged releases.

Check for:
- New subcommands or flags that aren't documented in the Usage section
- Removed or renamed subcommands still listed
- Changed behavior (default scope, flag names, output format) that contradicts the README
- Installation or requirements notes that are out of date

Present a brief audit summary. If nothing is out of date, say so explicitly. If issues are found, propose edits and wait for approval before editing `README.md`.

## Step 3 — Update CHANGELOG.md

1. Read `CHANGELOG.md`.
2. Confirm there is content under `## [Unreleased]`. If it's empty, warn the user before proceeding.
3. Replace `## [Unreleased]` with two sections:

```markdown
## [Unreleased]

## [X.Y.Z] - YYYY-MM-DD
```

Use today's date. Move all existing Unreleased content under the new version heading. Do not alter the content itself.

## Step 4 — Commit

Stage only the files that were changed (README.md if edited, CHANGELOG.md always):

```bash
git add CHANGELOG.md README.md   # or just CHANGELOG.md if README was unchanged
git commit -m "chore: release vX.Y.Z"
```

Show the diff before committing and wait for approval.

## Step 5 — Tag and Push

```bash
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
```

Confirm each command succeeded. Report the tag name and the commit SHA it points to.

## Done

Summarize: version released, tag pushed, any README changes made.
