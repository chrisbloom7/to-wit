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

@test "test helper: every test points TOWIT_SETTINGS_PATH at a temp file, never the real settings" {
  # Commands such as implode, teardown and install-hook fall back to ~/.claude/settings.json
  # when this is unset, and would edit the developer's real Claude Code hooks.
  [ -n "${TOWIT_SETTINGS_PATH:-}" ] || {
    echo "TOWIT_SETTINGS_PATH is not set by the test setup"; return 1
  }
  [[ "${TOWIT_SETTINGS_PATH}" == "${TEST_TMPDIR}"/* ]] || {
    echo "TOWIT_SETTINGS_PATH is outside TEST_TMPDIR: ${TOWIT_SETTINGS_PATH}"; return 1
  }
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
# version subcommand
# ---------------------------------------------------------------------------

# A copy of bin/towit in a throwaway tree, so a test controls libexec/towit/VERSION.
_version_tree() {
  local tree="${TEST_TMPDIR}/version-tree"
  mkdir -p "${tree}/bin" "${tree}/libexec/towit"
  cp "${PROJECT_ROOT}/bin/towit" "${tree}/bin/towit"
  echo "${tree}"
}

@test "towit: version prints the version from libexec/towit/VERSION" {
  local expected
  expected="towit $(tr -d '[:space:]' < "${PROJECT_ROOT}/libexec/towit/VERSION")"
  run "${TOWIT}" version
  [ "${status}" -eq 0 ]
  [ "${output}" = "${expected}" ]
  [[ "${output}" =~ ^towit\ [0-9]+\.[0-9]+\.[0-9]+$ ]]
}

@test "towit: --version and -v print the same as version" {
  run "${TOWIT}" version
  local expected="${output}"
  run "${TOWIT}" --version
  [ "${status}" -eq 0 ]
  [ "${output}" = "${expected}" ]
  run "${TOWIT}" -v
  [ "${status}" -eq 0 ]
  [ "${output}" = "${expected}" ]
}

@test "towit: version trims whitespace around the stored version" {
  local tree; tree="$(_version_tree)"
  printf '  1.2.3  \n\n' > "${tree}/libexec/towit/VERSION"
  run "${tree}/bin/towit" version
  [ "${status}" -eq 0 ]
  [ "${output}" = "towit 1.2.3" ]
}

@test "towit: version prints an unusual version string verbatim" {
  local tree; tree="$(_version_tree)"
  echo "1.2.3-rc.1+build.5" > "${tree}/libexec/towit/VERSION"
  run "${tree}/bin/towit" version
  [ "${status}" -eq 0 ]
  [ "${output}" = "towit 1.2.3-rc.1+build.5" ]
}

@test "towit: version prints 'unknown' when the VERSION file is missing" {
  local tree; tree="$(_version_tree)"
  run "${tree}/bin/towit" version
  [ "${status}" -eq 0 ]
  [ "${output}" = "towit unknown" ]
}

@test "towit: version prints 'unknown' when the VERSION file is empty" {
  local tree; tree="$(_version_tree)"
  : > "${tree}/libexec/towit/VERSION"
  run "${tree}/bin/towit" version
  [ "${status}" -eq 0 ]
  [ "${output}" = "towit unknown" ]
}

@test "towit: version prints 'unknown' when the VERSION file is unreadable" {
  [ "$(id -u)" -ne 0 ] || skip "root can read any file"
  local tree; tree="$(_version_tree)"
  echo "1.2.3" > "${tree}/libexec/towit/VERSION"
  chmod 000 "${tree}/libexec/towit/VERSION"
  run "${tree}/bin/towit" version
  [ "${status}" -eq 0 ]
  [ "${output}" = "towit unknown" ]
}

@test "towit: version needs no database" {
  [ ! -e "${TOWIT_DB_PATH}" ]
  run "${TOWIT}" version
  [ "${status}" -eq 0 ]
  [ ! -e "${TOWIT_DB_PATH}" ]
}

@test "towit: help lists the version subcommand and its aliases" {
  run "${TOWIT}" help
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"version"*"--version"*"-v"* ]] || {
    echo "Expected version, --version and -v in help, got: ${output}"; return 1
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
  mtime_before="$(stat -c '%Y' "${cfg}" 2>/dev/null || stat -f '%m' "${cfg}")"
  TOWIT_CONFIG_PATH="${cfg}" run "${TOWIT}" setup --config
  [ "${status}" -eq 0 ]
  local mtime_after
  mtime_after="$(stat -c '%Y' "${cfg}" 2>/dev/null || stat -f '%m' "${cfg}")"
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
# setup --full / --hook config handling
# ---------------------------------------------------------------------------

_setup_isolated_home() {
  # Pin the real python3 first: a shimmed python3 (mise/asdf) breaks under a fake HOME
  local real_py
  real_py="$(python3 -c 'import sys; print(sys.executable)')"
  ln -sf "${real_py}" "${TEST_TMPDIR}/mock_bin/python3"
  mkdir -p "${TEST_TMPDIR}/home/.claude/projects"
  export HOME="${TEST_TMPDIR}/home"
  export TOWIT_SETTINGS_PATH="${TEST_TMPDIR}/settings.json"
  export TOWIT_CONFIG_PATH="${TEST_TMPDIR}/fresh_config.toml"
}

@test "towit: setup --full generates the config file" {
  _setup_isolated_home
  run "${TOWIT}" setup --full
  [ "${status}" -eq 0 ] || { echo "status=${status}: ${output}"; return 1; }
  [ -f "${TOWIT_CONFIG_PATH}" ] || {
    echo "Expected config at ${TOWIT_CONFIG_PATH}; output: ${output}"; return 1
  }
  local mode
  mode="$(stat -c '%a' "${TOWIT_CONFIG_PATH}" 2>/dev/null || stat -f '%Lp' "${TOWIT_CONFIG_PATH}")"
  [ "${mode}" = "600" ] || { echo "Expected mode 600, got ${mode}"; return 1; }
  [[ "${output}" == *"Config file created at"* ]] || { echo "${output}"; return 1; }
  [[ "${output}" == *"Database initialized"* ]] || { echo "${output}"; return 1; }
  [[ "${output}" == *"hooks installed"* ]] || { echo "${output}"; return 1; }
  [[ "${output}" == *"No JSONL files found"* || "${output}" == *"Backfill"* ]] || {
    echo "${output}"; return 1
  }
}

@test "towit: setup --full leaves an existing config untouched" {
  _setup_isolated_home
  printf '# sentinel config\n' > "${TOWIT_CONFIG_PATH}"
  run "${TOWIT}" setup --full
  [ "${status}" -eq 0 ] || { echo "status=${status}: ${output}"; return 1; }
  [ "$(cat "${TOWIT_CONFIG_PATH}")" = "# sentinel config" ] || {
    echo "Config was modified"; return 1
  }
  [[ "${output}" == *"Config file already exists"* ]] || { echo "${output}"; return 1; }
}

@test "towit: setup --hook does not generate a config file" {
  _setup_isolated_home
  run "${TOWIT}" setup --hook
  [ "${status}" -eq 0 ] || { echo "status=${status}: ${output}"; return 1; }
  [ ! -e "${TOWIT_CONFIG_PATH}" ] || { echo "Config unexpectedly created"; return 1; }
}

@test "towit: setup with no flags does not generate a config file" {
  _setup_isolated_home
  run "${TOWIT}" setup
  [ "${status}" -eq 0 ] || { echo "status=${status}: ${output}"; return 1; }
  [ ! -e "${TOWIT_CONFIG_PATH}" ] || { echo "Config unexpectedly created"; return 1; }
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
# TOWIT_PYTHON interpreter override
# ---------------------------------------------------------------------------

@test "towit: TOWIT_PYTHON interpreter is used for helper invocations" {
  local stub="${TEST_TMPDIR}/stub-python"
  local record="${TEST_TMPDIR}/stub-argv"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$@" > "%s"\nexit 0\n' "${record}" > "${stub}"
  chmod +x "${stub}"
  "${TOWIT}" setup

  TOWIT_PYTHON="${stub}" run "${TOWIT}" stats
  [ "${status}" -eq 0 ]
  [ -f "${record}" ] || { echo "Stub interpreter was never invoked. Output: ${output}"; return 1; }
  [[ "$(head -n 1 "${record}")" == */libexec/towit/towit_stats.py ]] || {
    echo "Expected helper path as first argument, got: $(cat "${record}")"; return 1
  }
}

@test "towit: TOWIT_PYTHON pointing at a nonexistent interpreter exits non-zero naming TOWIT_PYTHON" {
  "${TOWIT}" setup
  TOWIT_PYTHON="${TEST_TMPDIR}/no-such-python" run "${TOWIT}" stats
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"TOWIT_PYTHON"* ]] || {
    echo "Expected TOWIT_PYTHON in error output, got: ${output}"; return 1
  }
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

# ---------------------------------------------------------------------------
# backfill subcommand (archive ingestion)
# ---------------------------------------------------------------------------

@test "towit: backfill with indexing disabled archives sessions without calling Claude" {
  # Pin the real python3 first: a shimmed python3 (mise/asdf) breaks under a fake HOME
  ln -sf "$(python3 -c 'import sys; print(sys.executable)')" "${TEST_TMPDIR}/mock_bin/python3"
  export HOME="${TEST_TMPDIR}/home"
  mkdir -p "${HOME}"
  printf '[indexing]\nenabled = false\n' >> "${TOWIT_CONFIG_PATH}"
  "${TOWIT}" setup
  local sessions="${TEST_TMPDIR}/sessions"
  write_fixture_session "${sessions}" "session-aaa-0001"
  write_fixture_session "${sessions}" "session-bbb-0002"

  run "${TOWIT}" backfill --folder "${sessions}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"-> ingested"* ]] || { echo "Expected ingest status, got: ${output}"; return 1; }
  [[ "${output}" == *"Archived: 2"* ]] || { echo "Expected 'Archived: 2', got: ${output}"; return 1; }

  run "${TOWIT}" stats
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Total conversations   : 2"* ]] || { echo "Expected 2 conversations in stats, got: ${output}"; return 1; }
}

# ---------------------------------------------------------------------------
# forget subcommand
# ---------------------------------------------------------------------------

@test "towit: forget is not undone by backfill or the SessionStart catch-up" {
  ln -sf "$(python3 -c 'import sys; print(sys.executable)')" "${TEST_TMPDIR}/mock_bin/python3"
  export HOME="${TEST_TMPDIR}/home"
  mkdir -p "${HOME}"
  printf '[indexing]\nenabled = false\n' >> "${TOWIT_CONFIG_PATH}"
  "${TOWIT}" setup
  local sessions="${HOME}/.claude/projects/-work-proj"
  write_fixture_session "${sessions}" "session-aaa-0001"
  run "${TOWIT}" backfill --folder "${sessions}"
  [ "${status}" -eq 0 ]
  run "${TOWIT}" search concurrency
  [[ "${output}" == *"session-aaa-0001"* ]] || { echo "Expected a hit before forget, got: ${output}"; return 1; }

  run "${TOWIT}" forget session-aaa-0001 --yes
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Forgot 1 conversation(s)."* ]]
  [ -f "${sessions}/session-aaa-0001.jsonl" ]

  run "${TOWIT}" backfill --folder "${sessions}"
  [ "${status}" -eq 0 ]
  run python3 "${HELPERS_DIR}/towit_ingest.py" --catch-up
  [ "${status}" -eq 0 ]

  run "${TOWIT}" search concurrency
  [[ "${output}" != *"session-aaa-0001"* ]] || { echo "Forgotten session resurfaced: ${output}"; return 1; }
  run "${TOWIT}" show session-aaa-0001
  [ "${status}" -eq 1 ]
  run "${TOWIT}" list
  [[ "${output}" != *"session-aaa-0001"* ]] || { echo "Forgotten session listed: ${output}"; return 1; }
}

@test "towit: forget --folder forgets every session in that working directory only" {
  ln -sf "$(python3 -c 'import sys; print(sys.executable)')" "${TEST_TMPDIR}/mock_bin/python3"
  export HOME="${TEST_TMPDIR}/home"
  mkdir -p "${HOME}"
  printf '[indexing]\nenabled = false\n' >> "${TOWIT_CONFIG_PATH}"
  "${TOWIT}" setup
  local sessions="${TEST_TMPDIR}/sessions"
  write_fixture_session "${sessions}" "session-aaa-0001"
  write_fixture_session "${sessions}" "session-bbb-0002"
  write_fixture_session "${sessions}" "session-ccc-0003"
  sed -i.bak 's#/work/proj#/work/other#g' "${sessions}/session-ccc-0003.jsonl"
  rm "${sessions}"/*.bak
  run "${TOWIT}" backfill --folder "${sessions}"
  [ "${status}" -eq 0 ]

  run "${TOWIT}" forget --folder /work/proj --yes
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Forgot 2 conversation(s)."* ]] || { echo "got: ${output}"; return 1; }

  run "${TOWIT}" show session-aaa-0001
  [ "${status}" -eq 1 ]
  run "${TOWIT}" show session-bbb-0002
  [ "${status}" -eq 1 ]
  run "${TOWIT}" show session-ccc-0003
  [ "${status}" -eq 0 ]
}

@test "towit: forget with no selector exits 2 and shows usage" {
  run "${TOWIT}" forget --yes
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"usage"* ]]
}

# ---------------------------------------------------------------------------
# show subcommand
# ---------------------------------------------------------------------------

@test "towit: show prints archived messages after the transcript is deleted" {
  ln -sf "$(python3 -c 'import sys; print(sys.executable)')" "${TEST_TMPDIR}/mock_bin/python3"
  export HOME="${TEST_TMPDIR}/home"
  mkdir -p "${HOME}"
  printf '[indexing]\nenabled = false\n' >> "${TOWIT_CONFIG_PATH}"
  "${TOWIT}" setup
  local sessions="${TEST_TMPDIR}/sessions"
  write_fixture_session "${sessions}" "session-aaa-0001"
  run "${TOWIT}" backfill --folder "${sessions}"
  [ "${status}" -eq 0 ]
  rm "${sessions}/session-aaa-0001.jsonl"

  run "${TOWIT}" show session-aaa-0001
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"[0] user"* ]] || { echo "Expected seq 0, got: ${output}"; return 1; }
  [[ "${output}" == *"Readers do not block the writer."* ]] || { echo "Expected message text, got: ${output}"; return 1; }

  run "${TOWIT}" show session-aaa-0001 --around 1 --context 0
  [ "${status}" -eq 0 ]
  [[ "${output}" == *">> [1] assistant"* ]] || { echo "Expected marked seq 1, got: ${output}"; return 1; }
  [[ "${output}" != *"[0] user"* ]] || { echo "Unexpected seq 0, got: ${output}"; return 1; }

  run "${TOWIT}" show nonexistent-session
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"not found"* ]]
}

# ---------------------------------------------------------------------------
# end-to-end archive flow
# ---------------------------------------------------------------------------

# Assert the conversations and messages tables are both empty
_assert_archive_empty() {
  run python3 -c '
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
print(con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
      con.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
' "${TOWIT_DB_PATH}"
  [ "${status}" -eq 0 ]
  [ "${output}" = "0 0" ] || { echo "Expected empty conversations/messages, got: ${output}"; return 1; }
}

@test "towit: end-to-end archive flow (backfill, search, show, redaction, forget)" {
  # Indexing is disabled; a stub claude on PATH fails and leaves a marker if ever called
  printf '#!/usr/bin/env bash\ntouch "%s/claude_called"\nexit 1\n' "${TEST_TMPDIR}" > "${TEST_TMPDIR}/mock_bin/claude"
  chmod +x "${TEST_TMPDIR}/mock_bin/claude"
  ln -sf "$(python3 -c 'import sys; print(sys.executable)')" "${TEST_TMPDIR}/mock_bin/python3"
  export HOME="${TEST_TMPDIR}/home"
  mkdir -p "${HOME}"
  printf '[indexing]\nenabled = false\n' >> "${TOWIT_CONFIG_PATH}"
  "${TOWIT}" setup

  # Synthetic fixture session with a fake secret assembled from pieces
  local fake_secret="AKIA""ABCDEFGHIJKLMNOP"
  local sessions="${TEST_TMPDIR}/sessions"
  mkdir -p "${sessions}"
  cat > "${sessions}/session-e2e-0001.jsonl" <<JSONL
{"type":"user","timestamp":"2026-01-15T10:00:00Z","cwd":"/work/proj","sessionId":"session-e2e-0001","message":{"role":"user","content":"Remember the zephyr marker for later. My key is ${fake_secret} ok?"}}
{"type":"assistant","timestamp":"2026-01-15T10:00:05Z","cwd":"/work/proj","sessionId":"session-e2e-0001","message":{"role":"assistant","content":[{"type":"text","text":"Noted, the zephyr marker is saved."}]}}
{"type":"user","timestamp":"2026-01-15T10:01:00Z","cwd":"/work/proj","sessionId":"session-e2e-0001","message":{"role":"user","content":"Thanks, that is all."}}
{"type":"assistant","timestamp":"2026-01-15T10:01:05Z","cwd":"/work/proj","sessionId":"session-e2e-0001","message":{"role":"assistant","content":[{"type":"text","text":"You are welcome."}]}}
JSONL

  run "${TOWIT}" backfill --folder "${sessions}"
  [ "${status}" -eq 0 ]

  run "${TOWIT}" search "zephyr marker"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"session-e2e-0001"* ]] || { echo "Expected a hit, got: ${output}"; return 1; }
  [[ "${output}" == *"zephyr"* ]] || { echo "Expected a snippet, got: ${output}"; return 1; }

  run "${TOWIT}" show session-e2e-0001
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"zephyr marker"* ]] || { echo "Expected message text, got: ${output}"; return 1; }
  [[ "${output}" != *"${fake_secret}"* ]] || { echo "Secret leaked via show"; return 1; }

  # Stored text is redacted: marker present, secret absent
  run python3 -c '
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
print("\n".join(r[0] for r in con.execute("SELECT text FROM messages")))
' "${TOWIT_DB_PATH}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"[REDACTED:"* ]] || { echo "Expected redaction marker, got: ${output}"; return 1; }
  [[ "${output}" != *"${fake_secret}"* ]] || { echo "Secret stored in DB"; return 1; }

  run "${TOWIT}" forget session-e2e-0001 --yes
  [ "${status}" -eq 0 ]

  run "${TOWIT}" search "zephyr marker"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"No conversations found."* ]] || { echo "Forgotten session still found: ${output}"; return 1; }
  _assert_archive_empty

  run "${TOWIT}" backfill --folder "${sessions}"
  [ "${status}" -eq 0 ]
  run "${TOWIT}" search "zephyr marker"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"No conversations found."* ]] || { echo "Backfill restored forgotten session: ${output}"; return 1; }
  _assert_archive_empty
  [ ! -e "${TEST_TMPDIR}/claude_called" ] || { echo "claude was invoked"; return 1; }
}

@test "towit: search matches terms spread across messages and keeps the any-term retry" {
  # Indexing is disabled; a stub claude on PATH fails and leaves a marker if ever called
  printf '#!/usr/bin/env bash\ntouch "%s/claude_called"\nexit 1\n' "${TEST_TMPDIR}" > "${TEST_TMPDIR}/mock_bin/claude"
  chmod +x "${TEST_TMPDIR}/mock_bin/claude"
  ln -sf "$(python3 -c 'import sys; print(sys.executable)')" "${TEST_TMPDIR}/mock_bin/python3"
  export HOME="${TEST_TMPDIR}/home"
  mkdir -p "${HOME}"
  printf '[indexing]\nenabled = false\n' >> "${TOWIT_CONFIG_PATH}"
  "${TOWIT}" setup

  local sessions="${TEST_TMPDIR}/sessions"
  mkdir -p "${sessions}"
  # 0001: redis and timeout live in different messages; 0002: redis only
  cat > "${sessions}/session-rank-0001.jsonl" <<'JSONL'
{"type":"user","timestamp":"2026-01-15T10:00:00Z","cwd":"/work/proj","sessionId":"session-rank-0001","message":{"role":"user","content":"Our redis cache keeps dropping keys."}}
{"type":"assistant","timestamp":"2026-01-15T10:00:05Z","cwd":"/work/proj","sessionId":"session-rank-0001","message":{"role":"assistant","content":[{"type":"text","text":"Check the eviction policy first."}]}}
{"type":"user","timestamp":"2026-01-15T10:01:00Z","cwd":"/work/proj","sessionId":"session-rank-0001","message":{"role":"user","content":"Now the client reports a timeout on connect."}}
{"type":"assistant","timestamp":"2026-01-15T10:01:05Z","cwd":"/work/proj","sessionId":"session-rank-0001","message":{"role":"assistant","content":[{"type":"text","text":"Raise the connect limit."}]}}
JSONL
  cat > "${sessions}/session-rank-0002.jsonl" <<'JSONL'
{"type":"user","timestamp":"2026-01-16T10:00:00Z","cwd":"/work/proj","sessionId":"session-rank-0002","message":{"role":"user","content":"How do I install redis locally?"}}
{"type":"assistant","timestamp":"2026-01-16T10:00:05Z","cwd":"/work/proj","sessionId":"session-rank-0002","message":{"role":"assistant","content":[{"type":"text","text":"Use your package manager."}]}}
{"type":"user","timestamp":"2026-01-16T10:01:00Z","cwd":"/work/proj","sessionId":"session-rank-0002","message":{"role":"user","content":"Thanks, that worked."}}
{"type":"assistant","timestamp":"2026-01-16T10:01:05Z","cwd":"/work/proj","sessionId":"session-rank-0002","message":{"role":"assistant","content":[{"type":"text","text":"Glad to help."}]}}
JSONL

  run "${TOWIT}" backfill --folder "${sessions}"
  [ "${status}" -eq 0 ]

  # Every term appears somewhere in 0001 (different messages), so only it matches
  run "${TOWIT}" search redis timeout --format json
  [ "${status}" -eq 0 ]
  run python3 -c '
import json, sys
rows = json.loads(sys.argv[1])
print(",".join(r["id"] for r in rows), all("seq" in r and "score" in r for r in rows))
' "${output}"
  [ "${status}" -eq 0 ]
  [ "${output}" = "session-rank-0001 True" ] || { echo "Expected only session-rank-0001 with seq/score, got: ${output}"; return 1; }

  # No conversation has every term, so the any-term retry notice goes to stderr
  run --separate-stderr "${TOWIT}" search redis zzzmissing
  [ "${status}" -eq 0 ]
  [[ "${stderr}" == *"No results for all terms; showing results matching any term."* ]] || { echo "Expected retry notice, got stderr: ${stderr}"; return 1; }
  [[ "${output}" == *"session-rank-0002"* ]] || { echo "Expected session-rank-0002, got: ${output}"; return 1; }
  [[ "${output}" == *"session-rank-0001"* ]] || { echo "Expected session-rank-0001, got: ${output}"; return 1; }
  [ ! -e "${TEST_TMPDIR}/claude_called" ] || { echo "claude was invoked"; return 1; }
}

@test "towit: setup migrates a v0.8.2 database and keeps rows searchable by metadata" {
  ln -sf "$(python3 -c 'import sys; print(sys.executable)')" "${TEST_TMPDIR}/mock_bin/python3"
  export HOME="${TEST_TMPDIR}/home"
  mkdir -p "${HOME}"

  # Hand-written v0.8.2 schema (no archive tables) with one existing row
  python3 - "${TOWIT_DB_PATH}" <<'PYEOF'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE conversations (
  id TEXT PRIMARY KEY, folder TEXT NOT NULL, cwd TEXT, started_at TEXT,
  last_active TEXT, title TEXT, summary TEXT, message_count INTEGER,
  indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL COLLATE NOCASE
);
CREATE TABLE conversation_topics (
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  PRIMARY KEY (conversation_id, topic_id)
);
CREATE TABLE keywords (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL COLLATE NOCASE
);
CREATE TABLE conversation_keywords (
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
  PRIMARY KEY (conversation_id, keyword_id)
);
INSERT INTO conversations (id, folder, cwd, started_at, last_active, title, summary, message_count)
VALUES ('legacy-session-0001', '-work-legacy', '/work/legacy', '2025-12-01T10:00:00Z',
        '2025-12-01T11:00:00Z', 'Quokka migration notes', 'Discussed marsupial schemas.', 4);
INSERT INTO topics (name) VALUES ('legacy-topic');
INSERT INTO conversation_topics VALUES ('legacy-session-0001', 1);
INSERT INTO keywords (name) VALUES ('marsupial');
INSERT INTO conversation_keywords VALUES ('legacy-session-0001', 1);
""")
con.commit()
PYEOF

  run "${TOWIT}" setup
  [ "${status}" -eq 0 ]

  # --only metadata searches keywords; --title/--summary add those fields
  run "${TOWIT}" search marsupial --only metadata
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"legacy-session-0001"* ]] || { echo "Expected keyword hit, got: ${output}"; return 1; }

  run "${TOWIT}" search quokka --only metadata --title
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"legacy-session-0001"* ]] || { echo "Expected title hit, got: ${output}"; return 1; }

  run "${TOWIT}" search quokka
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"legacy-session-0001"* ]] || { echo "Expected default-scope hit, got: ${output}"; return 1; }

  run "${TOWIT}" stats
  [ "${status}" -eq 0 ]

  # Archive schema was added and the legacy row is marked not archived
  run python3 - "${TOWIT_DB_PATH}" "${HELPERS_DIR}" <<'PYEOF'
import sqlite3, sys
sys.path.insert(0, sys.argv[2])
from towit_db import SCHEMA_VERSION
con = sqlite3.connect(sys.argv[1])
names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
missing = {"messages", "messages_fts", "forgotten", "meta"} - names
assert not missing, "missing tables: %s" % missing
version = con.execute("PRAGMA user_version").fetchone()[0]
assert version == SCHEMA_VERSION, "user_version %s != %s" % (version, SCHEMA_VERSION)
archived = con.execute(
    "SELECT archived FROM conversations WHERE id = 'legacy-session-0001'").fetchone()[0]
assert archived == 0, "archived = %s" % archived
print("ok")
PYEOF
  [ "${status}" -eq 0 ] || { echo "Migration assertions failed: ${output}"; return 1; }
}
