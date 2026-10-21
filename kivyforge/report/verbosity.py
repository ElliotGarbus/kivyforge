"""How much detail the tools a verb runs should show: ``-v`` / ``-vv`` (issue #64).

The level is a count the verb parses and sets for its lifetime, and the code
deep in a backend that starts a tool reads it -- the same route
:func:`~kivyforge.report.transfers.transfers_to` gives downloads, so no backend
signature carries it. See ``docs/design/dev/verbose-output-proposal.md``.

What the levels promise on any platform (proposal §3.7):

* ``1`` prints every command the backend runs, with its working directory, so
  the user can rerun it by hand. It never makes a successful run much longer.
* ``2`` may: it is for the tool's full output and its own verbose modes.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar

#: The highest level with a meaning; ``-vvv`` and up are treated as this.
MAX_VERBOSITY = 2

_CURRENT: ContextVar[int] = ContextVar("kivyforge_verbosity", default=0)


@contextmanager
def verbosity_to(level: int) -> Iterator[None]:
    """Run this context at *level*, clamped to ``0..MAX_VERBOSITY``."""
    token = _CURRENT.set(max(0, min(level, MAX_VERBOSITY)))
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current_verbosity() -> int:
    """The level the running verb set; ``0`` outside any verb."""
    return _CURRENT.get()


#: Arguments that read the same, unquoted, in PowerShell and in cmd.exe.
_WINDOWS_PLAIN = re.compile(r"[\w.:\\/=+@-]+")


def command_line(argv: Sequence[str], *, windows: bool | None = None) -> str:
    """*argv* as this host's shell would take it, for a user to paste and rerun.

    On Windows that is either of two shells. ``list2cmdline`` quotes only for
    spaces, but PowerShell also splits on ``;`` and ``,`` -- sdkmanager's
    ``ndk;27.2.12479018`` -- so anything outside a plain set is quoted too.
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return shlex.join(argv)
    return " ".join(
        arg if _WINDOWS_PLAIN.fullmatch(arg) else _windows_quote(arg) for arg in argv
    )


def _windows_quote(arg: str) -> str:
    """Always-quoted, with the backslash rules ``list2cmdline`` follows."""
    quoted = subprocess.list2cmdline([arg])
    if quoted.startswith('"'):
        return quoted
    # No space or tab, so list2cmdline left it bare (escaping any quotes);
    # backslashes before the closing quote added here must be doubled.
    trailing = len(quoted) - len(quoted.rstrip("\\"))
    return f'"{quoted}{"\\" * trailing}"'
