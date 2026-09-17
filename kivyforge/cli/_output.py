"""Shared output options for every verb (roadmap item 3).

``--json`` and ``--no-color`` belong to all verbs, so they are one decorator
rather than nine copies. They sit on the *verbs* rather than the top-level group
on purpose: a group option has to precede the subcommand (``kivyforge --no-color
doctor``), and everyone types ``kivyforge doctor --no-color``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import click

from .. import __version__
from ..build_outcome import Artifact, BuildEvents
from ..report import Diagnostic, Report, diagnostics
from ._common import ToolchainError


@contextmanager
def reporting(
    command: str,
    *,
    json_out: bool,
    no_color: bool,
    platform: str | None = None,
) -> Iterator[Report]:
    """Yield a :class:`~kivyforge.report.Report`, and emit one on failure too.

    Without this, ``--json`` produced **empty stdout** on exactly the run an agent
    most needs to read: a bad ``pyproject.toml`` raised ``ToolchainError``, click
    printed ``Error: ...`` to stderr, and no envelope was ever written. A consumer
    could not tell that from a crash, or from a verb that legitimately says
    nothing.

    So the failure is reported twice, in the two registers that already exist:
    the envelope goes to stdout, and click still prints its ``Error: ...`` to
    stderr because the exception is re-raised untouched. Re-raising also keeps
    the exit code click's to choose, which matters -- ``ToolchainError`` carries
    its own now.

    *platform* is often unknown when the failure happens, since resolving the
    target is itself one of the things that can fail. It stays ``None`` in that
    case, which is why the envelope's ``platform`` key is nullable; a verb that
    learns it later assigns ``report.platform``.

    Not caught here: ``click.UsageError`` (a bad flag), which click raises while
    parsing, before any command body runs. Nothing inside a verb can see it, and
    it exits ``2`` -- see :mod:`kivyforge.report.exit_codes`.
    """
    report = Report(
        command=command,
        kivyforge_version=__version__,
        platform=platform,
        json_mode=json_out,
        no_color=no_color,
    )
    try:
        yield report
    except ToolchainError as exc:
        report.diagnose(exc.as_diagnostic())
        report.emit(ok=False)
        raise


#: Severity of each success-path note a build or package can attach. A note is
#: never an error -- anything fatal raises instead -- so unknown codes are warnings.
_NOTE_SEVERITY = {diagnostics.MANIFEST_POLICY: diagnostics.INFO}


def report_events(report: Report) -> BuildEvents:
    """The ``build``/``package`` callbacks, backed by *report*.

    Artifacts are re-recorded as a whole list on every product, because
    ``Report.record`` replaces a field rather than appending to it; recording as
    they happen is what lets a failure envelope still name what was finished.
    """
    artifacts: list[dict[str, str]] = []

    def on_artifact(artifact: Artifact) -> None:
        artifacts.append(artifact.as_dict())
        report.record(artifacts=list(artifacts))

    def on_note(code: str, message: str, context=None) -> None:
        report.diagnose(
            Diagnostic(
                code=code,
                severity=_NOTE_SEVERITY.get(code, diagnostics.WARNING),
                message=message,
                context=dict(context or {}),
            )
        )

    return BuildEvents(
        on_line=report.line,
        on_progress=report.progress,
        on_artifact=on_artifact,
        on_note=on_note,
    )


def output_options[F: Callable[..., object]](fn: F) -> F:
    """Add ``--json`` and ``--no-color``, passed as ``json_out`` / ``no_color``.

    ``--json`` is named ``json_out`` in Python because ``json`` would shadow the
    stdlib module inside the verb, which is exactly the sort of thing that works
    until someone adds an ``import json`` and gets a confusing error.
    """
    fn = click.option(
        "--json",
        "json_out",
        is_flag=True,
        help="Emit a machine-readable JSON envelope on stdout.",
    )(fn)
    fn = click.option(
        "--no-color",
        is_flag=True,
        help="Disable coloured output. NO_COLOR is honoured too.",
    )(fn)
    return fn
