"""``--app-version`` / ``--no-build-isolation``, and resolving before dispatch.

Shared by ``build``, ``package`` and ``run``, the verbs that write a version
into an artifact. The verb resolves once, records the result and hands it to
the backend (docs/design/dev/dynamic-version-proposal.md section 3.4).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import click

from ..config import ConfigError
from ..config.loader import load_declared_version
from ..config.model import DynamicVersion, ResolvedVersion
from ..report import Report, diagnostics
from ..report.diagnostics import Diagnostic
from ..report.failures import ClassifiedError
from ..versioning import (
    ENV_OVERRIDE,
    FLAG_OVERRIDE,
    announcement,
    check_apple_version,
    check_version_file,
    resolve_version,
)
from ._common import ToolchainError


def version_options[F: Callable[..., object]](func: F) -> F:
    """Add ``--app-version`` and ``--no-build-isolation``."""
    func = click.option(
        "--no-build-isolation",
        is_flag=True,
        help="Resolve a dynamic version with the build backend installed in "
        "kivyforge's own environment (offline) instead of an isolated one. You "
        "vouch the environment has everything the backend needs.",
    )(func)
    func = click.option(
        FLAG_OVERRIDE,
        "app_version",
        default=None,
        metavar="VERSION",
        help=f"Build with this version instead of [project].version or the build "
        f"backend's (also {ENV_OVERRIDE}; the flag wins).",
    )(func)
    return func


def reject_unused(
    *, app_version: str | None, no_build_isolation: bool, why: str
) -> None:
    """Refuse version flags the command line makes a no-op (*why* names it)."""
    for given, name in (
        (app_version, FLAG_OVERRIDE),
        (no_build_isolation, "--no-build-isolation"),
    ):
        if given:
            raise ToolchainError(
                f"{name} has no effect with {why}, which builds nothing.\n"
                f"  Fix: drop {name}, or drop {why}."
            )


def resolve_for_verb(
    report: Report,
    project_root: Path,
    *,
    platform: str,
    app_version: str | None,
    no_build_isolation: bool,
    exports: bool,
    export_method: str | None = None,
) -> ResolvedVersion:
    """Resolve, announce and check the version, before any backend runs.

    Records ``data.version`` immediately, so a ``--json`` envelope from a build
    that fails later still says which version it was building. Warnings go to
    stderr and into the report's diagnostics; ``run`` has no envelope, so for it
    stderr is the whole report.
    """
    if app_version and no_build_isolation:
        raise ToolchainError(
            "--no-build-isolation has no effect with --app-version, which skips "
            "the build backend.\n  Fix: drop one of them."
        )
    try:
        declared, scm_version_file = load_declared_version(
            project_root / "pyproject.toml"
        )
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc

    if (
        isinstance(declared, DynamicVersion)
        and not app_version
        and not os.environ.get(ENV_OVERRIDE, "").strip()
    ):
        report.progress(f"Resolving the version with {declared.backend} (pip) ...")
    try:
        version = resolve_version(
            declared,
            project_root,
            flag=app_version,
            env=os.environ,
            isolated=not no_build_isolation,
        )
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc
    except ClassifiedError as exc:
        raise ToolchainError.wrap(exc) from exc
    report.record(version={"value": version.value, "source": version.source})

    line = announcement(version, declared, flag=app_version)
    if line is not None:
        report.progress(line)
    if no_build_isolation and version.source == "static":
        _report(
            report,
            Diagnostic(
                code=diagnostics.VERSION_ISOLATION_UNUSED,
                severity=diagnostics.INFO,
                message="--no-build-isolation had no effect: [project].version is "
                "static, so the build backend was not run.",
            ),
        )
    try:
        apple = check_apple_version(
            version, platform=platform, exports=exports, export_method=export_method
        )
    except ClassifiedError as exc:
        raise ToolchainError.wrap(exc) from exc
    for found in (apple, check_version_file(version, scm_version_file)):
        if found is not None:
            _report(report, found)
    return version


def _report(report: Report, diagnostic: Diagnostic) -> None:
    report.progress(f"{diagnostic.severity}: {diagnostic.message}")
    if diagnostic.remediation:
        report.progress(f"  {diagnostic.remediation}")
    report.diagnose(diagnostic)
