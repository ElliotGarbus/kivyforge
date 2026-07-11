"""``kivyforge status`` — read-only project state snapshot (spec 05).

Platform-aware: resolves the target (``-p`` / ``KIVYFORGE_PLATFORM`` / host) and
dispatches to that backend's ``status`` over its ``pyproject.toml`` +
``pylock.<platform>.toml``.
"""

from __future__ import annotations

import click

from ._platform import platform_option, resolve_target


@click.command()
@platform_option
def status(cli_platform: str | None) -> None:
    """Show app identity, Python version, lock sync, and build state."""
    backend, project_root = resolve_target(cli_platform)
    backend.status(project_root)
