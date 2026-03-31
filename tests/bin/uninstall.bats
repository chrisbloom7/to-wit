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

@test "uninstall: warns and exits 0 when claudecat is not in PATH" {
  run env PATH="/usr/bin:/bin" "${UNINSTALL}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Warning"* ]] || [[ "${output}" == *"not found"* ]] || {
    echo "Expected 'Warning' or 'not found' in output, got: ${output}"; return 1
  }
}

@test "uninstall: invokes claudecat implode with the given install dir" {
  local install_dir="${TEST_TMPDIR}/custom_bin"
  mkdir -p "${install_dir}"

  cat > "${TEST_TMPDIR}/mock_bin/claudecat" <<EOF
#!/usr/bin/env bash
echo "\$*" > "${TEST_TMPDIR}/claudecat_invocation"
exit 0
EOF
  chmod +x "${TEST_TMPDIR}/mock_bin/claudecat"

  run "${UNINSTALL}" "${install_dir}"
  [ "${status}" -eq 0 ]

  [ -f "${TEST_TMPDIR}/claudecat_invocation" ] || {
    echo "Expected invocation log at ${TEST_TMPDIR}/claudecat_invocation"; return 1
  }

  local invocation
  invocation="$(cat "${TEST_TMPDIR}/claudecat_invocation")"
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
  cat > "${TEST_TMPDIR}/mock_bin/claudecat" <<EOF
#!/usr/bin/env bash
echo "\$*" > "${TEST_TMPDIR}/claudecat_invocation"
exit 0
EOF
  chmod +x "${TEST_TMPDIR}/mock_bin/claudecat"

  run "${UNINSTALL}"
  [ "${status}" -eq 0 ]

  [ -f "${TEST_TMPDIR}/claudecat_invocation" ] || {
    echo "Expected invocation log at ${TEST_TMPDIR}/claudecat_invocation"; return 1
  }

  local invocation
  invocation="$(cat "${TEST_TMPDIR}/claudecat_invocation")"
  [[ "${invocation}" == *"/usr/local/bin"* ]] || {
    echo "Expected '/usr/local/bin' in invocation log, got: ${invocation}"; return 1
  }
}
