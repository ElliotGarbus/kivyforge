"""iOS build/run/package/open/status logic (specs 05/06).

Extracted from the shared ``cli`` verbs so all iOS-specific behavior lives behind
the iOS backend, symmetric with ``platforms/macos/cli.py`` and
``platforms/linux/cli.py``. The verb modules stay thin dispatchers.
"""

from __future__ import annotations

import os
import plistlib
import re
from pathlib import Path

import click

from kivyforge.artifacts.collect import CollectError, collect_artifacts
from kivyforge.artifacts.wheels import BuildSlice
from kivyforge.build_outcome import (
    ArtifactKind,
    BuildEvents,
    BuildOutcome,
    OutcomeBuilder,
)
from kivyforge.cli._common import (
    ECHO_EVENTS,
    LOCKFILE_NAME,
    ToolchainError,
    lockfile_path,
)
from kivyforge.config import ConfigError, load_config
from kivyforge.config.icons import IconSourceError
from kivyforge.lock import LockError, is_in_sync
from kivyforge.platforms.base import HostCapabilityError
from kivyforge.report import diagnostics
from kivyforge.status import BuildArtifact, LockState, LockStatus, StatusReport

from .entitlements import preflight_entitlements
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


def _ungranted_warning(keys: list[str]) -> str:
    """Non-fatal note for entitlements the pinned profile does not grant.

    Only reachable under ``auto_signing = true``, where ``xcodebuild`` gets
    ``-allowProvisioningUpdates`` and may register the capability mid-build —
    so these are named rather than treated as a certain failure.
    """
    return (
        "Warning: entitlements not granted by the pinned provisioning profile: "
        f"{', '.join(keys)}\n"
        "  auto_signing is on, so Xcode may register them at build time."
    )


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
    events: BuildEvents = ECHO_EVENTS,
) -> BuildOutcome:
    """Download artifacts, generate the Xcode project, and optionally build it."""
    outcome = OutcomeBuilder(events.on_artifact)
    _require_macos_host()
    # Signing pre-flight runs before any artifact work so --device/--release
    # fail fast on a missing team_id (spec 05 step 7).
    config = _load_config(project_root / "pyproject.toml")
    resolved_team_id: str | None = None
    if target is not None:
        try:
            resolved_team_id = preflight_signing(config, target, team_id_flag=team_id)
            ungranted = preflight_entitlements(config, project_root, target)
        except SigningError as exc:
            raise ToolchainError(str(exc)) from exc
        if ungranted:
            click.echo(_ungranted_warning(ungranted), err=True)
            events.note(
                diagnostics.ENTITLEMENTS_UNGRANTED,
                "entitlements not granted by the pinned provisioning profile: "
                f"{', '.join(ungranted)}",
            )

    prepare_build(
        config,
        project_root,
        target=target,
        arch=arch,
        no_verify_lock=no_verify_lock,
        no_cache=no_cache,
        team_id=resolved_team_id,
        events=events,
    )
    xb = XcodeBuild.from_config(config, project_root)
    outcome.add(xb.staging.relative_to(project_root), ArtifactKind.PROJECT)

    if target is None:
        events.on_line(
            "Project ready. Open it with `kivyforge open` or build with "
            "`kivyforge build --simulator`."
        )
        return outcome.finish()

    try:
        _xcodebuild_step7(
            xb,
            config,
            target=target,
            arch=arch,
            team_id_flag=team_id,
            signing_identity_flag=signing_identity,
            export_method=export_method,
            events=events,
            outcome=outcome,
        )
    except CommandError as exc:
        raise _tool_failure(exc, events) from exc
    except SigningError as exc:
        raise ToolchainError(str(exc)) from exc
    return outcome.finish()


def _tool_failure(exc: CommandError, events: BuildEvents) -> ToolchainError:
    """Split a failed build tool into its log (progress) and a summary (the error).

    xcodebuild's transcript can run to megabytes. It is build log, so it goes to
    stderr with the rest of the progress; the error a --json consumer reads says
    what failed, not everything it printed on the way.
    """
    if exc.output:
        events.on_progress(exc.output.rstrip())
    tool = Path(exc.argv[0]).name if exc.argv else "command"
    actions = [a for a in ("build", "archive", "-exportArchive") if a in exc.argv]
    task = f" {actions[0]}" if tool == "xcodebuild" and actions else ""
    return ToolchainError(
        f"{tool}{task} failed (exit {exc.returncode}); its output is above."
    )


def prepare_build(
    config,
    project_root: Path,
    *,
    target: str | None,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
    team_id: str | None = None,
    events: BuildEvents = ECHO_EVENTS,
) -> BuildSlice:
    """Run build steps 1-6 (drift, artifact collection, project generation).

    Shared by ``kivyforge build`` and ``kivyforge run``. A bare ``toolchain
    build`` (no target) collects both the device and simulator pip-deps slices
    so the generated project builds either Xcode destination without re-running
    the toolchain; a targeted build collects only its slice. Returns the primary
    slice (the targeted one, or the device slice for a bare build).

    Prints ``Generated`` but records nothing: whether the project is a product
    depends on the verb, so the caller decides.
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
    # Only `kivyforge package` (target="release") gets byte-compiled/stripped
    # app sources + pip-deps; `build`/`run` always keep readable .py, matching
    # every other platform's release-only default.
    release = target == "release"
    try:
        layout = create_staging(
            config,
            project_root,
            release=release,
            python_version=lock.python_xcframework.version if release else None,
            echo=events.on_progress,
            note=events.note,
        )
        events.on_progress(f"Collecting artifacts for {tags} ...")
        collect_artifacts(
            lock,
            layout,
            build_slices=build_slices,
            project_root=project_root,
            no_cache=no_cache,
            release=release,
            build_settings=config.ios.python_build_settings,
            echo=events.on_progress,
            note=events.note,
        )
        materialize_project(
            config,
            project_root,
            layout=layout,
            python_version=lock.python_xcframework.version,
            last_upgrade_check=_xcode_last_upgrade_check(),
            swift_packages=lock.swift_packages,
            xcframeworks=lock.xcframeworks,
            team_id=team_id,
        )
    except CollectError as exc:
        raise ToolchainError(str(exc)) from exc
    except IconSourceError as exc:
        raise ToolchainError(str(exc)) from exc
    except StagingError as exc:
        raise ToolchainError(str(exc)) from exc

    staging = project_root / f"{config.app_slug}-ios"
    events.on_line(f"Generated {staging.relative_to(project_root)}")
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
    events: BuildEvents,
    outcome: OutcomeBuilder,
) -> None:
    auto_signing = config.ios.signing.auto_signing
    if target in ("simulator", "device"):
        # Effective signing identity: --signing-identity → env → pyproject.
        # The pyproject default ("Apple Development") is meant for exactly this
        # case — a device debug build.
        identity = resolve_signing_identity(config, identity_flag=signing_identity_flag)
        sim_arch = arch if target == "simulator" else None
        # Pinned to the project-local DerivedData, as `run` does, so the .app
        # has a project-relative path instead of landing in Xcode's global cache.
        derived_data = xb.build_dir / "DerivedData"
        events.on_progress(f"xcodebuild build ({target}) ...")
        run_command(
            build_command(
                xb,
                target,
                arch=sim_arch,
                derived_data_path=derived_data,
                signing_identity=identity,
                allow_provisioning_updates=auto_signing and target == "device",
            )
        )
        app = _require_product(product_app_path(derived_data, xb.scheme, target), xb)
        rel = app.relative_to(xb.project_root)
        events.on_line(f"Built {rel}")
        outcome.add(rel, ArtifactKind.APP)
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
    events.on_progress("xcodebuild archive ...")
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

    events.on_progress("xcodebuild -exportArchive ...")
    run_command(
        export_command(xb, options_path, allow_provisioning_updates=auto_signing)
    )
    ipa = _require_product(xb.ipa_path, xb)
    rel = ipa.relative_to(xb.project_root)
    events.on_line(f"Exported {rel}")
    outcome.add(rel, ArtifactKind.IPA)


def _require_product(path: Path, xb: XcodeBuild) -> Path:
    """Confirm xcodebuild actually produced the product we are about to announce."""
    if not path.exists():
        raise ToolchainError(
            "xcodebuild reported success but no product is at "
            f"{path.relative_to(xb.project_root)}.\n"
            "  Check the scheme's build settings (PRODUCT_NAME, the export "
            "method) and file a kivyforge issue if they are the generated defaults."
        )
    return path


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


def _require_macos_host() -> None:
    """Gate the Xcode-bound verbs (mirrors the macOS/Linux/Windows backends).

    ``IosPlatform.check_host_capability`` has always described this rule; until
    now nothing called it, so an off-macOS invocation failed later with
    whatever error xcodebuild or SPM happened to raise first.
    """
    from kivyforge.platforms import get_platform

    try:
        get_platform("ios").check_host_capability()
    except HostCapabilityError as exc:
        raise ToolchainError(str(exc)) from exc


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
    _require_macos_host()
    try:
        config = load_config(project_root / "pyproject.toml")
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc

    xb = XcodeBuild.from_config(config, project_root)
    derived_data = xb.build_dir / "DerivedData"

    try:
        if not no_build:
            resolved_team_id: str | None = None
            if target == "device":
                resolved_team_id = preflight_signing(config, "device")
                # run signs via its own xcodebuild invocation rather than going
                # through ios_build, so the entitlements check must repeat here.
                # --no-build installs an already-signed .app: nothing to pre-empt.
                ungranted = preflight_entitlements(config, project_root, "device")
                if ungranted:
                    click.echo(_ungranted_warning(ungranted), err=True)
            prepare_build(
                config,
                project_root,
                target=target,
                arch=None,
                no_verify_lock=False,
                no_cache=False,
                team_id=resolved_team_id,
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
    events: BuildEvents = ECHO_EVENTS,
) -> BuildOutcome:
    """Build the release archive and export a signed ``.ipa``.

    Only the ``.ipa`` is recorded: the generated project and the ``.xcarchive``
    are intermediates of ``package``, however visible the former's line is.
    """
    outcome = OutcomeBuilder(events.on_artifact)
    _require_macos_host()
    config = _load_config(project_root / "pyproject.toml")
    try:
        # Resolve before prepare_build so the generated .xcodeproj carries the
        # right DEVELOPMENT_TEAM the first time — _xcodebuild_step7 resolves
        # again for the export step, which is harmless (same three sources,
        # same answer) but the project must already have it before archiving.
        resolved_team_id = preflight_signing(config, "release", team_id_flag=team_id)
        prepare_build(
            config,
            project_root,
            target="release",
            arch=None,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
            team_id=resolved_team_id,
            events=events,
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
            events=events,
            outcome=outcome,
        )
    except CommandError as exc:
        raise _tool_failure(exc, events) from exc
    except SigningError as exc:
        raise ToolchainError(str(exc)) from exc
    return outcome.finish()


# ---- open ---------------------------------------------------------------- #


def ios_open(project_root: Path) -> None:
    """Open ``<app>-ios/<app>.xcodeproj`` in Xcode."""
    _require_macos_host()
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


def ios_status(project_root: Path) -> StatusReport:
    """Gather app identity, Python version, lock sync, and build state."""
    pyproject = project_root / "pyproject.toml"
    try:
        config = load_config(pyproject)
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc

    ios = config.ios_required
    build_dir = project_root / f"{config.app_slug}-ios" / "build" / "DerivedData"
    # Two slices, because a green simulator build says nothing about the device
    # one -- signing and provisioning only apply to the latter.
    slices = (
        (f"simulator ({default_simulator_arch()})", "simulator"),
        ("device", "device"),
    )
    return StatusReport(
        platform="ios",
        app_name=config.display_name,
        app_id=ios.bundle_id,
        python_version=ios.python_version or "(unset)",
        lock=_lock_status(project_root, pyproject),
        artifacts=tuple(
            BuildArtifact.probe(
                product_app_path(build_dir, config.app_slug, target), label
            )
            for label, target in slices
        ),
    )


def _lock_status(project_root: Path, pyproject: Path) -> LockStatus:
    # No -p: iOS is the default target, and the shorter command is the one the
    # iOS docs have always shown.
    relock = "kivyforge lock"
    lockfile = project_root / LOCKFILE_NAME
    if not lockfile.is_file():
        return LockStatus(LockState.MISSING, relock)
    try:
        lock = load(lockfile)
    except LockError:
        return LockStatus(LockState.UNREADABLE, relock)
    in_sync = is_in_sync(lock, pyproject.read_text("utf-8"))
    return LockStatus(LockState.IN_SYNC if in_sync else LockState.OUT_OF_DATE, relock)
