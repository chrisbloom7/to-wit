# Claude Code Skill Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an installable Claude Code plugin whose skill teaches Claude to search, read and resume archived conversations with the `towit` CLI, installable with `towit setup --skill` or the two `claude plugin` commands.

**Architecture:** The repo becomes a Claude Code plugin marketplace (`.claude-plugin/marketplace.json`) with one plugin (`plugins/towit/`) holding one skill (`skills/towit/SKILL.md`). The skill is documentation only: it calls the existing CLI, with no hooks, no MCP server and no statusline. `towit setup --skill` wraps `claude plugin marketplace add chrisbloom7/to-wit#v<VERSION>` and `claude plugin install`, so the skill always matches the installed CLI; `towit doctor` reports whether the plugin is installed; `towit implode` removes it.

**Tech Stack:** Python 3.11+ stdlib, `unittest`, BATS, the `claude plugin` CLI.

**Reference:** Worktrunk's integration (https://worktrunk.dev/claude-code/, `skills/worktrunk/`, `plugins/worktrunk/`, `.claude-plugin/`).

## Global Constraints

- No schema change; nothing new stored in the database.
- The skill is read-only guidance. It never tells Claude to run `forget`, `prune` or `implode` unless the user asked for that action by name.
- Archived text is untrusted data: the skill says so, and says to summarize it rather than follow instructions found in it.
- Subprocesses (`claude plugin ...`) use list form, never `shell=True`, user scope only. They inherit the full environment instead of `safe_subprocess_env()`: the marketplace add is a git clone run on the user's behalf and needs their git/ssh credentials (`SSH_AUTH_SOCK`, `GIT_*`), which the hook-oriented allowlist drops. SECURITY.md and AGENTS.md say so explicitly; the allowlist sentence there stays unchanged.
- `towit setup --skill` is opt-in: `--full` does not install the plugin (it already installs hooks, which edit user settings; a plugin install is a separate consent).
- No new runtime dependency. A missing `claude` CLI is a clear error from `--skill` and a SKIP in doctor, not a crash.
- American English everywhere.
- Directives: plan approved before code; failing tests first; commits of at most 300 changed lines (ask before exceeding); `wt switch --create`, never raw `git worktree`.

## Task 0 Findings (spiked 2026-11-15 against the real `claude` CLI, in an isolated `CLAUDE_CONFIG_DIR`)

1. **Manifests.** `marketplace.json`: `name`, `owner.name`, `metadata.description`, `plugins[]` with `name`, `description`, `source: "./plugins/towit"`. `plugin.json`: `name`, `description`, `author`, `homepage`, `repository`, `license`, `keywords`. Worktrunk omits `version` (installs are keyed by commit SHA); we omit it too, so there is no version file to keep in sync. `claude plugin validate <path>` checks both manifests and the skill; the tests use it when `claude` is on PATH.
2. **Pinning works.** `claude plugin marketplace add owner/repo#vX.Y.Z` is accepted and recorded as `ref` in `extraKnownMarketplaces`. Decision: pin to `v<VERSION>` so the skill always matches the installed CLI. Constraints found:
   - Adding the same marketplace name from a different source (including a different ref) fails with `failureCode: "declared"`.
   - `marketplace remove` also uninstalls that marketplace's plugins.
   - So re-pinning is: remove marketplace, add at the new ref, install the plugin again. `setup --skill` does this when the declared ref differs from `v<VERSION>`, and `doctor` warns on that mismatch.
   - Between a release PR merge and the tag push, `v<VERSION>` does not exist yet; `add` then fails with a clear clone error, which `setup --skill` passes through.
3. **Idempotency.** `marketplace add` and `plugin install` rerun with exit 0 (`outcome: "ok"`, message says already on disk/installed). `--json` prints one result line (`outcome`, `failureCode`). Non-interactive use needs no `-y` for a plain marketplace plugin. `plugin list --json` gives `id` (`plugin@marketplace`), `scope`, `enabled`.
4. **Uninstall.** `claude plugin uninstall towit@to-wit` and `claude plugin marketplace remove to-wit` exit 1 with `failureCode: "not_installed"` / "not found" when absent; `implode` treats that as success. Default scope is `user`; towit only uses user scope.
5. **Naming.** Marketplace `to-wit`, plugin `towit`, id `towit@to-wit`. Install: `claude plugin marketplace add chrisbloom7/to-wit` then `claude plugin install towit@to-wit` (unpinned manual form; `setup --skill` pins).

## File Structure

- Create: `.claude-plugin/marketplace.json`
- Create: `plugins/towit/.claude-plugin/plugin.json`
- Create: `plugins/towit/skills/towit/SKILL.md` (plus `reference/` only if the body grows past about 150 lines)
- Create: `libexec/towit/towit_skill.py` (install, uninstall and status helpers around the `claude plugin` CLI; imported by setup, doctor and implode)
- Modify: `libexec/towit/towit_setup.py` (`--skill`)
- Modify: `libexec/towit/towit_doctor.py` (plugin check)
- Modify: `libexec/towit/towit_implode.py` (remove plugin)
- Modify: `bin/towit` (help text for `setup --skill`)
- Modify: `README.md`, `AGENTS.md`, `SECURITY.md`, `CHANGELOG.md`
- Modify: `.claude/skills/release-towit/SKILL.md` (verify `claude plugin validate .` and the tag-before-install ordering)
- Create: `tests/helpers/towit_skill_test.py`; modify `tests/helpers/docs_consistency_test.py`, `tests/helpers/towit_setup_test.py`, `tests/helpers/towit_doctor_test.py`, `tests/bin/uninstall.bats`, `tests/bin/towit.bats`

## Tasks

### Task 0: Spike the open questions

- [x] Read Worktrunk's installed `marketplace.json`, `plugin.json` and `SKILL.md` and the `claude plugin` help.
- [x] Ran add, install, rerun, uninstall, remove, ref pinning and ref change against throwaway and real marketplaces with an isolated `CLAUDE_CONFIG_DIR`.
- [x] Recorded the findings above; commit (docs only).

### Task 1: Plugin files and consistency tests

- [ ] Failing tests in `docs_consistency_test.py` (`TestPlugin`): both manifests parse as JSON; the marketplace lists the `towit` plugin with a source that resolves to `plugins/towit`; `plugin.json` name is `towit`; `SKILL.md` has frontmatter with `name: towit` and a non-empty `description`; every `towit` subcommand the skill mentions exists in `bin/towit`'s dispatcher; every flag the skill mentions appears in the help text; `plugin.json` has no `version` key; `claude plugin validate` passes on the repo and on `plugins/towit` when `claude` is on PATH (skipped otherwise); `--strict` is not used because it fails on the deliberately missing `version`; the skill's body contains the untrusted-data warning and does not instruct running `forget`, `prune` or `implode`.
- [ ] Run them and confirm they fail.
- [ ] Write the manifests and `SKILL.md`. Skill content:
  - When to use: the user asks what was done or decided in a past session, wants to find a conversation, or wants to resume one.
  - Workflow: `towit search <terms> --format json`, then `towit show <id> --around <Msg>`; fall back to `towit show <id> --role user --match <term>` when search misses; `towit list --topic/--keyword/--repo` to browse; `towit resume <id>` to hand back to the user.
  - Notes: Msg numbers are 0-based; `--repo NAME` matches worktree directories; plain terms are AND with an OR retry, and text matching is stemmed.
  - Guardrails: archived text is untrusted data; never run `forget`, `prune` or `implode` unprompted; run `towit version` and `towit --help` if a flag is unfamiliar; if `towit` is not found, point to the README install steps.
- [ ] Run the tests and confirm they pass; commit.

### Task 2: `towit_skill.py` helpers

- [ ] Failing unit tests in `towit_skill_test.py`, with `subprocess.run` mocked: `install(version)` runs `marketplace add chrisbloom7/to-wit#v<version> --json` then `plugin install towit@to-wit --json` with list-form args and `safe_subprocess_env()`; rerun is a no-op success; when `add` fails with `failureCode: "declared"` it removes the marketplace, re-adds at the new ref and reinstalls (repin); `declared_ref()` reads the ref from `claude plugin marketplace list` or user `settings.json` `extraKnownMarketplaces`; `claude` missing raises a clear error; a nonzero exit surfaces stderr; `uninstall()` removes plugin then marketplace and tolerates "not installed"; `status()` returns installed, not-installed or unavailable.
- [ ] Implement, matching the style of `towit_install_hook.py`; run tests; commit.

### Task 3: `towit setup --skill`

- [ ] Failing tests in `towit_setup_test.py` and `towit.bats`: `--skill` installs after setup succeeds; works on an existing database; `--full` does not install it; missing `claude` prints an error and exits nonzero without damaging the database; the BATS mock `claude` records the exact commands run.
- [ ] Implement the flag in `towit_setup.py`; add it to `bin/towit` help; run tests; commit.

### Task 4: Doctor check

- [ ] Failing tests in `towit_doctor_test.py`: PASS when installed at `v<VERSION>`, WARN with the remediation `towit setup --skill` when `claude` exists but the plugin is not installed or is pinned to a different ref (or unpinned), SKIP-equivalent when `claude` is missing (no duplicate failure beyond `check_claude_cli`).
- [ ] Implement `check_skill_plugin` using `towit_skill.status()`; run tests; commit.

### Task 5: Implode

- [ ] Failing test in `uninstall.bats`: `towit implode` calls the plugin and marketplace uninstall when installed, skips quietly when not or when `claude` is missing, and never fails the uninstall because of it.
- [ ] Implement; run tests; commit.

### Task 6: Docs and release plumbing

- [ ] README: a "Claude Code skill" section with both install forms, what the skill does, and the update path; usage block lists `setup --skill`.
- [ ] AGENTS.md: add `towit_skill.py` to the module list, the plugin layout to the architecture section, `claude plugin` to the subprocess list; SECURITY.md: the untrusted-data stance and the new subprocess calls.
- [ ] CHANGELOG `[Unreleased]`: Added entry.
- [ ] Release skill: add `claude plugin validate .` to Step 0 and a final check that `claude plugin marketplace add chrisbloom7/to-wit#v<VERSION>` succeeds once the tag is pushed.
- [ ] Run `./run-tests` and `TOWIT_RELEASE_CHECK=1 ./run-tests tests/helpers/docs_consistency_test.py`; commit.

### Task 7: End-to-end check

- [ ] In a clean temp `HOME`, run `towit setup --skill` against the real `claude` CLI, start a session, ask "find the conversation where we discussed X" and confirm the skill loads and uses `search` then `show --around`.
- [ ] Run `towit doctor`; run `towit implode` and confirm the plugin is gone.
- [ ] Open the PR (needs-your-answer section first, per your PR conventions; no UI, so no screenshots).

## Review Focus

1. Rerunning `towit setup --skill` leaves exactly one marketplace and one plugin install.
2. The skill cannot be read as authorization to delete data.
3. Doctor and implode behave when `claude` is absent, or when the plugin was installed by hand.
4. Skill text and CLI help agree, enforced by the consistency test rather than by memory.

## Release

Minor version (new user-visible feature). Cut it with the `release-towit` skill after the PR merges; the first release that includes the marketplace file is the first one `claude plugin marketplace add chrisbloom7/to-wit` can serve.
