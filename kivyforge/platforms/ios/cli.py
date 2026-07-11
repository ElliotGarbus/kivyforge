"""iOS build/run/package/open/status logic (specs 05/06).

Extracted from the shared ``cli`` verbs so all iOS-specific behavior lives behind
the iOS backend, symmetric with ``platforms/macos/cli.py`` and
``platforms/linux/cli.py``. The verb modules stay thin dispatchers.
"""

from __future__ import annotations

import os
import plistlib
import re
import time
from pathlib import Path

import click

from kivyforge.artifacts.collect import CollectError, collect_artifacts
from kivyforge.artifacts.wheels import BuildSlice
from kivyforge.cli._common import (
    LOCKFILE_NAME,
    ToolchainError,
    lockfile_path,
)
from kivyforge.config import ConfigError, load_config
from kivyforge.config.icons import IconSourceError
from kivyforge.lock import LockError, is_in_sync

from .lock import load
from .materialize import materialize_project
from .staging import StagingError, create_staging
from .xcode import (
    CommandError,
    SigningError,
    XcodeBuild,
    archive_command,
    build_command,
    default_simulator_arch,
    devicectl_install,
    devicectl_launch,
    devicectl_list,
    export_command,
    export_options_plist,
    open_command,
    preflight_signing,
    product_app_path,
    resolve_device_destination,
    resolve_simulator_destination,
    run_command,
    simctl_install,
    simctl_launch,
    simctl_list,
)
from .xcode.commands import SIGNING_IDENTITY_ENV, resolve_signing_identity

# ---- build --------------------------------------------------------------- #


def ios_build(
    project_root: Path,
    *,
    target: str | None,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
    team_id: str | None,
    signing_identity: str | None,
    export_method: str,
) -> None:
    """Download artifacts, generate the Xcode project, and optionally build it."""
    # Signing pre-flight runs before any artifact work so --device/--release
    # fail fast on a missing team_id (spec 05 step 7).
    config = _load_config(project_root / "pyproject.toml")
    if target is not None:
        try:
            preflight_signing(config, target, team_id_flag=team_id)
        except SigningError as exc:
            raise ToolchainError(str(exc)) from exc

    prepare_build(
        config,
        project_root,
        target=target,
        arch=arch,
        no_verify_lock=no_verify_lock,
        no_cache=no_cache,
    )

    if target is None:
        click.echo(
            "Project ready. Open it with `kivyforge open` or build with "
            "`kivyforge build --simulator`."
        )
        return

    xb = XcodeBuild.from_config(config, project_root)
    try:
        _xcodebuild_step7(
            xb,
            config,
            target=target,
            arch=arch,
            team_id_flag=team_id,
            signing_identity_flag=signing_identity,
            export_method=export_method,
        )
    except (CommandError, SigningError) as exc:
        raise ToolchainError(str(exc)) from exc


def prepare_build(
    config,
    project_root: Path,
    *,
    target: str | None,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
) -> BuildSlice:
    """Run build steps 1-6 (drift, artifact collection, project generation).

    Shared by ``kivyforge build`` and ``kivyforge run``. A bare ``toolchain
    build`` (no target) collects both the device and simulator pip-deps slices
    so the generated project builds either Xcode destination without re-running
    the toolchain; a targeted build collects only its slice. Returns the primary
    slice (the targeted one, or the device slice for a bare build).
    """
    pyproject = project_root / "pyproject.toml"
    lock = _load_lock(project_root)
    if not no_verify_lock and not is_in_sync(lock, pyproject.read_text("utf-8")):
        raise ToolchainError(
            f"{LOCKFILE_NAME} is out of date with pyproject.toml.\n"
            "  Run `kivyforge lock` to regenerate it (or pass --no-verify-lock "
            "to build against the stale lock anyway)."
        )

    build_slices = _resolve_slices(target, arch, config.ios.deployment_target)
    tags = ", ".join(s.platform_tag for s in build_slices)
    try:
        layout = create_staging(config, project_root)
        click.echo(f"Collecting artifacts for {tags} ...")
        collect_artifacts(
            lock,
            layout,
            build_slices=build_slices,
            project_root=project_root,
            no_cache=no_cache,
        )
        materialize_project(
            config,
            project_root,
            layout=layout,
            python_version=lock.python_xcframework.version,
            last_upgrade_check=_xcode_last_upgrade_check(),
            swift_packages=lock.swift_packages,
            xcframeworks=lock.xcframeworks,
        )
    except CollectError as exc:
        raise ToolchainError(str(exc)) from exc
    except IconSourceError as exc:
        raise ToolchainError(str(exc)) from exc
    except StagingError as exc:
        raise ToolchainError(str(exc)) from exc

    staging = project_root / f"{config.app_slug}-ios"
    click.echo(f"Generated {staging.relative_to(project_root)}")
    return build_slices[0]


def _xcodebuild_step7(
    xb: XcodeBuild,
    config,
    *,
    target: str,
    arch: str | None,
    team_id_flag: str | None,
    signing_identity_flag: str | None,
    export_method: str,
) -> None:
    auto_signing = config.ios.signing.auto_signing
    if target in ("simulator", "device"):
        # Effective signing identity: --signing-identity → env → pyproject.
        # The pyproject default ("Apple Development") is meant for exactly this
        # case — a device debug build.
        identity = resolve_signing_identity(config, identity_flag=signing_identity_flag)
        sim_arch = arch if target == "simulator" else None
        click.echo(f"xcodebuild build ({target}) ...")
        run_command(
            build_command(
                xb,
                target,
                arch=sim_arch,
                signing_identity=identity,
                allow_provisioning_updates=auto_signing and target == "device",
            )
        )
        return

    # --release: archive, then export a signed .ipa (spec 05 step 7).
    # Only an *explicit* --signing-identity flag or KIVYFORGE_SIGNING_IDENTITY
    # env var applies here — the pyproject default is for --device debug builds
    # and would force the wrong certificate type (Development) onto what needs
    # to be a Distribution-signed archive/export (see archive_command).
    release_identity = signing_identity_flag or os.environ.get(SIGNING_IDENTITY_ENV)
    resolved_team_id = preflight_signing(config, "release", team_id_flag=team_id_flag)
    if resolved_team_id is None:
        # preflight_signing only returns None for --simulator; unreachable here.
        raise SigningError(
            "code signing required for --release, but no team_id is set."
        )
    xb.build_dir.mkdir(parents=True, exist_ok=True)
    click.echo("xcodebuild archive ...")
    run_command(
        archive_command(
            xb,
            signing_identity=release_identity,
            allow_provisioning_updates=auto_signing,
        )
    )

    options = export_options_plist(
        method=export_method,
        team_id=resolved_team_id,
        upload_symbols=config.ios.signing.upload_symbols,
        signing_identity=release_identity,
    )
    options_path = xb.build_dir / "ExportOptions.plist"
    with open(options_path, "wb") as fh:
        plistlib.dump(options, fh)

    click.echo("xcodebuild -exportArchive ...")
    run_command(
        export_command(xb, options_path, allow_provisioning_updates=auto_signing)
    )
    click.echo(f"Exported {xb.ipa_path.relative_to(xb.project_root)}")


def _resolve_slices(
    target: str | None, arch: str | None, deployment_target: str
) -> list[BuildSlice]:
    """Slices to collect for *target*.

    A bare ``kivyforge build`` (``target is None``) collects both device and
    simulator so the "ready to open" project builds either Xcode destination —
    Xcode's default destination is usually a simulator, so collecting only the
    device slice would make the very first in-Xcode build fail. A targeted build
    collects only the slice it is about to build.

    The simulator slice defaults to the host's native arch (``--arch`` overrides):
    a single ``pip-deps-simulator`` directory holds one arch's compiled ``.so``
    files, so the right one to stage is the arch the developer's machine actually
    runs — ``x86_64`` on Intel, ``arm64`` on Apple Silicon. The lock pins both
    simulator arches; the build picks the host's.
    """
    sim_arch = arch or default_simulator_arch()
    if target is None:
        return [
            BuildSlice("device", "arm64", deployment_target),
            BuildSlice("simulator", sim_arch, deployment_target),
        ]
    return [_resolve_slice(target, arch, deployment_target)]


def _resolve_slice(
    target: str | None, arch: str | None, deployment_target: str
) -> BuildSlice:
    if target == "simulator":
        return BuildSlice(
            "simulator", arch or default_simulator_arch(), deployment_target
        )
    # device or release builds target device/arm64.
    return BuildSlice("device", "arm64", deployment_target)


def _xcode_last_upgrade_check() -> str | None:
    """LastUpgradeCheck for the installed Xcode (e.g. Xcode 26.5 -> "2650").

    Setting the generated project's ``LastUpgradeCheck`` to the running Xcode's
    version suppresses the "Update to recommended settings" banner. Returns
    ``None`` when Xcode can't be queried, in which case the generator falls back
    to its built-in constant.
    """
    from kivyforge.doctor.probe import RealProbe

    version = RealProbe().xcode_version()
    return _encode_last_upgrade_check(version) if version else None


def _encode_last_upgrade_check(version: str) -> str | None:
    """Encode an Xcode version string ("26.5", "16.2.1") as Xcode's integer
    LastUpgradeCheck code (major*100 + minor*10 + patch), or ``None``.
    """
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    if match is None:
        return None
    major, minor, patch = (int(match.group(i) or 0) for i in (1, 2, 3))
    return str(major * 100 + minor * 10 + patch)


def _load_config(pyproject: Path):
    try:
        return load_config(pyproject)
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc


def _load_lock(project_root: Path):
    path = lockfile_path(project_root)
    if not path.is_file():
        raise ToolchainError(f"no {LOCKFILE_NAME} found. Run `kivyforge lock` first.")
    try:
        return load(path)
    except LockError as exc:
        raise ToolchainError(str(exc)) from exc


# ---- run ----------------------------------------------------------------- #


def ios_run(
    project_root: Path,
    *,
    target: str,
    destination: str | None,
    no_build: bool,
) -> None:
    """Build (unless --no-build), install, and launch the app."""
    try:
        config = load_config(project_root / "pyproject.toml")
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc

    xb = XcodeBuild.from_config(config, project_root)
    derived_data = xb.build_dir / "DerivedData"

    try:
        if not no_build:
            if target == "device":
                preflight_signing(config, "device")
            prepare_build(
                config,
                project_root,
                target=target,
                arch=None,
                no_verify_lock=False,
                no_cache=False,
            )
            click.echo(f"xcodebuild build ({target}) ...")
            run_command(build_command(xb, target, derived_data_path=derived_data))

        app = product_app_path(derived_data, xb.scheme, target)
        if not app.exists():
            raise ToolchainError(
                f"built app not found at {app}.\n"
                "  Run without --no-build, or open the project in Xcode and build "
                "once to populate DerivedData."
            )

        bundle_id = config.ios_required.bundle_id
        if target == "simulator":
            _run_simulator(destination, app, bundle_id)
        else:
            _run_device(destination, app, bundle_id)
    except SigningError as exc:
        raise ToolchainError(str(exc)) from exc
    except CommandError as exc:
        raise ToolchainError(str(exc)) from exc


def ios_list_devices() -> None:
    for builder in (simctl_list, devicectl_list):
        proc = run_command(builder(), check=False)
        if proc.stdout:
            click.echo(proc.stdout)


def _run_simulator(destination: str | None, app: Path, bundle_id: str) -> None:
    device = resolve_simulator_destination(destination)
    label = f"{device.name} ({device.udid})"
    click.echo(f"Installing on simulator {label} ...")
    run_command(simctl_install(device.udid, app))
    click.echo(f"Launching {bundle_id} ...")
    run_command(simctl_launch(device.udid, bundle_id))


def _run_device(destination: str | None, app: Path, bundle_id: str) -> None:
    device = resolve_device_destination(destination)
    label = f"{device.name} ({device.identifier})"
    click.echo(f"Installing on device {label} ...")
    run_command(devicectl_install(device.identifier, app))
    click.echo(f"Launching {bundle_id} ...")
    run_command(devicectl_launch(device.identifier, bundle_id))


# ---- package ------------------------------------------------------------- #


def ios_package(
    project_root: Path,
    *,
    team_id: str | None,
    signing_identity: str | None,
    export_method: str,
    no_verify_lock: bool,
    no_cache: bool,
) -> None:
    """Build the release archive and export a signed ``.ipa``."""
    config = _load_config(project_root / "pyproject.toml")
    try:
        prepare_build(
            config,
            project_root,
            target="release",
            arch=None,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )
        xb = XcodeBuild.from_config(config, project_root)
        _xcodebuild_step7(
            xb,
            config,
            target="release",
            arch=None,
            team_id_flag=team_id,
            signing_identity_flag=signing_identity,
            export_method=export_method,
        )
    except (CommandError, SigningError) as exc:
        raise ToolchainError(str(exc)) from exc


# ---- open ---------------------------------------------------------------- #


def ios_open(project_root: Path) -> None:
    """Open ``<app>-ios/<app>.xcodeproj`` in Xcode."""
    try:
        config = load_config(project_root / "pyproject.toml")
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc

    slug = config.app_slug
    xcodeproj = project_root / f"{slug}-ios" / f"{slug}.xcodeproj"
    if not xcodeproj.exists():
        raise ToolchainError(
            f"{xcodeproj.name} does not exist yet.\n"
            "  Run `kivyforge build` first to generate the Xcode project."
        )
    try:
        run_command(open_command(xcodeproj))
    except CommandError as exc:
        raise ToolchainError(str(exc)) from exc


# ---- status -------------------------------------------------------------- #


def ios_status(project_root: Path) -> None:
    """Show app identity, Python version, lock sync, and build state."""
    pyproject = project_root / "pyproject.toml"
    try:
        config = load_config(pyproject)
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc

    ios = config.ios_required
    click.echo(f"App:        {config.display_name}  ({ios.bundle_id})")
    click.echo(f"Python:     {ios.python_version or '(unset)'}")
    click.echo(f"Lock:       {_lock_state(project_root, pyproject)}")

    click.echo("Build:")
    build_dir = project_root / f"{config.app_slug}-ios" / "build" / "DerivedData"
    sim_label = f"simulator ({default_simulator_arch()})"
    for label, target in ((sim_label, "simulator"), ("device", "device")):
        app = product_app_path(build_dir, config.app_slug, target)
        click.echo(f"  {label:<20}{_build_state(app)}")


def _lock_state(project_root: Path, pyproject: Path) -> str:
    lockfile = project_root / LOCKFILE_NAME
    if not lockfile.is_file():
        return "missing (run `kivyforge lock`)"
    try:
        lock = load(lockfile)
    except LockError:
        return "unreadable (run `kivyforge lock`)"
    if is_in_sync(lock, pyproject.read_text("utf-8")):
        return "in sync"
    return "out of date (run `kivyforge lock`)"


def _build_state(app: Path) -> str:
    if not app.exists():
        return "not built"
    age = time.time() - app.stat().st_mtime
    return f"last built {_humanize(age)}"


def _humanize(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = seconds // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"
