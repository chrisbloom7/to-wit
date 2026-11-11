bats_require_minimum_version 1.5.0

load "../test_helper"

# Tests for .claude/skills/release-towit/bump-tap-formula
#   bump-tap-formula <version> [--tap-dir <dir>] [--tarball <file>]
# Everything runs against temp dirs; curl is always a stub. No network.

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

write_formula() {
  cat > "${TAP}/Formula/towit.rb" <<'FORMULA'
class Towit < Formula
  desc "Searchable archive of your Claude Code conversations"
  homepage "https://github.com/chrisbloom7/to-wit"
  url "https://github.com/chrisbloom7/to-wit/archive/refs/tags/v0.9.2.tar.gz"
  sha256 "4b749a319fd31c368b416c34dad42a9d3872f10beef979df6d4fdba387df0ce7"
  license "GPL-3.0-only"

  depends_on "python@3.15"

  def install
    libexec.install "bin", "libexec"
    (bin/"towit").write_env_script libexec/"bin/towit",
                                   TOWIT_PYTHON: formula_opt_bin("python@3.15")/"python3.15"
  end

  def caveats
    <<~EOS
      Set up the database and the Claude Code hooks with:
        towit setup --hook

      Claude Code is optional: without it, To Wit archives and searches
      conversations but cannot generate titles, summaries, or topics. Install it with:
        brew install --cask claude-code
    EOS
  end

  test do
    ENV["HOME"] = testpath
    assert_match "To Wit", shell_output("#{bin}/towit help")
    system bin/"towit", "setup"
    assert_match "SQLite FTS5 is available", shell_output("#{bin}/towit doctor 2>&1; true")
    assert_match "Total conversations", shell_output("#{bin}/towit stats")
  end
end
FORMULA
}

# Commit the current formula so `git status` reflects only the script's edits.
commit_tap() {
  git -C "${TAP}" add -A
  git -C "${TAP}" -c user.name=t -c user.email=t@example.com commit -q -m fixture
  HEAD_BEFORE="$(git -C "${TAP}" rev-parse HEAD)"
  cp "${TAP}/Formula/towit.rb" "${ORIG}"
}

# Formula contents with the top-level url/sha256 lines removed.
other_lines() {
  grep -v -e '^  url "' -e '^  sha256 "' "$1"
}

setup() {
  _setup_common
  SCRIPT="${PROJECT_ROOT}/.claude/skills/release-towit/bump-tap-formula"
  TAP="${TEST_TMPDIR}/tap"
  ORIG="${TEST_TMPDIR}/towit.rb.orig"
  mkdir -p "${TAP}/Formula"
  git -C "${TAP}" init -q
  write_formula
  commit_tap

  # Fixture tarballs (distinct contents => distinct hashes)
  mkdir -p "${TEST_TMPDIR}/src1" "${TEST_TMPDIR}/src2"
  echo "one" > "${TEST_TMPDIR}/src1/file"
  echo "two" > "${TEST_TMPDIR}/src2/file"
  TARBALL="${TEST_TMPDIR}/v1.tar.gz"
  TARBALL2="${TEST_TMPDIR}/v2.tar.gz"
  tar czf "${TARBALL}" -C "${TEST_TMPDIR}/src1" file
  tar czf "${TARBALL2}" -C "${TEST_TMPDIR}/src2" file
  SHA="$(sha256_of "${TARBALL}")"
  SHA2="$(sha256_of "${TARBALL2}")"

  CURL_LOG="${TEST_TMPDIR}/curl.log"
  export CURL_LOG
}

teardown() {
  _teardown_common
}

# Install a stub curl first in PATH. $1 = "ok" (serves $FIXTURE_TARBALL) or "fail".
install_curl_stub() {
  local mode="$1"
  export FIXTURE_TARBALL="${TARBALL}"
  cat > "${TEST_TMPDIR}/mock_bin/curl" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "\${CURL_LOG}"
if [ "${mode}" = "fail" ]; then
  echo "curl: (22) stub failure" >&2
  exit 22
fi
out=""
while [ \$# -gt 0 ]; do
  case "\$1" in
    -o|--output) out="\$2"; shift 2 ;;
    -o*) out="\${1#-o}"; shift ;;
    --output=*) out="\${1#--output=}"; shift ;;
    *) shift ;;
  esac
done
if [ -n "\${out}" ] && [ "\${out}" != "-" ]; then
  cp "\${FIXTURE_TARBALL}" "\${out}"
else
  cat "\${FIXTURE_TARBALL}"
fi
EOF
  chmod +x "${TEST_TMPDIR}/mock_bin/curl"
}

assert_formula_unchanged() {
  cmp "${ORIG}" "${TAP}/Formula/towit.rb"
  [ -z "$(git -C "${TAP}" status --porcelain)" ]
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@test "bump-tap-formula: script exists and is executable bash with strict mode" {
  [ -x "${SCRIPT}" ]
  [[ "$(head -n 1 "${SCRIPT}")" == "#!"*bash* ]]
  grep -q 'set -euo pipefail' "${SCRIPT}"
}

@test "bump-tap-formula: rewrites the url line with the new version and the sha256 line" {
  [ -x "${SCRIPT}" ]
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  grep -qx '  url "https://github.com/chrisbloom7/to-wit/archive/refs/tags/v0.9.3.tar.gz"' "${TAP}/Formula/towit.rb"
  grep -qx "  sha256 \"${SHA}\"" "${TAP}/Formula/towit.rb"
  [[ "${SHA}" =~ ^[0-9a-f]{64}$ ]]
  ! grep -q 'v0.9.2' "${TAP}/Formula/towit.rb"
  ! grep -q '4b749a31' "${TAP}/Formula/towit.rb"
}

@test "bump-tap-formula: leaves every other line byte-identical" {
  [ -x "${SCRIPT}" ]
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  # The file really changed...
  ! cmp -s "${ORIG}" "${TAP}/Formula/towit.rb"
  # ...but only in the url and sha256 lines.
  diff <(other_lines "${ORIG}") <(other_lines "${TAP}/Formula/towit.rb")
  [ "$(wc -l < "${ORIG}")" -eq "$(wc -l < "${TAP}/Formula/towit.rb")" ]
  # Line positions of url/sha256 are preserved.
  [ "$(grep -n '^  url "' "${ORIG}" | cut -d: -f1)" = "$(grep -n '^  url "' "${TAP}/Formula/towit.rb" | cut -d: -f1)" ]
  [ "$(grep -n '^  sha256 "' "${ORIG}" | cut -d: -f1)" = "$(grep -n '^  sha256 "' "${TAP}/Formula/towit.rb" | cut -d: -f1)" ]
}

@test "bump-tap-formula: prints a change summary mentioning the new version and sha256" {
  [ -x "${SCRIPT}" ]
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"0.9.3"* ]]
  [[ "${output}" == *"${SHA}"* ]]
}

@test "bump-tap-formula: is idempotent for the same version and tarball" {
  [ -x "${SCRIPT}" ]
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  cp "${TAP}/Formula/towit.rb" "${TEST_TMPDIR}/after_first"
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  cmp "${TEST_TMPDIR}/after_first" "${TAP}/Formula/towit.rb"
  grep -qx "  sha256 \"${SHA}\"" "${TAP}/Formula/towit.rb"
}

@test "bump-tap-formula: a later bump replaces the previously bumped values" {
  [ -x "${SCRIPT}" ]
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  run "${SCRIPT}" 1.0.0 --tap-dir "${TAP}" --tarball "${TARBALL2}"
  [ "${status}" -eq 0 ]
  grep -qx '  url "https://github.com/chrisbloom7/to-wit/archive/refs/tags/v1.0.0.tar.gz"' "${TAP}/Formula/towit.rb"
  grep -qx "  sha256 \"${SHA2}\"" "${TAP}/Formula/towit.rb"
  [ "$(grep -c '^  url "' "${TAP}/Formula/towit.rb")" -eq 1 ]
  [ "$(grep -c '^  sha256 "' "${TAP}/Formula/towit.rb")" -eq 1 ]
  diff <(other_lines "${ORIG}") <(other_lines "${TAP}/Formula/towit.rb")
}

@test "bump-tap-formula: does not run git or brew; only Formula/towit.rb is modified" {
  [ -x "${SCRIPT}" ]
  # Fail loudly if brew is invoked
  printf '#!/usr/bin/env bash\necho brew >> "%s/brew.log"\nexit 1\n' "${TEST_TMPDIR}" > "${TEST_TMPDIR}/mock_bin/brew"
  chmod +x "${TEST_TMPDIR}/mock_bin/brew"
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  [ "$(git -C "${TAP}" status --porcelain)" = " M Formula/towit.rb" ]
  [ "$(git -C "${TAP}" rev-parse HEAD)" = "${HEAD_BEFORE}" ]
  [ -z "$(git -C "${TAP}" diff --cached --name-only)" ]
  [ ! -e "${TEST_TMPDIR}/brew.log" ]
}

@test "bump-tap-formula: makes no curl call when --tarball is given" {
  [ -x "${SCRIPT}" ]
  install_curl_stub fail
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  [ ! -e "${CURL_LOG}" ]
  grep -qx "  sha256 \"${SHA}\"" "${TAP}/Formula/towit.rb"
}

@test "bump-tap-formula: downloads the exact tag tarball URL via curl when --tarball is absent" {
  [ -x "${SCRIPT}" ]
  install_curl_stub ok
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}"
  [ "${status}" -eq 0 ]
  [ -s "${CURL_LOG}" ]
  grep -qF 'https://github.com/chrisbloom7/to-wit/archive/refs/tags/v0.9.3.tar.gz' "${CURL_LOG}"
  grep -qx "  sha256 \"${SHA}\"" "${TAP}/Formula/towit.rb"
  grep -qx '  url "https://github.com/chrisbloom7/to-wit/archive/refs/tags/v0.9.3.tar.gz"' "${TAP}/Formula/towit.rb"
}

@test "bump-tap-formula: failing download exits non-zero and leaves the formula unchanged" {
  [ -x "${SCRIPT}" ]
  install_curl_stub fail
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}"
  [ "${status}" -ne 0 ]
  [ -s "${CURL_LOG}" ]
  assert_formula_unchanged
}

@test "bump-tap-formula: rejects malformed versions with a message on stderr and changes nothing" {
  [ -x "${SCRIPT}" ]
  local v
  for v in v1.2.3 1.2 1.2.3-rc1 1.2.3.4 "" abc "1.2.x"; do
    run --separate-stderr "${SCRIPT}" "${v}" --tap-dir "${TAP}" --tarball "${TARBALL}"
    [ "${status}" -ne 0 ]
    [[ "${stderr}" =~ [Vv]ersion|[Uu]sage ]]
    assert_formula_unchanged
  done
}

@test "bump-tap-formula: missing version argument fails with usage on stderr and changes nothing" {
  [ -x "${SCRIPT}" ]
  run --separate-stderr "${SCRIPT}" --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -ne 0 ]
  [[ "${stderr}" =~ [Uu]sage|[Vv]ersion ]]
  assert_formula_unchanged
}

@test "bump-tap-formula: errors clearly when the tap dir does not exist" {
  [ -x "${SCRIPT}" ]
  run --separate-stderr "${SCRIPT}" 0.9.3 --tap-dir "${TEST_TMPDIR}/nope" --tarball "${TARBALL}"
  [ "${status}" -ne 0 ]
  [[ "${stderr}" == *"nope"* ]]
  [ ! -e "${TEST_TMPDIR}/nope" ]
  assert_formula_unchanged
}

@test "bump-tap-formula: errors clearly when Formula/towit.rb is missing from the tap dir" {
  [ -x "${SCRIPT}" ]
  local empty="${TEST_TMPDIR}/empty_tap"
  mkdir -p "${empty}"
  run --separate-stderr "${SCRIPT}" 0.9.3 --tap-dir "${empty}" --tarball "${TARBALL}"
  [ "${status}" -ne 0 ]
  [[ "${stderr}" == *"towit.rb"* ]]
  [ ! -e "${empty}/Formula/towit.rb" ]
  assert_formula_unchanged
}

@test "bump-tap-formula: errors when the --tarball file does not exist and changes nothing" {
  [ -x "${SCRIPT}" ]
  run --separate-stderr "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TEST_TMPDIR}/missing.tar.gz"
  [ "${status}" -ne 0 ]
  [[ "${stderr}" == *"missing.tar.gz"* ]]
  assert_formula_unchanged
}

@test "bump-tap-formula: refuses a formula with no sha256 line" {
  [ -x "${SCRIPT}" ]
  grep -v '^  sha256 "' "${ORIG}" > "${TAP}/Formula/towit.rb"
  commit_tap
  run --separate-stderr "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -ne 0 ]
  [[ "${stderr}" == *"sha256"* ]]
  assert_formula_unchanged
}

@test "bump-tap-formula: refuses a formula with no url line" {
  [ -x "${SCRIPT}" ]
  grep -v '^  url "' "${ORIG}" > "${TAP}/Formula/towit.rb"
  commit_tap
  run --separate-stderr "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -ne 0 ]
  [[ "${stderr}" == *"url"* ]]
  assert_formula_unchanged
}

@test "bump-tap-formula: refuses a formula with a duplicated url line" {
  [ -x "${SCRIPT}" ]
  awk '{print} /^  url "/{print}' "${ORIG}" > "${TAP}/Formula/towit.rb"
  commit_tap
  run --separate-stderr "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -ne 0 ]
  [[ "${stderr}" == *"url"* ]]
  assert_formula_unchanged
}

@test "bump-tap-formula: refuses a formula with a duplicated sha256 line" {
  [ -x "${SCRIPT}" ]
  awk '{print} /^  sha256 "/{print}' "${ORIG}" > "${TAP}/Formula/towit.rb"
  commit_tap
  run --separate-stderr "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -ne 0 ]
  [[ "${stderr}" == *"sha256"* ]]
  assert_formula_unchanged
}

@test "bump-tap-formula: ignores deeper-indented url/sha256 lines inside the test block" {
  [ -x "${SCRIPT}" ]
  awk '
    /^    system bin\/"towit", "setup"/ {
      print
      print "    url \"https://example.com/other.tar.gz\""
      print "    sha256 \"0000000000000000000000000000000000000000000000000000000000000000\""
      next
    }
    {print}' "${ORIG}" > "${TAP}/Formula/towit.rb"
  grep -q '^    url "https://example.com/other.tar.gz"' "${TAP}/Formula/towit.rb"
  commit_tap
  run "${SCRIPT}" 0.9.3 --tap-dir "${TAP}" --tarball "${TARBALL}"
  [ "${status}" -eq 0 ]
  grep -qx '    url "https://example.com/other.tar.gz"' "${TAP}/Formula/towit.rb"
  grep -qx '    sha256 "0000000000000000000000000000000000000000000000000000000000000000"' "${TAP}/Formula/towit.rb"
  grep -qx '  url "https://github.com/chrisbloom7/to-wit/archive/refs/tags/v0.9.3.tar.gz"' "${TAP}/Formula/towit.rb"
  grep -qx "  sha256 \"${SHA}\"" "${TAP}/Formula/towit.rb"
  diff <(other_lines "${ORIG}") <(other_lines "${TAP}/Formula/towit.rb")
}
