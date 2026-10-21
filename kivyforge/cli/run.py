"""``kivyforge run`` — build, install, and launch on a simulator/device (spec 05)."""

from __future__ import annotations

import click
from click.core import ParameterSource

from .. import __version__
from ..platforms.ios.cli import ios_list_devices
from ..report import Report
from ..report.transfers import transfers_to
from ..report.verbosity import verbosity_to
from ._common import ToolchainError
from ._output import verbosity_option
from ._platform import platform_option, reject_android_only, resolve_target
from ._version import (
    check_app_metadata,
    reject_unused,
    resolve_for_verb,
    version_options,
)


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
    # aarch64 is deliberately absent: Linux aarch64 is cross-only, and `run`
    # execs the result on this host.
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
@click.option(
    "--release",
    is_flag=True,
    help=(
        "Build the release flavor, so byte_compile/strip_source apply as they do "
        "for `package` (Android, Linux, macOS, Windows). Android: the release "
        "variant (with --smoke, the release probe)."
    ),
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
    "--abi",
    type=click.Choice(["arm64_v8a", "x86_64"]),
    default=None,
    help="Android: restrict the implicit build to one ABI.",
)
@click.option(
    "--no-follow",
    is_flag=True,
    help=(
        "Android: print the app's log once, 25 s after launch, and return "
        "instead of following it until the app exits or Ctrl-C (for scripts)."
    ),
)
@version_options
@verbosity_option
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
    no_follow: bool,
    app_version: str | None,
    no_build_isolation: bool,
    verbosity: int,
) -> None:
    """Build (unless --no-build), install, and launch the app."""
    # run takes no --json, so no reporting() context gives it a report; its
    # implicit build still downloads, so downloads draw through one of their
    # own (stderr only, like all progress). The -v level is set here for the
    # same reason.
    report = Report(command="run", kivyforge_version=__version__)
    try:
        with transfers_to(report.transfer), verbosity_to(verbosity):
            _run(
                cli_platform=cli_platform,
                target=target,
                arch=arch,
                destination=destination,
                list_devices=list_devices,
                no_build=no_build,
                emulator=emulator,
                avd=avd,
                serial=serial,
                smoke=smoke,
                release=release,
                abi=abi,
                no_follow=no_follow,
                app_version=app_version,
                no_build_isolation=no_build_isolation,
                report=report,
            )
    finally:
        report.close_transfers()


def _run(
    *,
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
    no_follow: bool,
    app_version: str | None,
    no_build_isolation: bool,
    report: Report,
) -> None:
    backend, project_root = resolve_target(cli_platform, verb="run")
    # --smoke always builds (it has no --no-build path); --list-devices and
    # --no-build build nothing, so they carry no version and refuse the flags.
    builds = not list_devices and (smoke or not no_build)
    if not builds:
        reject_unused(
            app_version=app_version,
            no_build_isolation=no_build_isolation,
            why="--list-devices" if list_devices else "--no-build",
        )

    def resolve():
        if not builds:
            return None
        version = resolve_for_verb(
            report,
            project_root,
            platform=backend.name,
            app_version=app_version,
            no_build_isolation=no_build_isolation,
            exports=False,
        )
        check_app_metadata(report, project_root)
        return version

    reject_android_only(
        backend,
        {
            "--emulator": emulator,
            "--avd": avd,
            "--serial": serial,
            "--smoke": smoke,
            "--abi": abi,
            "--no-follow": no_follow,
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

        if smoke and no_follow:
            raise ToolchainError(
                "--no-follow applies to the app's log, which --smoke does not "
                "show; pass one."
            )
        if list_devices:
            from ..platforms.android import adb as adb_mod

            click.echo("Devices: " + (", ".join(adb_mod.connected_devices()) or "none"))
            click.echo("AVDs: " + (", ".join(adb_mod.available_avds()) or "none"))
            return
        version = resolve()
        if smoke:
            assert version is not None  # smoke always builds
            android_smoke(
                project_root,
                version=version,
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
                version=version,
                no_build=no_build,
                release=release,
                abi=abi,
                serial=serial or destination,
                avd=avd,
                prefer_emulator=emulator or avd is not None,
                require_physical=require_physical,
                follow=not no_follow,
            )
        return

    if list_devices:
        ios_list_devices()
        return

    backend.run(
        project_root,
        version=resolve(),
        target=target,
        arch=arch,
        destination=destination,
        no_build=no_build,
        release=release,
    )
