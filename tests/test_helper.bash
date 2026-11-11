#!/usr/bin/env bash
# test_helper.bash — shared setup/teardown for towit BATS test suite

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${TESTS_DIR}/.." && pwd)"
BIN_DIR="${PROJECT_ROOT}/bin"
HELPERS_DIR="${PROJECT_ROOT}/libexec/towit"

_setup_common() {
  TEST_TMPDIR="$(mktemp -d)"

  mkdir -p "${TEST_TMPDIR}/mock_bin"

  # No-op sleep mock (speeds up any log-style sleeps)
  cat > "${TEST_TMPDIR}/mock_bin/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${TEST_TMPDIR}/mock_bin/sleep"

  export PATH="${TEST_TMPDIR}/mock_bin:${PATH}"

  # Config file controls DB path for all subprocess invocations
  export TOWIT_CONFIG_PATH="${TEST_TMPDIR}/config.toml"
  local db_path="${TEST_TMPDIR}/test.db"
  printf '[database]\npath = "%s"\n' "${db_path}" > "${TOWIT_CONFIG_PATH}"

  export TOWIT="${BIN_DIR}/towit"

  # Clear mode vars that shell scripts might reference
  export FORCE_MODE=false
  export VERBOSE_MODE=false
  export QUIET_MODE=false
}

_teardown_common() {
  rm -rf "${TEST_TMPDIR}"
}

# write_fixture_session <dir> <session-id>
# Write a synthetic two-exchange Claude Code transcript to <dir>/<session-id>.jsonl.
write_fixture_session() {
  local dir="$1" session_id="$2"
  mkdir -p "${dir}"
  cat > "${dir}/${session_id}.jsonl" <<EOF
{"type":"user","timestamp":"2026-01-15T10:00:00Z","cwd":"/work/proj","sessionId":"${session_id}","message":{"role":"user","content":"How does SQLite WAL mode work?"}}
{"type":"assistant","timestamp":"2026-01-15T10:00:05Z","cwd":"/work/proj","sessionId":"${session_id}","message":{"role":"assistant","content":[{"type":"text","text":"WAL appends changes to a log."}]}}
{"type":"user","timestamp":"2026-01-15T10:01:00Z","cwd":"/work/proj","sessionId":"${session_id}","message":{"role":"user","content":"And how does it help concurrency?"}}
{"type":"assistant","timestamp":"2026-01-15T10:01:05Z","cwd":"/work/proj","sessionId":"${session_id}","message":{"role":"assistant","content":[{"type":"text","text":"Readers do not block the writer."}]}}
EOF
}
