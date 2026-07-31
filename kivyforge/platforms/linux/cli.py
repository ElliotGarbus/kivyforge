"""Linux dispatch for the shared ``build`` / ``run`` / ``package`` verbs.

Keeps the Linux AppDir flow out of the (iOS/Xcode-centric) verb modules: each
verb resolves the target platform and, when it is Linux, calls in here. Loads the
Linux config + ``pylock.linux.toml``, runs the drift check, and drives the
AppDir bundler.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import click

from kivyforge.cli._common import ToolchainError, lockfile_path_for
from kivyforge.config import ConfigError, load_config
from kivyforge.lock.reader import LockError, is_in_sync

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
) -> Path:
    """Assemble the Linux AppDir; return its path."""
    _require_linux_host()
    config, lock = _load_and_verify(project_root, no_verify_lock)
    appdir = _assemble(
        config, lock, project_root, arch=arch, no_cache=no_cache, release=False
    )
    click.echo(f"Built {appdir.relative_to(project_root)}")
    return appdir


def linux_package(
    project_root: Path,
    *,
    fmt: str,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
) -> Path:
    """Produce the distributable artifact: an ``.AppImage`` (default) or the AppDir."""
    _require_linux_host()
    config, lock = _load_and_verify(project_root, no_verify_lock)
    target_arch = _resolve_arch(lock, arch)
    appdir = _assemble(
        config, lock, project_root, arch=target_arch, no_cache=no_cache, release=True
    )

    if fmt == "folder":
        click.echo(
            f"Packaged {appdir.relative_to(project_root)} (AppDir folder).\n"
            "  Run it with ./AppRun, or `kivyforge package -f appimage` for a "
            "single-file distributable."
        )
        return appdir

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
            echo=click.echo,
        )
    except AppDirError as exc:
        raise ToolchainError(str(exc)) from exc

    click.echo(
        f"Packaged {result.relative_to(project_root)}.\n"
        "  Distribute the .AppImage directly (chmod +x, then run). The host needs "
        "glibc >= the effective floor, libGL/libEGL, and an X11/Wayland "
        "session.\n"
        "  No libfuse2 package is required (static-FUSE runtime embedded). If the "
        "host lacks kernel FUSE (/dev/fuse) — e.g. some containers/CI — run it "
        "with --appimage-extract-and-run (or APPIMAGE_EXTRACT_AND_RUN=1)."
    )
    return result


def _assemble(config, lock, project_root, *, arch, no_cache, release) -> Path:
    try:
        return build_appdir(
            config, lock, project_root, arch=arch, no_cache=no_cache, release=release
        )
    except AppDirError as exc:
        raise ToolchainError(str(exc)) from exc


def _resolve_arch(lock: LinuxLockfile, arch: str | None) -> str:
    try:
        return resolve_assembly_arch(lock.archs, arch)
    except AppDirError as exc:
        raise ToolchainError(str(exc)) from exc


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
            "--no-verify-lock to build against the stale lock anyway)."
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
        appdir = linux_build(
            project_root, arch=arch, no_verify_lock=False, no_cache=False
        )

    apprun = appdir / "AppRun"
    click.echo(f"Launching {appdir.name} ...")
    # Foreground exec so the dev sees stdout/stderr + tracebacks.
    proc = subprocess.run([str(apprun)])
    if proc.returncode != 0:
        raise ToolchainError(f"{appdir.name} exited with status {proc.returncode}.")


def linux_status(project_root: Path) -> None:
    """Show app identity, Python version, lock sync, and build state."""
    config = _load_config(project_root)
    linux = config.linux_required
    click.echo(f"App:        {config.display_name}  ({linux.app_id})")
    click.echo(f"Python:     {linux.python_version or '(unset)'}")
    click.echo(f"Lock:       {_lock_state(project_root)}")

    appdir = project_root / "build" / "linux" / f"{config.display_name}.AppDir"
    click.echo(f"Build:      {_build_state(appdir)}")


def _lock_state(project_root: Path) -> str:
    path = lockfile_path_for("linux", project_root)
    if not path.is_file():
        return "missing (run `kivyforge lock -p linux`)"
    try:
        lock = load_linux_lock(path)
    except LockError:
        return "unreadable (run `kivyforge lock -p linux`)"
    pyproject = project_root / "pyproject.toml"
    if is_in_sync(lock, pyproject.read_text("utf-8")):
        return "in sync"
    return "out of date (run `kivyforge lock -p linux`)"


def _build_state(appdir: Path) -> str:
    if not appdir.exists():
        return "not built"
    age = time.time() - appdir.stat().st_mtime
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


def _require_linux_host() -> None:
    try:
        get_platform("linux").check_host_capability()
    except HostCapabilityError as exc:
        raise ToolchainError(str(exc)) from exc


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
            f"no {path.name} found. Run `kivyforge lock -p linux` first."
        )
    try:
        return load_linux_lock(path)
    except LockError as exc:
        raise ToolchainError(str(exc)) from exc
