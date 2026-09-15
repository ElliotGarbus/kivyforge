"""The output seam every verb writes through (roadmap item 3).

Before this, user output was ~119 scattered ``click.echo`` calls with no central
console, so neither colour nor ``--json`` could be added without editing every
one of them. :class:`Report` is the single interception point; the renderers hang
off it.

Stream routing
--------------

The rule the rest of the item depends on:

* **The product goes to stdout.** In ``--json`` mode that is the envelope; in
  human mode it is the report itself (doctor's check lines, ``status``'s
  summary). So ``kivyforge doctor > report.txt`` keeps working exactly as it
  does today.
* **Progress and log lines go to stderr, always** -- including in ``--json``
  mode. That is the whole point: ``kivyforge build -p android --json >
  build.json`` yields a parseable document while the user still watches Gradle
  work. ``--json`` never has to go quiet to stay parseable.
* **In ``--json`` mode the human report is suppressed**, because the envelope
  supersedes it. Progress is not, per the previous point.

Two failure modes this deliberately avoids
------------------------------------------

**Rich markup is off.** ``markup=True`` (Rich's default) parses square brackets
as style tags, and doctor's lines begin with ``[PASS]`` / ``[FAIL]``. Rich would
treat ``PASS`` as a style name and raise ``MissingStyle`` at render time -- a
crash caused purely by passing our own existing text through a new renderer.
Styling is applied via explicit ``style=`` arguments instead, which also keeps
user-supplied content (paths, package names, error text from a subprocess) from
being interpreted as markup. That last part matters more than the first: a
dependency named ``foo[bar]`` should never be able to influence rendering.

**Highlighting is off.** Rich's auto-highlighter colours things that look like
numbers, paths and URLs. Applied to build output it is noise, and it makes
golden-output tests depend on Rich's heuristics.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import IO

from rich.console import Console

from .diagnostics import Diagnostic
from .envelope import Envelope

#: Status styles. ASCII-safe by construction -- these are colour names, and the
#: glyphs stay in the message text where the cp1252 guard can see them.
STYLES = {
    "PASS": "green",
    "WARN": "yellow",
    "FAIL": "bold red",
    "SKIP": "dim",
}


def want_color(
    *,
    no_color: bool,
    stream: IO[str],
    env: Mapping[str, str] | None = None,
) -> bool:
    """Whether to colour output on *stream*.

    Precedence, most specific first: the explicit flag, then ``NO_COLOR``, then
    ``FORCE_COLOR``, then whether the stream is a terminal.

    ``NO_COLOR`` beats ``FORCE_COLOR`` because the two are only ever both set by
    accident (a CI image exporting one, a user exporting the other), and in that
    case the safe reading of the ambiguity is "no escape codes" -- unwanted
    colour corrupts a log file, whereas absent colour merely disappoints.
    Presence is what counts for both, per https://no-color.org, so ``NO_COLOR=0``
    still disables; that is the documented convention even though it surprises
    people.
    """
    env = os.environ if env is None else env
    if no_color:
        return False
    if env.get("NO_COLOR") is not None:
        return False
    if env.get("FORCE_COLOR") is not None:
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        # A detached or closed stream is not a terminal. ValueError is what a
        # closed file raises, and pytest's capture objects have been known to
        # lack isatty entirely.
        return False


class Report:
    """Everything a verb emits, routed and rendered in one place."""

    def __init__(
        self,
        *,
        command: str,
        kivyforge_version: str,
        platform: str | None = None,
        json_mode: bool = False,
        no_color: bool = False,
        stdout: IO[str] | None = None,
        stderr: IO[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.command = command
        self.kivyforge_version = kivyforge_version
        self.platform = platform
        self.json_mode = json_mode
        self._diagnostics: list[Diagnostic] = []
        self._data: dict[str, object] = {}

        out = sys.stdout if stdout is None else stdout
        err = sys.stderr if stderr is None else stderr
        self._out = _console(out, no_color=no_color, env=env)
        self._err = _console(err, no_color=no_color, env=env)

    # --- human output ------------------------------------------------------

    def line(self, text: str = "", *, style: str | None = None) -> None:
        """Part of the report itself: stdout, and suppressed under ``--json``."""
        if self.json_mode:
            return
        self._out.print(text, style=style)

    def status_line(self, text: str, status: str) -> None:
        """A report line coloured by a doctor-style status name."""
        self.line(text, style=STYLES.get(status))

    def progress(self, text: str) -> None:
        """Incidental progress: stderr, and shown even under ``--json``."""
        self._err.print(text)

    # --- diagnostics -------------------------------------------------------

    def diagnose(self, diagnostic: Diagnostic) -> None:
        self._diagnostics.append(diagnostic)

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(self._diagnostics)

    # --- machine output ----------------------------------------------------

    def record(self, **fields: object) -> None:
        """Add fields to the envelope's ``data`` as they become known.

        The point is the *failure* path. ``reporting()`` emits an envelope when a
        verb raises, and it has nothing to put in ``data`` -- so a run that
        resolved a lock, wrote nothing and then reported drift produced
        ``"data": {}``, discarding the very facts the consumer needs. Anything
        recorded here survives into that envelope.

        A verb that succeeds can pass its payload to :meth:`emit` as before;
        recorded fields merge underneath it, so the two styles mix freely and the
        final value wins.
        """
        self._data.update(fields)

    def envelope(self, *, ok: bool, data: dict[str, object] | None = None) -> Envelope:
        return Envelope(
            command=self.command,
            kivyforge=self.kivyforge_version,
            platform=self.platform,
            ok=ok,
            data={**self._data, **(data or {})},
            diagnostics=self.diagnostics,
        )

    def emit(self, *, ok: bool, data: dict[str, object] | None = None) -> None:
        """Write the envelope, in ``--json`` mode only. A no-op otherwise."""
        if not self.json_mode:
            return
        # Written through the raw stream rather than Rich: the payload must be
        # byte-for-byte what json.dumps produced, and a console is entitled to
        # wrap, indent or style anything it is given.
        self._out.file.write(self.envelope(ok=ok, data=data).to_json())
        self._out.file.flush()


def _console(
    stream: IO[str], *, no_color: bool, env: Mapping[str, str] | None
) -> Console:
    colored = want_color(no_color=no_color, stream=stream, env=env)
    return Console(
        file=stream,
        # Both flags, not just no_color. Rich's ``no_color`` strips *colour* but
        # keeps other SGR attributes, so a "bold red" style still emits
        # ``\x1b[1m`` on a terminal -- which defeats the point, since the reason
        # to pass --no-color is usually a log file or a CI transcript, where a
        # stray bold code is exactly as much noise as a stray colour code.
        # Turning terminal detection off as well is what guarantees no escape
        # sequences at all. This is a slightly broader reading of NO_COLOR than
        # no-color.org's ("prevent the addition of ANSI color codes"), and the
        # broader one is what callers actually want.
        #
        # Losing Rich's width detection is the cost, and it is not a real cost
        # here: soft_wrap below means we never reflow to the width anyway.
        no_color=not colored,
        force_terminal=colored,
        markup=False,
        highlight=False,
        # Our messages arrive pre-wrapped with meaningful indentation (the
        # `hint:` continuation lines), so Rich must not re-flow them to the
        # terminal width.
        soft_wrap=True,
        emoji=False,
    )
