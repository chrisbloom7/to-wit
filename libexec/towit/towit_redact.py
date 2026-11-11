#!/usr/bin/env python3
"""Best-effort, pattern-based secret redaction.

redact() replaces secret-shaped substrings with [REDACTED:<kind>]. It is pure,
deterministic, idempotent, and never raises on arbitrary text. Patterns are kept
linear-time: bounded quantifiers, and token patterns anchored by a lookbehind so
a long run of token characters is scanned once, not once per start position.
"""

import re
import sys
from typing import Sequence

# kind -> regex. Order matters: anthropic_key must run before openai_key.
# A named group "secret" limits replacement to that group (keeping the scheme,
# host, key name, or "Bearer " prefix); otherwise the whole match is replaced.
REDACTION_PATTERNS = {
    'aws_key_id': r'(?<![A-Za-z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])',
    'github_token': r'(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})',
    'anthropic_key': r'(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}',
    'openai_key': r'(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,}',
    'stripe_key': r'(?<![A-Za-z0-9_])(?:[sr]k_(?:live|test)|whsec)_[A-Za-z0-9]{16,}',
    'slack_token': r'(?<![A-Za-z0-9-])xox[abprs]-[A-Za-z0-9-]{10,}',
    'jwt': r'(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}',
    'private_key': r'-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----[A-Za-z0-9+/=\s]*(?:-----END [A-Z ]{0,30}PRIVATE KEY-----)?',
    'bearer_token': r'\b[Bb]earer[ \t]{1,5}(?P<secret>[A-Za-z0-9._~+/=-]{16,})',
    'url_credentials': r'://(?P<secret>[^\s/@:\[\]]{1,100}:[^\s/@\[\]]{1,200})@',
    # Needs a digit in the value so code like max_tokens = some_long_name is left alone.
    'secret_assignment': (
        r'(?i:key|secret|token|password)\w{0,40}["\']?[ \t]*[=:][ \t]*["\']?'
        r'(?P<secret>(?=[A-Za-z0-9_+/=.-]{0,200}\d)[A-Za-z0-9_+/=.-]{16,})'
    ),
}

_COMPILED = [(kind, re.compile(rx)) for kind, rx in REDACTION_PATTERNS.items()]

_extra_cache = {}
_warned = set()


def _replacer(kind):
    marker = '[REDACTED:%s]' % kind

    def repl(m):
        if 'secret' in m.re.groupindex:
            start, end = m.span('secret')
            offset = m.start()
            whole = m.group(0)
            return whole[:start - offset] + marker + whole[end - offset:]
        return marker
    return repl


def _compile_extra(pattern):
    """Return a compiled regex for a user pattern, or None (warning once) if unusable."""
    if pattern in _extra_cache:
        return _extra_cache[pattern]
    compiled = None
    try:
        compiled = re.compile(pattern)
        if compiled.match(''):
            problem = 'matches the empty string'
            compiled = None
        else:
            problem = None
    except (re.error, TypeError, RecursionError) as e:
        problem = str(e)
    if compiled is None and pattern not in _warned:
        _warned.add(pattern)
        print('towit: warning: ignoring invalid ingest.extra_patterns entry %r: %s'
              % (pattern, problem), file=sys.stderr)
    _extra_cache[pattern] = compiled
    return compiled


def redact(text: str, extra_patterns: Sequence[str] = ()) -> str:
    """Replace secret-shaped substrings in text with [REDACTED:<kind>]."""
    if not isinstance(text, str) or not text:
        return text
    for kind, rx in _COMPILED:
        text = rx.sub(_replacer(kind), text)
    for pattern in extra_patterns or ():
        rx = _compile_extra(pattern)
        if rx is not None:
            text = rx.sub('[REDACTED:custom]', text)
    return text
