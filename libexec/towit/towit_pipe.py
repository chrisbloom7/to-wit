#!/usr/bin/env python3
"""
towit_pipe — Exit quietly when stdout is a pipe whose reader has gone away.

`towit show <id> | head -n 1` closes the pipe after one line. Python ignores SIGPIPE,
so the next write raises BrokenPipeError and, unhandled, prints a traceback. The
subcommands that print results run through run_cli() instead, which turns that one
error into a silent exit with status 141 (128 + SIGPIPE, the status git and most
Unix tools report).
"""

import contextlib
import os
import sys

# 128 + SIGPIPE (13): the conventional exit status of a process killed by a closed pipe
EXIT_STATUS = 141


@contextlib.contextmanager
def quiet_broken_pipe():
    """Exit with status 141 if writing to stdout inside the block hits a closed pipe.

    Wrap only the code that writes to stdout. A BrokenPipeError raised elsewhere (for
    example by a child process) must stay a real error, so do not wrap whole programs
    that also talk to subprocesses; use this around the print calls instead.
    """
    try:
        yield
        # Buffered output may only fail on flush; surface it here, not at shutdown
        sys.stdout.flush()
    except BrokenPipeError:
        # Point stdout at /dev/null so the flush the interpreter does at exit has
        # nowhere to fail ("Exception ignored ... BrokenPipeError")
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        sys.exit(EXIT_STATUS)


def run_cli(main):
    """Run main(), exiting quietly with status 141 if stdout is a closed pipe.

    Only BrokenPipeError is handled. SystemExit from main() (every sys.exit code the
    subcommands use) passes through unchanged, and any other exception still prints
    its traceback.
    """
    with quiet_broken_pipe():
        try:
            main()
        finally:
            # Flush even when main() exits early, so a closed pipe shows up now
            sys.stdout.flush()
