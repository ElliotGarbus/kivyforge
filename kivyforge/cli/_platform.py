"""CLI glue for target-platform selection (common design doc 02).

Provides the shared ``-p/--platform`` option and ``resolve_target``, which reads
which ``[tool.kivy.<platform>]`` overlays a project configures and runs the
resolution chain, surfacing failures as clean ``ToolchainError`` messages.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import click

from ..platforms import (
    Platform,
    PlatformResolutionError,
    available_platform_names,
)
from ..platforms import (
    resolve_target as _resolve_target,
)
from ._common import ToolchainError, find_pyproject

platform_option = click.option(
    "--platform",
    "-p",
    "cli_platform",
    type=click.Choice(available_platform_names()),
    default=None,
    help="Target platform (overrides KIVYFORGE_PLATFORM and the host default).",
)


def configured_platforms(pyproject: Path) -> set[str]:
    """Platform names whose ``[tool.kivy.<name>]`` overlay this project declares."""
    try:
        raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    kivy = raw.get("tool", {}).get("kivy", {})
    if not isinstance(kivy, dict):
        return set()
    return {name for name in available_platform_names() if name in kivy}


def reject_android_only(backend: Platform, options: dict[str, object]) -> None:
    """Fail when Android-only options are used against another platform.

    The shared verbs carry the full option superset, so an option that only
    Android acts on would otherwise be silently ignored elsewhere — the worst
    outcome, since the user believes it took effect.
    """
    used = [name for name, value in options.items() if value]
    if not used or backend.name == "android":
        return
    raise ToolchainError(
        f"{', '.join(used)} {'is' if len(used) == 1 else 'are'} "
        f"Android-only; not valid for {backend.name}."
    )


def resolve_target(
    cli_platform: str | None, *, verb: str = "build"
) -> tuple[Platform, Path]:
    """Resolve the target platform and return it with the project root.

    Looks for ``pyproject.toml`` in the CWD (like every verb), determines the
    configured overlays, and runs the resolution chain. ``verb`` names the
    calling CLI command so an unresolved-platform error's example command is
    accurate (e.g. ``kivyforge lock --platform ios``, not always ``build``).
    """
    pyproject = find_pyproject()
    try:
        backend = _resolve_target(
            cli_platform,
            configured=configured_platforms(pyproject),
            env=os.environ,
            verb=verb,
        )
    except PlatformResolutionError as exc:
        raise ToolchainError(str(exc)) from exc
    return backend, pyproject.parent
