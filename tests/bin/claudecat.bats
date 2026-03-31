bats_require_minimum_version 1.5.0

load "../test_helper"

# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------

setup() {
  _setup_common
  export CLAUDECAT_DB_PATH="${TEST_TMPDIR}/test.db"
  CLAUDECAT="${BIN_DIR}/claudecat"
}

teardown() {
  _teardown_common
}

# ---------------------------------------------------------------------------
# No args / usage
# ---------------------------------------------------------------------------

@test "claudecat: no args prints usage and exits non-zero" {
  run "${CLAUDECAT}"
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"Usage"* ]] || [[ "${output}" == *"subcommand"* ]] || {
    echo "Expected usage/subcommand in output, got: ${output}"; return 1
  }
}

@test "claudecat: unknown subcommand prints error and exits non-zero" {
  run "${CLAUDECAT}" notacommand
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"unknown subcommand"* ]] || [[ "${output}" == *"notacommand"* ]] || {
    echo "Expected unknown subcommand error, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# help subcommand
# ---------------------------------------------------------------------------

@test "claudecat: help subcommand prints usage and exits 0" {
  run "${CLAUDECAT}" help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Usage"* ]] || {
    echo "Expected 'Usage' in output, got: ${output}"; return 1
  }
}

@test "claudecat: --help flag prints usage and exits 0" {
  run "${CLAUDECAT}" --help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Usage"* ]] || {
    echo "Expected 'Usage' in output, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# setup subcommand
# ---------------------------------------------------------------------------

@test "claudecat: setup creates the database file" {
  [ ! -f "${CLAUDECAT_DB_PATH}" ] || rm -f "${CLAUDECAT_DB_PATH}"
  run "${CLAUDECAT}" setup
  [ "${status}" -eq 0 ]
  [ -f "${CLAUDECAT_DB_PATH}" ] || {
    echo "Expected DB file at ${CLAUDECAT_DB_PATH}"; return 1
  }
}

@test "claudecat: setup a second time prints 'already initialized'" {
  "${CLAUDECAT}" setup
  run "${CLAUDECAT}" setup
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"already"* ]] || {
    echo "Expected 'already' in output on second setup, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# search subcommand
# ---------------------------------------------------------------------------

@test "claudecat: search with no terms exits non-zero" {
  "${CLAUDECAT}" setup
  run bash -c "\"${CLAUDECAT}\" search 2>&1"
  [ "${status}" -ne 0 ]
}

# ---------------------------------------------------------------------------
# list subcommand
# ---------------------------------------------------------------------------

@test "claudecat: list on empty DB exits 0" {
  "${CLAUDECAT}" setup
  run "${CLAUDECAT}" list
  [ "${status}" -eq 0 ]
}

# ---------------------------------------------------------------------------
# stats subcommand
# ---------------------------------------------------------------------------

@test "claudecat: stats on empty DB exits 0 and prints stats" {
  "${CLAUDECAT}" setup
  run "${CLAUDECAT}" stats
  [ "${status}" -eq 0 ]
}

# ---------------------------------------------------------------------------
# python3 missing
# ---------------------------------------------------------------------------

@test "claudecat: missing python3 prints helpful error and exits non-zero" {
  # macOS always ships a python3 stub at /usr/bin/python3, so we cannot reliably
  # remove python3 from PATH on this platform. Skip rather than false-positive.
  if [[ "$(uname)" == "Darwin" ]]; then
    skip "macOS ships /usr/bin/python3 stub — cannot remove python3 from PATH"
  fi
  run env PATH="/bin:/usr/bin" "${CLAUDECAT}" setup 2>&1
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"python3"* ]] || [[ "${output}" == *"Python"* ]] || {
    echo "Expected python3 error message, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# install-hook subcommand
# ---------------------------------------------------------------------------

@test "claudecat: install-hook writes hook to settings.local.json" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  run env CLAUDECAT_SETTINGS_PATH="${settings_file}" "${CLAUDECAT}" install-hook
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"installed"* ]] || {
    echo "Expected 'installed' in output, got: ${output}"; return 1
  }
  [ -f "${settings_file}" ] || {
    echo "Expected settings file at ${settings_file}"; return 1
  }
  run grep -c "claudecat_hook.py" "${settings_file}"
  [ "${output}" -ge 1 ]
}

# ---------------------------------------------------------------------------
# uninstall-hook subcommand
# ---------------------------------------------------------------------------

@test "claudecat: uninstall-hook removes hook from settings.local.json" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  env CLAUDECAT_SETTINGS_PATH="${settings_file}" "${CLAUDECAT}" install-hook
  [ -f "${settings_file}" ]
  run env CLAUDECAT_SETTINGS_PATH="${settings_file}" "${CLAUDECAT}" uninstall-hook
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"removed"* ]] || [[ "${output}" == *"uninstalled"* ]] || {
    echo "Expected 'removed'/'uninstalled' in output, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# teardown subcommand
# ---------------------------------------------------------------------------

@test "claudecat: teardown --yes removes hook and database when both exist" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  "${CLAUDECAT}" setup
  env CLAUDECAT_SETTINGS_PATH="${settings_file}" "${CLAUDECAT}" install-hook
  [ -f "${CLAUDECAT_DB_PATH}" ]
  [ -f "${settings_file}" ]
  run env CLAUDECAT_SETTINGS_PATH="${settings_file}" "${CLAUDECAT}" teardown --yes
  [ "${status}" -eq 0 ]
  [ ! -f "${CLAUDECAT_DB_PATH}" ] || {
    echo "Expected DB to be removed after teardown"; return 1
  }
}

# ---------------------------------------------------------------------------
# implode subcommand
# ---------------------------------------------------------------------------

@test "claudecat: implode --yes removes hook and database when both exist" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  "${CLAUDECAT}" setup
  env CLAUDECAT_SETTINGS_PATH="${settings_file}" "${CLAUDECAT}" install-hook
  [ -f "${CLAUDECAT_DB_PATH}" ]
  [ -f "${settings_file}" ]
  run env CLAUDECAT_SETTINGS_PATH="${settings_file}" \
    "${CLAUDECAT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
  [ ! -f "${CLAUDECAT_DB_PATH}" ] || {
    echo "Expected DB to be removed after implode"; return 1
  }
}

@test "claudecat: implode --yes removes binary symlink" {
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  local fake_target="${TEST_TMPDIR}/fake_claudecat"
  touch "${fake_target}"
  ln -s "${fake_target}" "${install_dir}/claudecat"
  [ -L "${install_dir}/claudecat" ]
  run env CLAUDECAT_SETTINGS_PATH="${TEST_TMPDIR}/settings.local.json" \
    "${CLAUDECAT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
  [ ! -L "${install_dir}/claudecat" ] || {
    echo "Expected symlink to be removed after implode"; return 1
  }
}

@test "claudecat: implode --yes prints data directory path" {
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  "${CLAUDECAT}" setup
  run "${CLAUDECAT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"$(dirname "${CLAUDECAT_DB_PATH}")"* ]] || {
    echo "Expected data directory in output, got: ${output}"; return 1
  }
}

@test "claudecat: implode warns when binary is not a symlink" {
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  echo "#!/bin/bash" > "${install_dir}/claudecat"
  run "${CLAUDECAT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"not a symlink"* ]] || {
    echo "Expected 'not a symlink' warning, got: ${output}"; return 1
  }
  [ -f "${install_dir}/claudecat" ] || {
    echo "Expected regular file to remain (not removed)"; return 1
  }
}

@test "claudecat: implode exits 0 when nothing to remove" {
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  run "${CLAUDECAT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
}

# ---------------------------------------------------------------------------
# setup --hook subcommand
# ---------------------------------------------------------------------------

@test "claudecat: setup --hook creates DB and installs hook" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  [ ! -f "${CLAUDECAT_DB_PATH}" ] || rm -f "${CLAUDECAT_DB_PATH}"
  run env CLAUDECAT_SETTINGS_PATH="${settings_file}" "${CLAUDECAT}" setup --hook
  [ "${status}" -eq 0 ]
  [ -f "${CLAUDECAT_DB_PATH}" ] || {
    echo "Expected DB file at ${CLAUDECAT_DB_PATH}"; return 1
  }
  [ -f "${settings_file}" ] || {
    echo "Expected settings file at ${settings_file}"; return 1
  }
}
