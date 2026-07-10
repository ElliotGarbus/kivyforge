"""``kivyforge open`` — open the generated Xcode project (spec 05)."""

from __future__ import annotations

import click

from ..platforms.ios.cli import ios_open
from ._platform import platform_option, resolve_target


@click.command(name="open")
@platform_option
def open_(cli_platform: str | None) -> None:
    """Open <app>-ios/<app>.xcodeproj in Xcode."""
    _backend, project_root = resolve_target(cli_platform)
    ios_open(project_root)
