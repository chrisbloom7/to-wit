#!/usr/bin/env bash
# Stop hook: when code or docs changed in the working tree, run the docs
# consistency test so README/AGENTS.md/help-text drift is fixed in the same turn.
set -uo pipefail

payload="$(cat)"
# A prior Stop-hook block already re-prompted Claude; don't loop.
if [[ "$(jq -r '.stop_hook_active // false' <<<"$payload")" == "true" ]]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0

# Only act when a file the test reads has uncommitted changes.
if ! git status --porcelain | rg -q '^.. (libexec/towit/.*\.py|bin/towit|README\.md|AGENTS\.md|SECURITY\.md)$'; then
  exit 0
fi

if out="$(./run-tests tests/helpers/docs_consistency_test.py 2>&1)"; then
  exit 0
fi

{
  echo "docs_consistency_test.py failed: docs and code disagree. Update the docs it names."
  echo "$out" | tail -n 40
} >&2
exit 2
