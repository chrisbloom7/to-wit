bats_require_minimum_version 1.5.0

load "../test_helper"

# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------

setup() {
  _setup_common
  INSTALL="${PROJECT_ROOT}/install"
  export HOME="${TEST_TMPDIR}/home"
  mkdir -p "${HOME}"
}

teardown() {
  # Restore write permission so the temp dir can be removed
  chmod -R u+w "${TEST_TMPDIR}" 2>/dev/null || true
  _teardown_common
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@test "install: defaults to ~/.local/bin and creates it when missing" {
  run "${INSTALL}"
  [ "${status}" -eq 0 ]
  [ -L "${HOME}/.local/bin/towit" ]
  [ "$(readlink "${HOME}/.local/bin/towit")" = "${PROJECT_ROOT}/bin/towit" ]
}

@test "install: links into an explicit install dir" {
  local dir="${TEST_TMPDIR}/custom_bin"
  mkdir -p "${dir}"
  run "${INSTALL}" "${dir}"
  [ "${status}" -eq 0 ]
  [ -L "${dir}/towit" ]
}

@test "install: errors when an explicit install dir does not exist" {
  run "${INSTALL}" "${TEST_TMPDIR}/nope"
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"does not exist"* ]]
  [ ! -e "${TEST_TMPDIR}/nope" ]
}

@test "install: explains a non-writable install dir instead of a bare ln error" {
  local dir="${TEST_TMPDIR}/readonly_bin"
  mkdir -p "${dir}"
  chmod a-w "${dir}"
  run "${INSTALL}" "${dir}"
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"not writable"* ]]
  [[ "${output}" == *"~/.local/bin"* ]]
  [[ "${output}" != *"Permission denied"* ]]
}

@test "install: warns when the install dir is not on PATH" {
  run "${INSTALL}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"not on your PATH"* ]]
  [[ "${output}" == *"${HOME}/.local/bin"* ]]
}

@test "install: does not warn when the install dir is on PATH" {
  local dir="${TEST_TMPDIR}/path_bin"
  mkdir -p "${dir}"
  PATH="${dir}:${PATH}" run "${INSTALL}" "${dir}"
  [ "${status}" -eq 0 ]
  [[ "${output}" != *"not on your PATH"* ]]
}
