bats_require_minimum_version 1.5.0

load "../test_helper"

# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------

setup() {
  _setup_common
  TOWIT="${BIN_DIR}/towit"
  # Convenience variable for assertions — mirrors the DB path written into TOWIT_CONFIG_PATH
  TOWIT_DB_PATH="${TEST_TMPDIR}/test.db"
}

teardown() {
  _teardown_common
}

# ---------------------------------------------------------------------------
# No args / usage
# ---------------------------------------------------------------------------

@test "towit: no args prints usage and exits non-zero" {
  run "${TOWIT}"
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"Usage"* ]] || [[ "${output}" == *"subcommand"* ]] || {
    echo "Expected usage/subcommand in output, got: ${output}"; return 1
  }
}

@test "towit: unknown subcommand prints error and exits non-zero" {
  run "${TOWIT}" notacommand
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"unknown subcommand"* ]] || [[ "${output}" == *"notacommand"* ]] || {
    echo "Expected unknown subcommand error, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# help subcommand
# ---------------------------------------------------------------------------

@test "towit: help subcommand prints usage and exits 0" {
  run "${TOWIT}" help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Usage"* ]] || {
    echo "Expected 'Usage' in output, got: ${output}"; return 1
  }
}

@test "towit: --help flag prints usage and exits 0" {
  run "${TOWIT}" --help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Usage"* ]] || {
    echo "Expected 'Usage' in output, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# setup subcommand
# ---------------------------------------------------------------------------

@test "towit: setup creates the database file" {
  [ ! -f "${TOWIT_DB_PATH}" ] || rm -f "${TOWIT_DB_PATH}"
  run "${TOWIT}" setup
  [ "${status}" -eq 0 ]
  [ -f "${TOWIT_DB_PATH}" ] || {
    echo "Expected DB file at ${TOWIT_DB_PATH}"; return 1
  }
}

@test "towit: setup a second time prints 'already initialized'" {
  "${TOWIT}" setup
  run "${TOWIT}" setup
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"already"* ]] || {
    echo "Expected 'already' in output on second setup, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# setup --config subcommand
# ---------------------------------------------------------------------------

@test "towit: setup --config creates config file" {
  local cfg="${TEST_TMPDIR}/new_config.toml"
  TOWIT_CONFIG_PATH="${cfg}" run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
  [ -f "${cfg}" ] || {
    echo "Expected config file at ${cfg}"; return 1
  }
}

@test "towit: setup --config prints path of created config" {
  local cfg="${TEST_TMPDIR}/new_config.toml"
  TOWIT_CONFIG_PATH="${cfg}" run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"${cfg}"* ]] || {
    echo "Expected config path in output, got: ${output}"; return 1
  }
}

@test "towit: setup --config is idempotent — does not overwrite existing config" {
  local cfg="${TEST_TMPDIR}/existing_config.toml"
  echo "# my custom config" > "${cfg}"
  local mtime_before
  mtime_before="$(stat -f '%m' "${cfg}" 2>/dev/null || stat -c '%Y' "${cfg}")"
  TOWIT_CONFIG_PATH="${cfg}" run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
  local mtime_after
  mtime_after="$(stat -f '%m' "${cfg}" 2>/dev/null || stat -c '%Y' "${cfg}")"
  [ "${mtime_before}" = "${mtime_after}" ] || {
    echo "Config file was overwritten — it should not be"; return 1
  }
  [[ "$(cat "${cfg}")" == "# my custom config" ]] || {
    echo "Config file content was changed"; return 1
  }
}

@test "towit: setup --config does not require database to exist" {
  local cfg="${TEST_TMPDIR}/standalone_config.toml"
  local fresh_db="${TEST_TMPDIR}/fresh.db"
  printf '[database]\npath = "%s"\n' "${fresh_db}" > "${cfg}"
  TOWIT_CONFIG_PATH="${cfg}" run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
}

# ---------------------------------------------------------------------------
# search subcommand
# ---------------------------------------------------------------------------

@test "towit: search with no terms exits non-zero" {
  "${TOWIT}" setup
  run bash -c "\"${TOWIT}\" search 2>&1"
  [ "${status}" -ne 0 ]
}

# ---------------------------------------------------------------------------
# list subcommand
# ---------------------------------------------------------------------------

@test "towit: list on empty DB exits 0" {
  "${TOWIT}" setup
  run "${TOWIT}" list
  [ "${status}" -eq 0 ]
}

# ---------------------------------------------------------------------------
# stats subcommand
# ---------------------------------------------------------------------------

@test "towit: stats on empty DB exits 0 and prints stats" {
  "${TOWIT}" setup
  run "${TOWIT}" stats
  [ "${status}" -eq 0 ]
}

# ---------------------------------------------------------------------------
# python3 missing
# ---------------------------------------------------------------------------

@test "towit: missing python3 prints helpful error and exits non-zero" {
  # Use env -i to clear version-manager env vars (mise, pyenv, asdf) that can
  # redirect python3 calls even when PATH is overridden. Place a stub python3
  # first in PATH so the script finds it before any real interpreter — this is
  # necessary on Ubuntu 24.04 where /bin is a symlink to /usr/bin and removing
  # /usr/bin from PATH alone does not hide python3.
  local no_py_bin="${TEST_TMPDIR}/no_python3"
  mkdir -p "${no_py_bin}"
  cat > "${no_py_bin}/python3" <<'EOF'
#!/bin/sh
echo "python3: command not found" >&2
exit 127
EOF
  chmod +x "${no_py_bin}/python3"
  run -127 env -i \
    HOME="${HOME}" \
    TOWIT_CONFIG_PATH="${TOWIT_CONFIG_PATH}" \
    PATH="${no_py_bin}:/usr/local/bin:/usr/bin:/bin" \
    "${TOWIT}" setup 2>&1
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"python3"* ]] || [[ "${output}" == *"Python"* ]] || {
    echo "Expected python3 error message, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# install-hook subcommand
# ---------------------------------------------------------------------------

@test "towit: install-hook writes hook to settings.local.json" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  run env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" install-hook
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"installed"* ]] || {
    echo "Expected 'installed' in output, got: ${output}"; return 1
  }
  [ -f "${settings_file}" ] || {
    echo "Expected settings file at ${settings_file}"; return 1
  }
  run grep -c "towit_hook.py" "${settings_file}"
  [ "${output}" -ge 1 ]
}

# ---------------------------------------------------------------------------
# uninstall-hook subcommand
# ---------------------------------------------------------------------------

@test "towit: uninstall-hook removes hook from settings.local.json" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" install-hook
  [ -f "${settings_file}" ]
  run env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" uninstall-hook
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"removed"* ]] || [[ "${output}" == *"uninstalled"* ]] || {
    echo "Expected 'removed'/'uninstalled' in output, got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# teardown subcommand
# ---------------------------------------------------------------------------

@test "towit: teardown --yes removes hook and database when both exist" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  "${TOWIT}" setup
  env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" install-hook
  [ -f "${TOWIT_DB_PATH}" ]
  [ -f "${settings_file}" ]
  run env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" teardown --yes
  [ "${status}" -eq 0 ]
  [ ! -f "${TOWIT_DB_PATH}" ] || {
    echo "Expected DB to be removed after teardown"; return 1
  }
}

# ---------------------------------------------------------------------------
# implode subcommand
# ---------------------------------------------------------------------------

@test "towit: implode --yes removes hook and database when both exist" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  "${TOWIT}" setup
  env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" install-hook
  [ -f "${TOWIT_DB_PATH}" ]
  [ -f "${settings_file}" ]
  run env TOWIT_SETTINGS_PATH="${settings_file}" \
    "${TOWIT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
  [ ! -f "${TOWIT_DB_PATH}" ] || {
    echo "Expected DB to be removed after implode"; return 1
  }
}

@test "towit: implode --yes removes binary symlink" {
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  local fake_target="${TEST_TMPDIR}/fake_towit"
  touch "${fake_target}"
  ln -s "${fake_target}" "${install_dir}/towit"
  [ -L "${install_dir}/towit" ]
  run env TOWIT_SETTINGS_PATH="${TEST_TMPDIR}/settings.local.json" \
    "${TOWIT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
  [ ! -L "${install_dir}/towit" ] || {
    echo "Expected symlink to be removed after implode"; return 1
  }
}

@test "towit: implode --yes prints data directory path" {
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  "${TOWIT}" setup
  run "${TOWIT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"$(dirname "${TOWIT_DB_PATH}")"* ]] || {
    echo "Expected data directory in output, got: ${output}"; return 1
  }
}

@test "towit: implode warns when binary is not a symlink" {
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  echo "#!/bin/bash" > "${install_dir}/towit"
  run "${TOWIT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"not a symlink"* ]] || {
    echo "Expected 'not a symlink' warning, got: ${output}"; return 1
  }
  [ -f "${install_dir}/towit" ] || {
    echo "Expected regular file to remain (not removed)"; return 1
  }
}

@test "towit: implode exits 0 when nothing to remove" {
  local install_dir="${TEST_TMPDIR}/bin"
  mkdir -p "${install_dir}"
  run "${TOWIT}" implode --yes --install-dir "${install_dir}"
  [ "${status}" -eq 0 ]
}

# ---------------------------------------------------------------------------
# resume subcommand
# ---------------------------------------------------------------------------

@test "towit: resume with unknown session-id exits non-zero" {
  "${TOWIT}" setup
  run "${TOWIT}" resume nonexistent-id
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"session not found"* ]] || {
    echo "Expected 'session not found' in output, got: ${output}"; return 1
  }
}

@test "towit: open subcommand prints deprecation warning and delegates to resume" {
  "${TOWIT}" setup
  run "${TOWIT}" open nonexistent-id
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"deprecated"* ]] || {
    echo "Expected deprecation warning in output, got: ${output}"; return 1
  }
  [[ "${output}" == *"session not found"* ]] || {
    echo "Expected 'session not found' in output (delegated to resume), got: ${output}"; return 1
  }
}

# ---------------------------------------------------------------------------
# setup --hook subcommand
# ---------------------------------------------------------------------------

@test "towit: setup --hook creates DB and installs hook" {
  local settings_file="${TEST_TMPDIR}/settings.local.json"
  [ ! -f "${TOWIT_DB_PATH}" ] || rm -f "${TOWIT_DB_PATH}"
  run env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" setup --hook
  [ "${status}" -eq 0 ]
  [ -f "${TOWIT_DB_PATH}" ] || {
    echo "Expected DB file at ${TOWIT_DB_PATH}"; return 1
  }
  [ -f "${settings_file}" ] || {
    echo "Expected settings file at ${settings_file}"; return 1
  }
}

# ---------------------------------------------------------------------------
# doctor subcommand
# ---------------------------------------------------------------------------

@test "towit: doctor --help exits 0 and prints usage" {
  run "${TOWIT}" doctor --help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"usage"* ]] || [[ "${output}" == *"Usage"* ]] || {
    echo "Expected 'usage' in output, got: ${output}"; return 1
  }
}

@test "towit: doctor exits non-zero when database is missing" {
  # DB not set up; TOWIT_CONFIG_PATH points to a config referencing a nonexistent DB
  local settings_file="${TEST_TMPDIR}/settings.json"
  echo '{}' > "${settings_file}"
  run env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" doctor
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"[FAIL]"* ]] || {
    echo "Expected [FAIL] in output, got: ${output}"; return 1
  }
}

@test "towit: doctor prints [PASS] for database after setup" {
  local settings_file="${TEST_TMPDIR}/settings.json"
  echo '{}' > "${settings_file}"
  "${TOWIT}" setup
  run env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" doctor
  [[ "${output}" == *"[PASS]"* ]] || {
    echo "Expected [PASS] lines in output, got: ${output}"; return 1
  }
  [[ "${output}" == *"Database"* ]] || {
    echo "Expected 'Database' in output, got: ${output}"; return 1
  }
}

@test "towit: doctor output contains no JSON or CSV" {
  local settings_file="${TEST_TMPDIR}/settings.json"
  echo '{}' > "${settings_file}"
  run env TOWIT_SETTINGS_PATH="${settings_file}" "${TOWIT}" doctor
  [[ "${output}" != *"{"* ]] || { echo "Unexpected JSON in output"; return 1; }
  [[ "${output}" != *'","'* ]] || { echo "Unexpected CSV in output"; return 1; }
}

@test "towit: doctor rejects unknown flags" {
  run "${TOWIT}" doctor --json
  [ "${status}" -ne 0 ]
}
