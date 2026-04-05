bats_require_minimum_version 1.5.0

load "../test_helper"

# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------

setup() {
  _setup_common
  UNINSTALL="${PROJECT_ROOT}/uninstall"
}

teardown() {
  _teardown_common
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@test "uninstall: warns and exits 0 when towit is not in PATH" {
  run bash -c "env PATH='/usr/bin:/bin' '${UNINSTALL}' 2>&1"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Warning"* ]] || [[ "${output}" == *"not found"* ]] || {
    echo "Expected 'Warning' or 'not found' in output, got: ${output}"; return 1
  }
}

@test "uninstall: invokes towit implode with the given install dir" {
  local install_dir="${TEST_TMPDIR}/custom_bin"
  mkdir -p "${install_dir}"

  local invocation_log="${TEST_TMPDIR}/towit_invocation"
  export INVOCATION_LOG="${invocation_log}"
  cat > "${TEST_TMPDIR}/mock_bin/towit" <<'EOF'
#!/usr/bin/env bash
echo "$*" > "${INVOCATION_LOG}"
exit 0
EOF
  chmod +x "${TEST_TMPDIR}/mock_bin/towit"

  run "${UNINSTALL}" "${install_dir}"
  [ "${status}" -eq 0 ]

  [ -f "${invocation_log}" ] || {
    echo "Expected invocation log at ${invocation_log}"; return 1
  }

  local invocation
  invocation="$(cat "${invocation_log}")"
  [[ "${invocation}" == *"implode"* ]] || {
    echo "Expected 'implode' in invocation log, got: ${invocation}"; return 1
  }
  [[ "${invocation}" == *"--install-dir"* ]] || {
    echo "Expected '--install-dir' in invocation log, got: ${invocation}"; return 1
  }
  [[ "${invocation}" == *"${install_dir}"* ]] || {
    echo "Expected install dir '${install_dir}' in invocation log, got: ${invocation}"; return 1
  }
}

@test "uninstall: uses /usr/local/bin as default install dir" {
  local invocation_log="${TEST_TMPDIR}/towit_invocation"
  export INVOCATION_LOG="${invocation_log}"
  cat > "${TEST_TMPDIR}/mock_bin/towit" <<'EOF'
#!/usr/bin/env bash
echo "$*" > "${INVOCATION_LOG}"
exit 0
EOF
  chmod +x "${TEST_TMPDIR}/mock_bin/towit"

  run "${UNINSTALL}"
  [ "${status}" -eq 0 ]

  [ -f "${invocation_log}" ] || {
    echo "Expected invocation log at ${invocation_log}"; return 1
  }

  local invocation
  invocation="$(cat "${invocation_log}")"
  [[ "${invocation}" == *"/usr/local/bin"* ]] || {
    echo "Expected '/usr/local/bin' in invocation log, got: ${invocation}"; return 1
  }
}
