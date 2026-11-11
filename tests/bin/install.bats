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

@test "install-hook: registered command runs under sh when the install path contains a space" {
  local root="${TEST_TMPDIR}/with space"
  mkdir -p "${root}"
  command cp -R "${PROJECT_ROOT}/bin" "${PROJECT_ROOT}/libexec" "${root}/"

  # setup() points HOME at a temp dir, which breaks version-manager python3 shims;
  # restore the real home for the interpreter only (config/db/settings stay isolated).
  export HOME="$(eval echo "~$(id -un)")"

  local settings="${TEST_TMPDIR}/settings.json"
  TOWIT_SETTINGS_PATH="${settings}" run env -u TOWIT_PYTHON "${root}/bin/towit" install-hook
  [ "${status}" -eq 0 ] || { echo "install-hook failed: ${output}"; return 1; }

  local command
  command="$(jq -r '.hooks.Stop[0].hooks[0].command' "${settings}")"
  [ -n "${command}" ] && [ "${command}" != "null" ]

  # sh must split the command into exactly two words: interpreter and script
  local words
  words="$(sh -c 'printf "%s\n" '"${command}")"
  [ "$(printf '%s\n' "${words}" | wc -l | tr -d ' ')" = "2" ] || {
    echo "Expected two shell words, got: ${words}"; return 1
  }
  # bin/towit resolves symlinks (macOS /var -> /private/var), so compare against the physical path
  local physical_root
  physical_root="$(cd "${root}" && pwd -P)"
  [ "$(printf '%s\n' "${words}" | tail -1)" = "${physical_root}/libexec/towit/towit_hook.py" ] || {
    echo "Unexpected script word in: ${words}"; return 1
  }

  # Run it for real with an inert payload and isolated config/db
  run bash -c "printf '%s' '{\"hook_event_name\":\"PreToolUse\"}' | sh -c \"\$1\" 2>&1" _ "${command}"
  [ "${status}" -eq 0 ] || { echo "hook exited ${status}: ${output}"; return 1; }
  [[ "${output}" != *"can't open file"* ]] || { echo "script not found: ${output}"; return 1; }
  [[ "${output}" != *"No such file"* ]] || { echo "script not found: ${output}"; return 1; }
}
