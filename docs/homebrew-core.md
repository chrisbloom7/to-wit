# Submitting To Wit to homebrew-core

To Wit is currently distributed through its own tap (`brew install chrisbloom7/tap/towit`, repository [chrisbloom7/homebrew-tap](https://github.com/chrisbloom7/homebrew-tap)). This note records what it would take to move the formula into `homebrew/core`, so the question can be rechecked without redoing the research.

Sources (read 2026-11-11): the Homebrew [Package Acceptance Policy](https://docs.brew.sh/Package-Acceptance-Policy) and [Acceptable Formulae](https://docs.brew.sh/Acceptable-Formulae). Homebrew can change these; recheck them before submitting.

## Notability (the current blocker)

For a GitHub project, a new package must show public interest beyond its author:

| Submitter | Needs at least one of |
|---|---|
| Anyone else | 30 forks, 30 watchers, or 75 stars |
| The repository owner (a self-submission), or a commit author whose email is at the package's homepage/url/head domain | **90 forks, 90 watchers, or 225 stars** |

The metrics apply to the canonical upstream repository (`chrisbloom7/to-wit`), not a mirror. Meeting them does not guarantee acceptance, and new submissions can be held to a higher standard. A self-submission without a public repository can still be accepted with evidence of notability in the pull request.

Check the current numbers:

```bash
gh api repos/chrisbloom7/to-wit -q '"stars=\(.stargazers_count) forks=\(.forks_count) watchers=\(.subscribers_count)"'
```

| Date | Stars | Forks | Watchers |
|---|---|---|---|
| 2026-11-11 | 5 | 0 | 0 |

The self-submission bar is 225 stars, 90 forks, or 90 watchers. A submission by someone else (a contributor who is not the owner or a commit author at the project's domain) needs only 75 stars, 30 forks, or 30 watchers.

## Other requirements, and where To Wit stands

| Requirement | Status |
|---|---|
| Repository at least 30 days old | Met (created 2026-03-30) |
| Open-source license compatible with the DFSG | Met (GPL-3.0; declared `GPL-3.0-only` in the formula) |
| Stable, immutable tag; no moving branch or unchecksummed download | Met (`vX.Y.Z` tags; the formula uses the tag tarball and its `sha256`) |
| Must not depend on a cask or proprietary software | Met (depends on `python@3.x` only; Claude Code is optional and only mentioned in `caveats`) |
| Builds and passes its test on the core CI matrix (macOS and Linux) | Likely; the tap's `brew test-bot` run passes on both. Not tried in core CI |
| Working `livecheck` | Default behavior applies (GitHub tags); confirm with `brew livecheck` when submitting |
| Actively maintained, no known unpatched vulnerabilities | Met |

## When the bar is met

Moving from the tap to core means opening a pull request against `Homebrew/homebrew-core` with the formula (see Homebrew's [Adding Software to Homebrew](https://docs.brew.sh/Adding-Software-to-Homebrew), which this note has not summarized), then deleting or redirecting the tap formula so the two do not conflict. A third-party tap remains available at any star count.
