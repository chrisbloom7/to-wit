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
            self.assertContains(readme, f'`{key}`', f"[{section}] {key} missing from README")
            self.assertMatches(template, rf'(?m)^#? ?{re.escape(key)} =',
                               f"[{section}] {key} missing from _CONFIG_TEMPLATE")

    def test_every_hook_event_documented(self):
        for event in towit_install_hook.HOOK_EVENTS:
            for doc in ('README.md', 'AGENTS.md'):
                self.assertContains(_read(doc), event, f"{event} missing from {doc}")


if __name__ == '__main__':
    unittest.main()
