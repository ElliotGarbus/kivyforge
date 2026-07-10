"""``kivyforge doctor`` — environment + project health check (spec 05).

Platform-aware: resolves the target (``-p`` / ``KIVYFORGE_PLATFORM`` / host,
falling back to iOS for a bare environment check) and dispatches to that
backend's ``doctor`` over its ``pyproject.toml`` + ``pylock.<platform>.toml``.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from .. import __version__
from ..doctor import Status, worst_status
from ..platforms import Platform, PlatformResolutionError, get_platform
from ..platforms import resolve_target as _resolve_platform
from ._common import PYPROJECT_NAME
from ._platform import configured_platforms, platform_option


@click.command()
@platform_option
@click.option("--offline", is_flag=True, help="Skip network-dependent checks.")
def doctor(cli_platform: str | None, offline: bool) -> None:
    """Run environment and project health checks."""
    cwd = Path.cwd()
    backend = _resolve_doctor_backend(cli_platform, cwd)
    results = backend.doctor(cwd, kivyforge_version=__version__, offline=offline)

    mode = "project" if _has_config(cwd) else "environment"
    click.echo(f"kivyforge doctor ({backend.name}, {mode} mode)\n")
    for result in results:
        click.echo(result.render())

    if worst_status(results) is Status.FAIL:
        raise SystemExit(1)


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
