"""Shared helpers for the ``kivyforge`` CLI.

All verbs look for ``pyproject.toml`` in the **current working directory
only** — no parent-directory traversal (per spec 05).
"""

from __future__ import annotations

from pathlib import Path

import click

from ..build_outcome import BuildEvents, discard_artifact, discard_note
from ..report import diagnostics, exit_codes

PYPROJECT_NAME = "pyproject.toml"
# iOS lockfile name, kept for the iOS verbs' backward-compatible call sites.
# New/platform-aware code uses ``lockfile_name``/``lockfile_path_for``.
LOCKFILE_NAME = "pylock.ios.toml"


def lockfile_name(platform: str) -> str:
    """The per-platform lockfile filename, e.g. ``pylock.macos.toml``."""
    return f"pylock.{platform}.toml"


class ToolchainError(click.ClickException):
    """A user-facing error that prints cleanly and exits non-zero.

    Unlike a bare exception, ``click`` renders this as ``Error: <message>``
    without a traceback, which is what we want for expected failure modes
    (missing pyproject, validation errors, drift, etc.).

    Roadmap item 3 gave it structure as well as a message, so a ``--json`` run
    reports the failure as a diagnostic instead of producing empty stdout. Every
    field is optional: an untriaged raise site keeps exactly its old behaviour
    (generic code, exit ``1``) and is merely unspecific, never wrong.
    """

    exit_code = exit_codes.CONFIG_ERROR

    def __init__(
        self,
        message: str,
        *,
        code: str = diagnostics.UNSPECIFIED,
        exit_code: int | None = None,
        remediation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = _extract_fix(message) if remediation is None else remediation
        if exit_code is not None:
            self.exit_code = exit_code

    def as_diagnostic(self) -> diagnostics.Diagnostic:
        return diagnostics.Diagnostic(
            code=self.code,
            severity=diagnostics.ERROR,
            message=self.format_message(),
            remediation=self.remediation,
        )


def _echo_line(text: str) -> None:
    click.echo(text)


def _echo_progress(text: str) -> None:
    click.echo(text)


#: Human-only wiring for ``build``/``package``, byte-identical to the output that
#: predates the callbacks: product and progress both print to stdout, artifacts
#: and notes are dropped. ``--json`` replaces this with report-backed closures.
ECHO_EVENTS = BuildEvents(
    on_line=_echo_line,
    on_progress=_echo_progress,
    on_artifact=discard_artifact,
    on_note=discard_note,
)


def _extract_fix(message: str) -> str:
    """Pull the trailing ``Fix:`` line out of a message, if it has one.

    The backends already end user-facing failures with an explicit ``Fix:`` line
    (a convention established in roadmap item 1), so honouring it here gives
    every existing raise site a populated ``remediation`` without touching any of
    them. A raise site that wants to be exact passes ``remediation=``.

    Parsing prose is normally the thing to avoid -- the point of structured
    diagnostics is that consumers should not have to. Doing it *once, at the
    producer*, is the opposite: it is how the convention becomes a field instead
    of staying prose for everyone downstream.
    """
    for line in reversed(message.splitlines()):
        stripped = line.strip()
        if stripped.startswith("Fix:"):
            return stripped.removeprefix("Fix:").strip()
    return ""


def find_pyproject(start: Path | None = None) -> Path:
    """Return the path to ``pyproject.toml`` in the current directory.

    Raises ``ToolchainError`` if it is not present. No parent traversal is
    performed — the tool is intentionally CWD-scoped so it never picks up an
    unrelated ``pyproject.toml`` from an ancestor directory.
    """
    base = Path.cwd() if start is None else start
    candidate = base / PYPROJECT_NAME
    if not candidate.is_file():
        raise ToolchainError(
            f"no {PYPROJECT_NAME} found in the current directory ({base}).\n"
            f"  Run kivyforge commands from the directory that contains your "
            f"{PYPROJECT_NAME}, or run `kivyforge init` to create one."
        )
    return candidate


def lockfile_path(start: Path | None = None) -> Path:
    """Return the path where ``pylock.ios.toml`` lives (sibling to pyproject)."""
    base = Path.cwd() if start is None else start
    return base / LOCKFILE_NAME


def lockfile_path_for(platform: str, start: Path | None = None) -> Path:
    """Return the ``pylock.<platform>.toml`` path (sibling to pyproject)."""
    base = Path.cwd() if start is None else start
    return base / lockfile_name(platform)
