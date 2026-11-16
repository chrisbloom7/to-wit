#!/usr/bin/env python3
"""
towit_skill — install, remove and check the To Wit Claude Code plugin.

The plugin is served from this repo's marketplace (`.claude-plugin/marketplace.json`) and is
pinned to the tag matching the installed CLI (`<repo>#v<VERSION>`), so the skill never
describes flags the CLI lacks. Re-running `install` after an upgrade repins it.

Everything goes through the `claude plugin` CLI, in list form and user scope. The
subprocess inherits the full environment (unlike the indexing calls): the marketplace
clone is a git checkout run on the user's behalf and needs their git and ssh credentials.
"""

import json
import os
import re
import shutil
import subprocess
import sys

SOURCE = 'chrisbloom7/to-wit'
MARKETPLACE = 'to-wit'
PLUGIN = 'towit'
PLUGIN_ID = f'{PLUGIN}@{MARKETPLACE}'
TIMEOUT_SECONDS = 180        # installing and removing: a git clone can be slow
QUERY_TIMEOUT_SECONDS = 30   # listing: a hung claude must not stall `towit doctor`

VERSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION')
_VERSION_RE = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z')


class SkillError(Exception):
    """A `claude plugin` call failed, or `claude` is not installed."""


def installed_version(path=VERSION_PATH):
    """The CLI version from the VERSION file, or None if unreadable."""
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def _claude(args, timeout=TIMEOUT_SECONDS):
    """Run `claude plugin <args>`; return (returncode, parsed JSON or None, text)."""
    exe = shutil.which('claude')
    if exe is None:
        raise SkillError("claude CLI not found on PATH; install Claude Code first")
    try:
        result = subprocess.run([exe, 'plugin', *args], capture_output=True, text=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SkillError(f"`claude plugin {args[0]}` timed out after {timeout}s") from None
    return result.returncode, _parse_json(result.stdout), (result.stderr or result.stdout).strip()


def _parse_json(stdout):
    """The JSON in `--json` output: all of it (lists are pretty-printed over many lines),
    else the last line (single results come after any progress text)."""
    text = stdout.strip()
    for candidate in (text, text.splitlines()[-1] if text else ''):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _message(payload, text):
    if isinstance(payload, dict) and payload.get('message'):
        return payload['message']
    return text or 'no output'


def _run(args, timeout=TIMEOUT_SECONDS):
    """Like `_claude`, but a nonzero exit raises SkillError."""
    code, payload, text = _claude(args, timeout)
    if code != 0:
        raise SkillError(f"`claude plugin {' '.join(args[:2])}` failed: {_message(payload, text)}")
    return payload


def _marketplace_entry():
    """Our marketplace as `claude plugin marketplace list --json` reports it, or None."""
    entries = _run(['marketplace', 'list', '--json'], QUERY_TIMEOUT_SECONDS)
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and entry.get('name') == MARKETPLACE:
            return entry
    return None


def _plugin_installed():
    plugins = _run(['list', '--json'], QUERY_TIMEOUT_SECONDS)
    return isinstance(plugins, list) and any(
        isinstance(p, dict) and p.get('id') == PLUGIN_ID for p in plugins)


def _ref_for(version):
    if not isinstance(version, str) or not _VERSION_RE.match(version):
        raise SkillError(f"cannot pin the skill: {version!r} is not a release version (X.Y.Z)")
    return f'v{version}'


def _is_pinned(entry, ref):
    return (entry is not None and entry.get('source') == 'github'
            and entry.get('repo') == SOURCE and entry.get('ref') == ref)


def _source_of(entry):
    """The `marketplace add` source string for a listed marketplace, or None if unknown."""
    if entry.get('source') == 'github' and entry.get('repo'):
        return f"{entry['repo']}#{entry['ref']}" if entry.get('ref') else entry['repo']
    return entry.get('path') or entry.get('url')


def _restore(source, had_plugin):
    """Best effort: put back the marketplace (and plugin) a failed repin removed."""
    try:
        _run(['marketplace', 'add', source, '--scope', 'user', '--json'])
        if had_plugin:
            _run(['install', PLUGIN_ID, '--scope', 'user', '--json'])
    except SkillError:
        return f"could not restore the previous install; run: claude plugin marketplace add {source}"
    return "previous marketplace and plugin restored"


def install(version):
    """Install the plugin pinned to v<version>; repin if the marketplace is declared otherwise.

    Removing a marketplace also uninstalls its plugins, so a repin always ends by
    installing the plugin again. If the new pin cannot be added (for example the tag is not
    pushed yet), the previous marketplace and plugin are restored. Raises SkillError.
    """
    ref = _ref_for(version)
    entry = _marketplace_entry()
    if not _is_pinned(entry, ref):
        previous = had_plugin = None
        if entry is not None:
            previous = _source_of(entry)
            had_plugin = _plugin_installed()
            _run(['marketplace', 'remove', MARKETPLACE, '--scope', 'user', '--json'])
        try:
            _run(['marketplace', 'add', f'{SOURCE}#{ref}', '--scope', 'user', '--json'])
        except SkillError as exc:
            if previous:
                raise SkillError(f"{exc} ({_restore(previous, had_plugin)})") from None
            raise
    _run(['install', PLUGIN_ID, '--scope', 'user', '--json'])


def uninstall():
    """Remove the plugin and its marketplace. True if anything was removed.

    Quietly False when `claude` is missing or nothing was installed.
    """
    if shutil.which('claude') is None:
        return False
    removed = False
    for args in (['uninstall', PLUGIN_ID, '--scope', 'user', '--json'],
                 ['marketplace', 'remove', MARKETPLACE, '--scope', 'user', '--json']):
        code, payload, text = _claude(args)
        if code == 0:
            removed = True
        elif 'not found' not in text.lower() and 'not_installed' not in json.dumps(payload):
            raise SkillError(f"`claude plugin {args[0]}` failed: {_message(payload, text)}")
    return removed


def present():
    """True when claude is available and the plugin or its marketplace is installed."""
    if shutil.which('claude') is None:
        return False
    return _plugin_installed() or _marketplace_entry() is not None


def status(version):
    """(state, detail): 'unavailable', 'missing', 'unpinned', 'stale' or 'ok'.

    'unpinned' is the documented manual install of this repo, which follows main; 'stale' is
    anything else not pinned to v<version> (another ref, another repo, a local path).
    """
    if shutil.which('claude') is None:
        return 'unavailable', 'claude CLI not found on PATH'
    if not _plugin_installed():
        return 'missing', f'{PLUGIN_ID} is not installed'
    entry = _marketplace_entry()
    ref = _ref_for(version)
    if _is_pinned(entry, ref):
        return 'ok', f'{PLUGIN_ID} installed, pinned to {ref}'
    entry = entry or {}
    if entry.get('source') == 'github' and entry.get('repo') == SOURCE and not entry.get('ref'):
        return 'unpinned', f"{PLUGIN_ID} follows main, which can run ahead of this CLI; v{version} is the matching version"
    if entry.get('source') == 'github' and entry.get('ref'):
        return 'stale', f"{PLUGIN_ID} is pinned to {entry['ref']}, expected {ref}"
    return 'stale', f"{PLUGIN_ID} is not pinned (source: {_source_of(entry) or 'unknown'}), expected {ref}"


def main(argv=None):
    """CLI: `towit_skill.py install|uninstall`. Returns the process exit status."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in ('install', 'uninstall'):
        print("usage: towit_skill.py install|uninstall", file=sys.stderr)
        return 2
    try:
        if argv[0] == 'install':
            version = installed_version()
            if version is None:
                raise SkillError("cannot read the towit version, so the skill cannot be pinned")
            install(version)
            print(f"Claude Code skill installed ({PLUGIN_ID}, pinned to v{version}). "
                  "Start a new session or run /reload-plugins to load it.")
        elif uninstall():
            print(f"Claude Code skill removed ({PLUGIN_ID}).")
        else:
            print("Claude Code skill not installed.")
    except SkillError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
