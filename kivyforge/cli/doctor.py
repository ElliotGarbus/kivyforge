"""``kivyforge doctor`` — environment + project health check (spec 05).

Platform-aware: resolves the target (``-p`` / ``KIVYFORGE_PLATFORM`` / host,
falling back to iOS for a bare environment check) and dispatches to that
backend's ``doctor`` over its ``pyproject.toml`` + ``pylock.<platform>.toml``.

First consumer of :mod:`kivyforge.report` (roadmap item 3), and first by design:
``CheckResult`` was already a structured frozen dataclass, so ``--json`` here is
close to free, and it is the most useful verb for an agent to have -- it answers
"is a build even possible" before anything expensive is attempted.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from .. import __version__
from ..doctor import CheckResult, Status, worst_status
from ..platforms import Platform, PlatformResolutionError, get_platform
from ..platforms import resolve_target as _resolve_platform
from ..report import Diagnostic, diagnostics, exit_codes
from ._common import PYPROJECT_NAME
from ._output import output_options, reporting
from ._platform import configured_platforms, platform_option

# Status to diagnostic severity. PASS and SKIP produce no diagnostic: a list
# that includes successes is one every consumer has to filter first.
_SEVERITY = {
    Status.FAIL: diagnostics.ERROR,
    Status.WARN: diagnostics.WARNING,
}


@click.command()
@platform_option
@click.option("--offline", is_flag=True, help="Skip network-dependent checks.")
@output_options
def doctor(
    cli_platform: str | None,
    offline: bool,
    json_out: bool,
    no_color: bool,
) -> None:
    """Run environment and project health checks."""
    cwd = Path.cwd()
    with reporting("doctor", json_out=json_out, no_color=no_color) as report:
        backend = _resolve_doctor_backend(cli_platform, cwd)
        report.platform = backend.name

        results = backend.doctor(cwd, kivyforge_version=__version__, offline=offline)
        mode = "project" if _has_config(cwd) else "environment"

        report.line(f"kivyforge doctor ({backend.name}, {mode} mode)")
        report.line()
        for result in results:
            report.status_line(result.render(), result.status.value)

        for result in results:
            severity = _SEVERITY.get(result.status)
            if severity is not None:
                report.diagnose(_as_diagnostic(result, severity))

        ok = worst_status(results) is not Status.FAIL
        report.emit(
            ok=ok,
            data={
                "mode": mode,
                "checks": [r.as_dict() for r in results],
                "summary": _summary(results),
            },
        )

    if not ok:
        # ENVIRONMENT_ERROR rather than the historical 1: a doctor FAIL means
        # something about this machine or project is not ready, which is a
        # different reaction from "you passed a bad flag". Raised outside the
        # reporting block so it is never mistaken for a ToolchainError.
        raise SystemExit(exit_codes.ENVIRONMENT_ERROR)


def _as_diagnostic(result: CheckResult, severity: str) -> Diagnostic:
    return Diagnostic(
        code=result.code or diagnostics.DOCTOR_CHECK,
        severity=severity,
        message=f"{result.name}: {result.detail}" if result.detail else result.name,
        remediation=result.hint,
        # The check name is the join key back into data.checks, so it travels
        # with the diagnostic rather than requiring the consumer to parse it out
        # of the message.
        context={"check": result.name},
    )


def _summary(results: list[CheckResult]) -> dict[str, int]:
    """Counts per status, every key always present.

    All four keys are emitted even at zero so a consumer can read
    ``summary["FAIL"]`` unconditionally.
    """
    counts = {status.value: 0 for status in Status}
    for result in results:
        counts[result.status.value] += 1
    return counts


def _resolve_doctor_backend(cli_platform: str | None, cwd: Path) -> Platform:
    pyproject = cwd / PYPROJECT_NAME
    configured = configured_platforms(pyproject) if pyproject.is_file() else set()
    try:
        return _resolve_platform(cli_platform, configured=configured, env=os.environ)
    except PlatformResolutionError:
        # Environment-mode fallback: no project/target to infer from.
        return get_platform("ios")


def _has_config(cwd: Path) -> bool:
    return (cwd / PYPROJECT_NAME).is_file()
