"""``kivyforge doctor`` — environment + project health check (spec 05).

Platform-aware: resolves the target (``-p`` / ``KIVYFORGE_PLATFORM`` / host,
falling back to iOS for a bare environment check) and runs that backend's check
set over its ``pyproject.toml`` + ``pylock.<platform>.toml``.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from .. import __version__
from ..config import ConfigError, load_config
from ..doctor import (
    CheckResult,
    RealProbe,
    Status,
    run_checks,
    run_linux_checks,
    run_macos_checks,
    worst_status,
)
from ..lock import LockError, load
from ..lock.linux import load as load_linux_lock
from ..lock.macos import load as load_macos_lock
from ..platforms import PlatformResolutionError
from ..platforms import resolve_target as _resolve_platform
from ._common import PYPROJECT_NAME, lockfile_name
from ._platform import configured_platforms, platform_option


@click.command()
@platform_option
@click.option("--offline", is_flag=True, help="Skip network-dependent checks.")
def doctor(cli_platform: str | None, offline: bool) -> None:
    """Run environment and project health checks."""
    cwd = Path.cwd()
    platform = _resolve_doctor_platform(cli_platform, cwd)
    if platform == "macos":
        results = _macos_doctor(cwd, offline)
    elif platform == "linux":
        results = _linux_doctor(cwd, offline)
    else:
        results = _ios_doctor(cwd, offline)

    mode = "project" if _has_config(cwd) else "environment"
    click.echo(f"kivyforge doctor ({platform}, {mode} mode)\n")
    for result in results:
        click.echo(result.render())

    if worst_status(results) is Status.FAIL:
        raise SystemExit(1)


def _resolve_doctor_platform(cli_platform: str | None, cwd: Path) -> str:
    pyproject = cwd / PYPROJECT_NAME
    configured = configured_platforms(pyproject) if pyproject.is_file() else set()
    try:
        return _resolve_platform(
            cli_platform, configured=configured, env=os.environ
        ).name
    except PlatformResolutionError:
        # Environment-mode fallback: no project/target to infer from.
        return "ios"


def _has_config(cwd: Path) -> bool:
    return (cwd / PYPROJECT_NAME).is_file()


def _ios_doctor(cwd: Path, offline: bool) -> list[CheckResult]:
    pyproject = cwd / PYPROJECT_NAME
    config = None
    lock = None
    parse_results: list[CheckResult] = []
    if pyproject.is_file():
        try:
            config = load_config(pyproject)
        except ConfigError as exc:
            parse_results.append(CheckResult(PYPROJECT_NAME, Status.FAIL, exc.format()))
        lockfile = cwd / lockfile_name("ios")
        if lockfile.is_file():
            try:
                lock = load(lockfile)
            except LockError as exc:
                parse_results.append(_lock_parse_fail("ios", exc))
    return parse_results + run_checks(
        RealProbe(),
        kivyforge_version=__version__,
        config=config,
        project_root=cwd,
        lock=lock,
        offline=offline,
    )


def _macos_doctor(cwd: Path, offline: bool) -> list[CheckResult]:
    pyproject = cwd / PYPROJECT_NAME
    config = None
    lock = None
    parse_results: list[CheckResult] = []
    if pyproject.is_file():
        try:
            config = load_config(pyproject, require_ios=False, require_macos=True)
        except ConfigError as exc:
            parse_results.append(CheckResult(PYPROJECT_NAME, Status.FAIL, exc.format()))
        lockfile = cwd / lockfile_name("macos")
        if lockfile.is_file():
            try:
                lock = load_macos_lock(lockfile)
            except LockError as exc:
                parse_results.append(_lock_parse_fail("macos", exc))
    return parse_results + run_macos_checks(
        RealProbe(),
        kivyforge_version=__version__,
        config=config,
        project_root=cwd,
        lock=lock,
        offline=offline,
    )


def _linux_doctor(cwd: Path, offline: bool) -> list[CheckResult]:
    pyproject = cwd / PYPROJECT_NAME
    config = None
    lock = None
    parse_results: list[CheckResult] = []
    if pyproject.is_file():
        try:
            config = load_config(pyproject, require_ios=False, require_linux=True)
        except ConfigError as exc:
            parse_results.append(CheckResult(PYPROJECT_NAME, Status.FAIL, exc.format()))
        lockfile = cwd / lockfile_name("linux")
        if lockfile.is_file():
            try:
                lock = load_linux_lock(lockfile)
            except LockError as exc:
                parse_results.append(_lock_parse_fail("linux", exc))
    return parse_results + run_linux_checks(
        RealProbe(),
        kivyforge_version=__version__,
        config=config,
        project_root=cwd,
        lock=lock,
        offline=offline,
    )


def _lock_parse_fail(platform: str, exc: LockError) -> CheckResult:
    return CheckResult(
        lockfile_name(platform),
        Status.FAIL,
        f"failed to parse: {exc}",
        hint=f"Regenerate it with `kivyforge lock -p {platform}`.",
    )
