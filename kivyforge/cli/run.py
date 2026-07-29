"""``kivyforge run`` — build, install, and launch on a simulator/device (spec 05)."""

from __future__ import annotations

import click
from click.core import ParameterSource

from ..platforms.ios.cli import ios_list_devices
from ._common import ToolchainError
from ._platform import platform_option, reject_android_only, resolve_target


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
    "--device",
    "target",
    flag_value="device",
    help="Target a connected device (Android: a physical one, never an AVD).",
)
@click.option(
    "--arch",
    # x86_64 stays: it is the Linux arch and an Android ABI, not a macOS one.
    type=click.Choice(["arm64", "x86_64", "arm64_v8a"]),
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
@click.option(
    "--abi",
    type=click.Choice(["arm64_v8a", "x86_64"]),
    default=None,
    help="Android: restrict the implicit build to one ABI.",
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
    abi: str | None,
) -> None:
    """Build (unless --no-build), install, and launch the app."""
    backend, project_root = resolve_target(cli_platform, verb="run")

    reject_android_only(
        backend,
        {
            "--emulator": emulator,
            "--avd": avd,
            "--serial": serial,
            "--smoke": smoke,
            "--release": release,
            "--abi": abi,
        },
    )
    abi = abi or arch

    if backend.name == "android":
        from ..platforms.android.cli import android_run, android_smoke

        # --simulator is the default flag value, so only an *explicit* one is a
        # mistake worth reporting; the source is how click tells the two apart.
        source = click.get_current_context().get_parameter_source("target")
        explicit = target if source is ParameterSource.COMMANDLINE else None
        if explicit == "simulator":
            raise ToolchainError(
                "--simulator is iOS-only; Android's equivalent is --emulator."
            )
        if explicit == "device" and emulator:
            raise ToolchainError(
                "--device and --emulator select opposite targets; pass one, or "
                "neither to auto-select (a single attached device, else an AVD)."
            )
        if explicit == "device" and avd is not None:
            raise ToolchainError(
                "--avd names an emulator to boot, which --device rules out; pass one."
            )
        require_physical = explicit == "device"

        if list_devices:
            from ..platforms.android import adb as adb_mod

            click.echo("Devices: " + (", ".join(adb_mod.connected_devices()) or "none"))
            click.echo("AVDs: " + (", ".join(adb_mod.available_avds()) or "none"))
            return
        if smoke:
            android_smoke(
                project_root,
                release=release,
                abi=abi,
                serial=serial,
                avd=avd,
                prefer_emulator=emulator or avd is not None,
                require_physical=require_physical,
            )
        else:
            android_run(
                project_root,
                no_build=no_build,
                abi=abi,
                serial=serial or destination,
                avd=avd,
                prefer_emulator=emulator or avd is not None,
                require_physical=require_physical,
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
