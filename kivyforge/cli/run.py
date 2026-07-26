"""``kivyforge run`` — build, install, and launch on a simulator/device (spec 05)."""

from __future__ import annotations

import click

from ..platforms.ios.cli import ios_list_devices
from ._common import ToolchainError
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
    type=click.Choice(["arm64", "x86_64", "universal2", "arm64_v8a"]),
    default=None,
    help="macOS: a subset of locked archs; Android: restrict to one ABI.",
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
# --- Android-only ---
@click.option(
    "--emulator", is_flag=True, help="Android: boot/target an emulator (AVD)."
)
@click.option("--avd", default=None, help="Android: which AVD to boot (--emulator).")
@click.option(
    "--serial", default=None, help="Android: which adb device when several attach."
)
@click.option(
    "--smoke",
    is_flag=True,
    help="Android: run the generated contract smoke test instead of launching.",
)
@click.option(
    "--release",
    is_flag=True,
    help="Android (with --smoke): target the release variant.",
)
def run(
    cli_platform: str | None,
    target: str,
    arch: str | None,
    destination: str | None,
    list_devices: bool,
    no_build: bool,
    emulator: bool,
    avd: str | None,
    serial: str | None,
    smoke: bool,
    release: bool,
) -> None:
    """Build (unless --no-build), install, and launch the app."""
    backend, project_root = resolve_target(cli_platform, verb="run")

    android_only = {
        "--emulator": emulator,
        "--avd": avd,
        "--serial": serial,
        "--smoke": smoke,
        "--release": release,
    }
    used = [name for name, value in android_only.items() if value]
    if used and backend.name != "android":
        raise ToolchainError(
            f"{', '.join(used)} {'is' if len(used) == 1 else 'are'} "
            f"Android-only; not valid for {backend.name}."
        )

    if backend.name == "android":
        from ..platforms.android.cli import android_run, android_smoke

        if list_devices:
            from ..platforms.android import adb as adb_mod

            click.echo("Devices: " + (", ".join(adb_mod.connected_devices()) or "none"))
            click.echo("AVDs: " + (", ".join(adb_mod.available_avds()) or "none"))
            return
        if smoke:
            android_smoke(
                project_root,
                release=release,
                abi=arch,
                serial=serial,
                avd=avd,
                prefer_emulator=emulator or avd is not None,
            )
        else:
            android_run(
                project_root,
                no_build=no_build,
                abi=arch,
                serial=serial or destination,
                avd=avd,
                prefer_emulator=emulator or avd is not None,
            )
        return

    if list_devices:
        ios_list_devices()
        return

    backend.run(
        project_root,
        target=target,
        arch=arch,
        destination=destination,
        no_build=no_build,
    )
