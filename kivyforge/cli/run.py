"""``kivyforge run`` — build, install, and launch on a simulator/device (spec 05)."""

from __future__ import annotations

import click

from ..platforms.ios.cli import ios_list_devices
from ._platform import platform_option, resolve_target


@click.command()
@platform_option
@click.option(
    "--simulator",
    "target",
    flag_value="simulator",
    default=True,
    help="Target the iOS simulator (default).",
)
@click.option(
    "--device", "target", flag_value="device", help="Target a connected device."
)
@click.option(
    "--arch",
    type=click.Choice(["arm64", "x86_64", "universal2"]),
    default=None,
    help="macOS: assemble a subset of the locked archs for a faster run.",
)
@click.option(
    "--destination", default=None, help="Specific simulator/device by name or UDID."
)
@click.option(
    "--list-devices",
    is_flag=True,
    help="Print available simulators and devices, then exit.",
)
@click.option(
    "--no-build",
    is_flag=True,
    help="Skip the implicit build; install + launch the existing app.",
)
def run(
    cli_platform: str | None,
    target: str,
    arch: str | None,
    destination: str | None,
    list_devices: bool,
    no_build: bool,
) -> None:
    """Build (unless --no-build), install, and launch the app."""
    if list_devices:
        ios_list_devices()
        return

    backend, project_root = resolve_target(cli_platform, verb="run")
    backend.run(
        project_root,
        target=target,
        arch=arch,
        destination=destination,
        no_build=no_build,
    )
