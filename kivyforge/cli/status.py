"""``kivyforge status`` — read-only project state snapshot (spec 05).

Platform-aware: resolves the target (``-p`` / ``KIVYFORGE_PLATFORM`` / host) and
dispatches to that backend's ``status`` over its ``pyproject.toml`` +
``pylock.<platform>.toml``.

The backends return a :class:`~kivyforge.status.StatusReport`; the rendering --
human and JSON -- happens here. Before roadmap item 3 each backend printed its
own report, which is why ``--json`` needed this verb refactored rather than just
intercepted.
"""

from __future__ import annotations

import click

from .. import __version__
from ..report import Diagnostic, Report, diagnostics
from ..status import ARTIFACT_LABEL_WIDTH, LABEL_WIDTH, LockState, StatusReport
from ._output import output_options
from ._platform import platform_option, resolve_target

# Lock states worth telling a consumer about, with the code that names each.
# IN_SYNC is absent: it is the expected case and not a diagnostic.
_LOCK_CODES = {
    LockState.MISSING: diagnostics.LOCK_MISSING,
    LockState.OUT_OF_DATE: diagnostics.LOCK_DRIFT,
    LockState.UNREADABLE: diagnostics.LOCK_UNREADABLE,
}


@click.command()
@platform_option
@output_options
def status(cli_platform: str | None, json_out: bool, no_color: bool) -> None:
    """Show app identity, Python version, lock sync, and build state."""
    backend, project_root = resolve_target(cli_platform, verb="status")
    report = Report(
        command="status",
        kivyforge_version=__version__,
        platform=backend.name,
        json_mode=json_out,
        no_color=no_color,
    )

    snapshot = backend.status(project_root)

    for line in render(snapshot):
        report.line(line)

    code = _LOCK_CODES.get(snapshot.lock.state)
    if code is not None:
        report.diagnose(
            Diagnostic(
                code=code,
                severity=diagnostics.WARNING,
                message=f"lock is {snapshot.lock.state.value}",
                remediation=snapshot.lock.relock_command,
            )
        )

    # Always ``ok``: status is read-only and reports whatever it finds. A stale
    # lock is news about the project, not a failure of the command, and it has
    # never affected the exit code.
    report.emit(ok=True, data=snapshot.as_dict())


def render(snapshot: StatusReport) -> list[str]:
    """The human report, as lines.

    Returned rather than printed so it can be asserted on directly, and so the
    ``--json`` path can skip it without this function knowing about modes.
    """
    lines = [
        _row("App", f"{snapshot.app_name}  ({snapshot.app_id})"),
        _row("Python", snapshot.python_version),
    ]
    lines += [_row(label, value) for label, value in snapshot.extra]
    lines.append(_row("Lock", snapshot.lock.render()))

    # A single unlabelled artifact reads better on the Build: line itself; only
    # platforms that genuinely produce several (iOS, Android) open a list.
    if len(snapshot.artifacts) == 1 and not snapshot.artifacts[0].label:
        lines.append(_row("Build", snapshot.artifacts[0].render()))
    else:
        lines.append(_row("Build", ""))
        lines += [
            f"  {a.label:<{ARTIFACT_LABEL_WIDTH}}{a.render()}"
            for a in snapshot.artifacts
        ]
    return lines


def _row(label: str, value: str) -> str:
    return f"{label + ':':<{LABEL_WIDTH}}{value}".rstrip()
