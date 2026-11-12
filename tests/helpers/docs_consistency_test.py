# tests/helpers/docs_consistency_test.py
"""Mechanical checks that README, AGENTS.md, SECURITY.md, CHANGELOG and the help text
agree with the code. Prose accuracy is audited by hand; these catch drift in names,
flags, config keys, hook events, tables and environment variables."""
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'libexec', 'towit'))

# Imported modules read TOWIT_* env at import time; keep them off the real home.
os.environ.setdefault('TOWIT_CONFIG_PATH', os.path.join(ROOT, 'no-such-config.toml'))

import towit_config  # noqa: E402
import towit_install_hook  # noqa: E402
import towit_setup  # noqa: E402

FLAG_RE = re.compile(r'--[a-z][a-z-]*')


def _read(rel_path: str) -> str:
    with open(os.path.join(ROOT, rel_path), encoding='utf-8') as fh:
        return fh.read()


class DocTestCase(unittest.TestCase):
    """assertIn/assertRegex variants that never dump a whole document on failure."""

    def assertContains(self, text, needle, msg):
        self.assertTrue(needle in text, msg)

    def assertMatches(self, text, pattern, msg):
        self.assertIsNotNone(re.search(pattern, text), msg)


def _help_output() -> str:
    result = subprocess.run([os.path.join(ROOT, 'bin', 'towit'), 'help'],
                            capture_output=True, text=True, check=True)
    return result.stdout


def _dispatcher_case_block() -> str:
    script = _read('bin/towit')
    start = script.index('case "${subcommand}" in')
    return script[start:script.index('\nesac', start)]


def _dispatcher_subcommands() -> set:
    """Labels of the top-level case, minus the deprecated `open` alias, `help` and defaults."""
    labels = set()
    for line in _dispatcher_case_block().splitlines():
        m = re.match(r'^  ([a-z][a-z-]*)\)\s*$', line)  # two-space indent: top level only
        if m:
            labels.add(m.group(1))
    return labels - {'open', 'help'}


def _readme_usage_block() -> str:
    readme = _read('README.md')
    after = readme[readme.index('\n## Usage'):]
    fence = after.index('```')
    return after[fence + 3:after.index('```', fence + 3)]


def _flattened_config_keys() -> list:
    return [(section, key) for section, keys in towit_config._KNOWN_KEYS.items() for key in keys]


class TestReadmeAndHelp(DocTestCase):
    def test_every_subcommand_in_help_and_readme(self):
        subcommands = _dispatcher_subcommands()
        self.assertIn('forget', subcommands)  # the parser found the real case block
        help_text, usage = _help_output(), _readme_usage_block()
        for sub in sorted(subcommands):
            pattern = re.compile(rf'^\s*#?\s*{re.escape(sub)}\b', re.MULTILINE)
            self.assertMatches(help_text, pattern, f"{sub} missing from `towit help`")
            self.assertMatches(usage, pattern, f"{sub} missing from the README Usage block")

    def test_help_flags_match_readme_usage(self):
        help_flags = set(FLAG_RE.findall(_help_output()))
        readme_flags = set(FLAG_RE.findall(_readme_usage_block()))
        self.assertEqual(help_flags - readme_flags, set(), "flags in help but not README Usage")
        self.assertEqual(readme_flags - help_flags, set(), "flags in README Usage but not help")

    def test_every_config_key_documented(self):
        readme, template = _read('README.md'), towit_setup._CONFIG_TEMPLATE
        for section, key in _flattened_config_keys():
            self.assertMatches(readme, rf'(?m)^\| `{key}` \|', f"[{section}] {key} missing from the README config tables")
            self.assertMatches(template, rf'(?m)^#? ?{re.escape(key)} =',
                               f"[{section}] {key} missing from _CONFIG_TEMPLATE")

    def test_every_hook_event_documented(self):
        events = list(towit_install_hook.HOOK_EVENTS)
        self.assertEqual(len(events), 3)
        readme, agents = _read('README.md'), _read('AGENTS.md')
        for event in events:  # a row of the README hooks table, not a stray substring
            self.assertMatches(readme, rf'(?m)^\| `{event}`', f"{event} has no row in the README hooks table")
        # AGENTS.md must name all the events together, in one sentence about registration
        self.assertTrue(any(all(f'`{e}`' in line for e in events) for line in agents.splitlines()),
                        "AGENTS.md has no line naming all hook events")


def _libexec_modules() -> list:
    libexec = os.path.join(ROOT, 'libexec', 'towit')
    return sorted(f[:-3] for f in os.listdir(libexec) if f.startswith('towit_') and f.endswith('.py'))


def _env_vars_read_by_code() -> set:
    """TOWIT_* names read from os.environ anywhere under libexec/towit/."""
    reads = re.compile(r"""os\.(?:environ(?:\.get\(|\[)|getenv\()\s*['"](TOWIT_[A-Z_]+)['"]""")
    found = set()
    for module in _libexec_modules():
        found |= set(reads.findall(_read(f'libexec/towit/{module}.py')))
    return found


class TestAgentsMd(DocTestCase):
    def test_every_env_var_documented_in_agents_md(self):
        found = _env_vars_read_by_code()
        self.assertIn('TOWIT_INDEXING', found)  # the scan really finds reads
        agents = _read('AGENTS.md')
        for var in sorted(found):
            self.assertMatches(agents, rf'`{var}[`=]', f"{var} missing from the AGENTS.md environment table")

    def test_every_schema_table_in_agents_md(self):
        tables = set(re.findall(r'CREATE (?:VIRTUAL )?TABLE (?:IF NOT EXISTS )?(\w+)', _read('libexec/towit/towit_db.py')))
        self.assertGreaterEqual(len(tables), 9)
        agents = _read('AGENTS.md')
        for table in sorted(tables):
            self.assertContains(agents, f'`{table}`', f"table {table} missing from AGENTS.md")

    def test_every_non_subcommand_module_in_agents_md(self):
        dispatcher = _read('bin/towit')
        helpers = [m for m in _libexec_modules() if f'{m}.py"' not in dispatcher]
        self.assertIn('towit_ingest', helpers)
        agents = _read('AGENTS.md')
        for module in helpers:
            self.assertContains(agents, f'`{module}.py`', f"{module}.py missing from AGENTS.md")

    def test_claude_md_imports_agents_md(self):
        self.assertMatches(_read('CLAUDE.md'), r'(?m)^@AGENTS\.md\s*$', "CLAUDE.md must import @AGENTS.md")


class TestWording(DocTestCase):
    # Lines that are genuinely about the Claude Code `Stop` hook event, not the old
    # single-hook design: towit_setup's reindex_delta comment says the Stop hook fires
    # after every response, which is still true.
    ALLOWED = ('The Stop hook fires after every response',)

    def test_no_stale_stop_hook_wording_in_user_facing_code(self):
        paths = [os.path.join('bin', f) for f in os.listdir(os.path.join(ROOT, 'bin'))]
        paths += ['install', 'uninstall']
        paths += [f'libexec/towit/{m}.py' for m in _libexec_modules()]
        offenders = []
        for rel in paths:
            for n, line in enumerate(_read(rel).splitlines(), 1):
                if re.search(r'\bstop hook\b', line, re.I) and not any(a in line for a in self.ALLOWED):
                    offenders.append(f'{rel}:{n}')
        self.assertEqual(offenders, [], 'stale "stop hook" wording (the hooks are Stop, SessionEnd, SessionStart)')


class TestSecurityMd(DocTestCase):
    def test_security_allowlist_matches_source(self):
        sentence = next((line for line in _read('SECURITY.md').splitlines()
                         if 'prefix allowlist' in line), None)
        self.assertIsNotNone(sentence, "SECURITY.md has no subprocess-allowlist sentence")
        documented = {token.rstrip('*') for token in re.findall(r'`([A-Za-z_*]+)`', sentence)}
        self.assertEqual(documented, set(towit_config._PASS_THROUGH_PREFIXES))

    def test_security_documents_archive_controls(self):
        security = _read('SECURITY.md')
        for term in ('redact', 'forget', 'FTS5', 'claude purge', 'SessionEnd'):
            self.assertContains(security, term, f"SECURITY.md does not mention {term!r}")


class TestVersion(DocTestCase):
    def test_version_file_matches_newest_changelog_release(self):
        released = re.search(r'(?m)^## \[(\d+\.\d+\.\d+)\]', _read('CHANGELOG.md'))
        self.assertIsNotNone(released, "CHANGELOG.md has no numbered release heading")
        self.assertEqual(_read('libexec/towit/VERSION').strip(), released.group(1),
                         "libexec/towit/VERSION must equal the newest CHANGELOG release")


class TestChangelog(DocTestCase):
    @unittest.skipUnless(os.environ.get('TOWIT_RELEASE_CHECK') == '1',
                         'release gate: set TOWIT_RELEASE_CHECK=1')
    def test_changelog_has_unreleased_content(self):
        changelog = _read('CHANGELOG.md')
        start = changelog.index('## [Unreleased]') + len('## [Unreleased]')
        nxt = re.search(r'(?m)^## \[', changelog[start:])
        section = changelog[start:start + nxt.start()] if nxt else changelog[start:]
        self.assertTrue(section.strip(), "CHANGELOG.md [Unreleased] section is empty")


if __name__ == '__main__':
    unittest.main()
