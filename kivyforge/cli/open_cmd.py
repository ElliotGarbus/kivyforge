"""``kivyforge open`` — open the generated Xcode project (spec 05)."""

from __future__ import annotations

import click

from ._platform import platform_option, resolve_target


@click.command(name="open")
@platform_option
def open_(cli_platform: str | None) -> None:
    """Open <app>-ios/<app>.xcodeproj in Xcode."""
    backend, project_root = resolve_target(cli_platform, verb="open")
    backend.open_project(project_root)
