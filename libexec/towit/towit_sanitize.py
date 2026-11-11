"""
towit_sanitize — make archived text safe to print to a terminal.

Archived text came from tool output and web content, so it can carry terminal
control sequences. Used by `show` (full text), `search` and `list` (table cells).
"""

import re

# String-type sequences (OSC, DCS, SOS, PM, APC) go whole, then CSI, then any other
# two-byte ESC sequence, then stray C0/C1 controls (newline and tab are kept).
# Bidi override/isolate characters are stripped too.
_STRING_SEQ = re.compile(r'(?:\x1b[\]PX^_]|[\x90\x98\x9d\x9e\x9f])[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?')
_CSI_SEQ = re.compile(r'(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]?')
_ESC_SEQ = re.compile(r'\x1b[ -/]*[0-~]?')
_CONTROLS = re.compile('[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]')


def sanitize(text) -> str:
    """Strip terminal control sequences; newlines and tabs are kept."""
    text = str(text) if text is not None else ''
    for pattern in (_STRING_SEQ, _CSI_SEQ, _ESC_SEQ, _CONTROLS):
        text = pattern.sub('', text)
    return text


def sanitize_cell(text) -> str:
    """Sanitize for one line of a table: also collapse newlines, tabs and runs of spaces."""
    return ' '.join(sanitize(text).split())
