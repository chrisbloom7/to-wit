"""Completion contracts are derived from the dispatcher and argparse definitions."""
import ast
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIBEXEC = ROOT / 'libexec' / 'towit'
DISPATCHER = (ROOT / 'bin' / 'towit').read_text(encoding='utf-8')
COMMAND_CASE = DISPATCHER.split('case "${subcommand}" in', 1)[1].split('\nesac', 1)[0]
COMMANDS = set(re.findall(r'^  ([a-z][a-z-]*)(?:\|[^\n]*)?\)$', COMMAND_CASE, re.M)) - {'open'}
BASH = ROOT / 'completions' / 'towit.bash'
ZSH = ROOT / 'completions' / '_towit'

BASH_PROBE = r'''
source "$1"
shift
COMP_WORDS=(towit "$@")
COMP_CWORD=$#
_towit_completions
printf '%s\n' "${COMPREPLY[@]}"
'''

ZSH_PROBE = r'''
completion_file=$1
requested=$2
_arguments() {
    if [[ $1 == -C ]]; then
        if [[ -z $requested ]]; then
            state=command
        else
            state=arguments
            line=("$requested")
        fi
    else
        print -rl -- "$@"
    fi
}
_describe() { print -rl -- "${subcommands[@]}"; }
source "$completion_file"
'''


def command_options(command):
    """Read accepted options without executing commands that can modify data."""
    helper = LIBEXEC / f'towit_{command.replace("-", "_")}.py'
    options = set()
    choices = {}
    if helper.is_file():
        tree = ast.parse(helper.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == 'ArgumentParser':
                options.update(('-h', '--help'))
            if node.func.attr != 'add_argument':
                continue
            flags = {arg.value for arg in node.args if isinstance(arg, ast.Constant)
                     and isinstance(arg.value, str) and arg.value.startswith('-')}
            options.update(flags)
            for keyword in node.keywords:
                if keyword.arg == 'choices':
                    for flag in flags:
                        choices[flag] = set(ast.literal_eval(keyword.value))
    block = re.search(rf'^  {re.escape(command)}\)\n(.*?)^    ;;$', COMMAND_CASE, re.M | re.S)
    if block:
        options.update(re.findall(r'^      (?:  )?(--[a-z-]+)\)', block.group(1), re.M))
    return options, choices


def bash_complete(*words):
    result = subprocess.run(
        ['bash', '-c', BASH_PROBE, 'towit-completion-test', str(BASH), *words],
        text=True, capture_output=True, check=True,
    )
    return set(result.stdout.split())


def zsh_specs(command):
    result = subprocess.run(
        ['zsh', '-fc', ZSH_PROBE, 'towit-completion-test', str(ZSH), command],
        text=True, capture_output=True, check=True,
    )
    return result.stdout.splitlines()


class TestBashCompletion(unittest.TestCase):
    def test_commands_and_top_level_flags(self):
        self.assertGreaterEqual(len(COMMANDS), 15)
        self.assertEqual(bash_complete(''), COMMANDS | {'-h', '--help', '-v', '--version'})
        self.assertEqual(bash_complete('sea'), {'search'})

    def test_options_match_cli(self):
        for command in sorted(COMMANDS):
            options, choices = command_options(command)
            with self.subTest(command=command):
                self.assertEqual(bash_complete(command, '-'), options)
                for flag, values in choices.items():
                    self.assertEqual(bash_complete(command, flag, ''), values)

    def test_equals_word_and_split_equals(self):
        self.assertEqual(bash_complete('show', '--format=te'), {'--format=text'})
        self.assertEqual(bash_complete('show', '--format', '=', 'te'), {'text'})


@unittest.skipUnless(shutil.which('zsh'), 'zsh is unavailable')
class TestZshCompletion(unittest.TestCase):
    def test_commands_match_cli(self):
        self.assertEqual({spec.split(':', 1)[0] for spec in zsh_specs('')},
                         COMMANDS | {'-h', '--help', '-v', '--version'})

    def test_options_match_cli(self):
        for command in sorted(COMMANDS):
            options, choices = command_options(command)
            with self.subTest(command=command):
                specs = zsh_specs(command)
                self.assertEqual(
                    {match.group(1) for spec in specs
                     if (match := re.search(r'^\*?(--?[a-z][a-z-]*)', spec))},
                    options,
                )
                for flag, values in choices.items():
                    spec = next(spec for spec in specs if spec.startswith(flag + '['))
                    match = re.search(r':\(([^)]+)\)$', spec)
                    self.assertIsNotNone(match, spec)
                    self.assertEqual(set(match.group(1).split()), values)


if __name__ == '__main__':
    unittest.main()
