"""Linux dispatch for the shared ``build`` / ``run`` / ``package`` verbs.

Keeps the Linux AppDir flow out of the (iOS/Xcode-centric) verb modules: each
verb resolves the target platform and, when it is Linux, calls in here. Loads the
Linux config + ``pylock.linux.toml``, runs the drift check, and drives the
AppDir bundler.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from kivyforge.build_outcome import (
    ArtifactKind,
    BuildEvents,
    BuildOutcome,
    OutcomeBuilder,
)
from kivyforge.cli._common import ECHO_EVENTS, ToolchainError, lockfile_path_for
from kivyforge.config import ConfigError, load_config
from kivyforge.lock.reader import LockError, is_in_sync
from kivyforge.report import failures
from kivyforge.status import BuildArtifact, LockState, LockStatus, StatusReport

from .. import HostCapabilityError, get_platform
from . import AppDirError
from .appimage import build_appimage
from .bundle import build_appdir, resolve_assembly_arch
from .lock import LinuxLockfile
from .lock import load as load_linux_lock


def linux_build(
    project_root: Path,
    *,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
    events: BuildEvents = ECHO_EVENTS,
) -> BuildOutcome:
    """Assemble the Linux AppDir."""
    outcome = OutcomeBuilder(events.on_artifact)
    _require_linux_host()
    config, lock = _load_and_verify(project_root, no_verify_lock)
    appdir = _assemble(
        config,
        lock,
        project_root,
        arch=arch,
        no_cache=no_cache,
        release=False,
        events=events,
    )
    rel = appdir.relative_to(project_root)
    events.on_line(f"Built {rel}")
    outcome.add(rel, ArtifactKind.FOLDER)
    return outcome.finish()


def linux_package(
    project_root: Path,
    *,
    fmt: str,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
    events: BuildEvents = ECHO_EVENTS,
) -> BuildOutcome:
    """Produce the distributable artifact: an ``.AppImage`` (default) or the AppDir."""
    outcome = OutcomeBuilder(events.on_artifact)
    _require_linux_host()
    config, lock = _load_and_verify(project_root, no_verify_lock)
    target_arch = _resolve_arch(lock, arch)
    appdir = _assemble(
        config,
        lock,
        project_root,
        arch=target_arch,
        no_cache=no_cache,
        release=True,
        events=events,
    )

    if fmt == "folder":
        rel = appdir.relative_to(project_root)
        events.on_line(f"Packaged {rel} (AppDir folder).")
        outcome.add(rel, ArtifactKind.FOLDER)
        return outcome.finish(
            notes=(
                "  Run it with ./AppRun, or `kivyforge package -f appimage` for a "
                "single-file distributable.",
            )
        )

    output = (
        project_root
        / "dist"
        / "linux"
        / f"{config.app_slug}-{config.project.version}-{target_arch}.AppImage"
    )
    try:
        result = build_appimage(
            appdir,
            output,
            target_arch,
            project_root=project_root,
            no_cache=no_cache,
            echo=events.on_progress,
        )
    except AppDirError as exc:
        raise ToolchainError.wrap(exc) from exc

    rel = result.relative_to(project_root)
    events.on_line(f"Packaged {rel}.")
    outcome.add(rel, ArtifactKind.APPIMAGE)
    return outcome.finish(
        notes=(
            "  Distribute the .AppImage directly (chmod +x, then run). The host "
            "needs glibc >= the effective floor, libGL/libEGL, and an X11/Wayland "
            "session.\n"
            "  No libfuse2 package is required (static-FUSE runtime embedded). If "
            "the host lacks kernel FUSE (/dev/fuse) — e.g. some containers/CI — "
            "run it with --appimage-extract-and-run (or APPIMAGE_EXTRACT_AND_RUN=1).",
        )
    )


def _assemble(
    config, lock, project_root, *, arch, no_cache, release, events=ECHO_EVENTS
) -> Path:
    try:
        return build_appdir(
            config,
            lock,
            project_root,
            arch=arch,
            no_cache=no_cache,
            release=release,
            echo=events.on_progress,
            note=events.note,
        )
    except AppDirError as exc:
        raise ToolchainError.wrap(exc) from exc


def _resolve_arch(lock: LinuxLockfile, arch: str | None) -> str:
    try:
        return resolve_assembly_arch(lock.archs, arch)
    except AppDirError as exc:
        raise ToolchainError.wrap(exc) from exc


def _load_and_verify(
    project_root: Path, no_verify_lock: bool
) -> tuple[object, LinuxLockfile]:
    config = _load_config(project_root)
    lock = _load_lock(project_root)
    pyproject = project_root / "pyproject.toml"
    if not no_verify_lock and not is_in_sync(lock, pyproject.read_text("utf-8")):
        raise ToolchainError(
            f"{lockfile_path_for('linux').name} is out of date with "
            "pyproject.toml.\n"
            "  Run `kivyforge lock -p linux` to regenerate it (or pass "
            "--no-verify-lock to build against the stale lock anyway).",
            **failures.LOCK_DRIFT,
        )
    return config, lock


def linux_run(
    project_root: Path,
    *,
    arch: str | None,
    no_build: bool,
) -> None:
    """Build (unless --no-build) and launch the app via ``AppRun`` in foreground."""
    if no_build:
        _require_linux_host()
        config = _load_config(project_root)
        appdir = project_root / "build" / "linux" / f"{config.display_name}.AppDir"
        if not appdir.exists():
            raise ToolchainError(
                f"no built AppDir at {appdir.relative_to(project_root)}; run "
                "without --no-build first."
            )
    else:
        built = linux_build(
            project_root, arch=arch, no_verify_lock=False, no_cache=False
        )
        appdir = project_root / built.artifacts[0].path

    apprun = appdir / "AppRun"
    click.echo(f"Launching {appdir.name} ...")
    # Foreground exec so the dev sees stdout/stderr + tracebacks.
    proc = subprocess.run([str(apprun)])
    if proc.returncode != 0:
        raise ToolchainError(f"{appdir.name} exited with status {proc.returncode}.")


def linux_status(project_root: Path) -> StatusReport:
    """Gather app identity, Python version, lock sync, and build state."""
    config = _load_config(project_root)
    linux = config.linux_required
    appdir = project_root / "build" / "linux" / f"{config.display_name}.AppDir"
    return StatusReport(
        platform="linux",
        app_name=config.display_name,
        app_id=linux.app_id,
        python_version=linux.python_version or "(unset)",
        lock=_lock_status(project_root),
        artifacts=(BuildArtifact.probe(appdir),),
    )


def _lock_status(project_root: Path) -> LockStatus:
    relock = "kivyforge lock -p linux"
    path = lockfile_path_for("linux", project_root)
    if not path.is_file():
        return LockStatus(LockState.MISSING, relock)
    try:
        lock = load_linux_lock(path)
    except LockError:
        return LockStatus(LockState.UNREADABLE, relock)
    pyproject = project_root / "pyproject.toml"
    in_sync = is_in_sync(lock, pyproject.read_text("utf-8"))
    return LockStatus(LockState.IN_SYNC if in_sync else LockState.OUT_OF_DATE, relock)


def _require_linux_host() -> None:
    try:
        get_platform("linux").check_host_capability()
    except HostCapabilityError as exc:
        raise ToolchainError(str(exc), **failures.HOST_INCAPABLE) from exc


def _load_config(project_root: Path):
    try:
        return load_config(
            project_root / "pyproject.toml", require_ios=False, require_linux=True
        )
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc


def _load_lock(project_root: Path) -> LinuxLockfile:
    path = lockfile_path_for("linux", project_root)
    if not path.is_file():
        raise ToolchainError(
            f"no {path.name} found. Run `kivyforge lock -p linux` first.",
            **failures.LOCK_MISSING,
        )
    try:
        return load_linux_lock(path)
    except LockError as exc:
        raise ToolchainError(str(exc), **failures.LOCK_UNREADABLE) from exc
