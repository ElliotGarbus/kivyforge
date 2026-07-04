"""macOS dispatch for the shared ``build`` / ``run`` / ``package`` verbs.

Keeps the macOS ``.app`` flow out of the (iOS/Xcode-centric) verb modules: each
verb resolves the target platform and, when it is macOS, calls in here. Loads the
macOS config + ``pylock.macos.toml``, runs the drift check, and drives the
``.app`` bundler.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from ..config import ConfigError, load_config
from ..lock.macos import MacosLockfile
from ..lock.macos import load as load_macos_lock
from ..lock.reader import LockError, is_in_sync
from ..macos import AppBundleError
from ..macos.bundle import build_app_bundle
from ..platforms import HostCapabilityError, get_platform
from ._common import ToolchainError, lockfile_path_for


def macos_build(
    project_root: Path,
    *,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
    sign: bool = True,
) -> Path:
    """Assemble (and ad-hoc sign) the macOS ``.app``; return its path."""
    _require_macos_host()
    config = _load_config(project_root)
    lock = _load_lock(project_root)

    pyproject = project_root / "pyproject.toml"
    if not no_verify_lock and not is_in_sync(lock, pyproject.read_text("utf-8")):
        raise ToolchainError(
            f"{lockfile_path_for('macos').name} is out of date with "
            "pyproject.toml.\n"
            "  Run `kivyforge lock -p macos` to regenerate it (or pass "
            "--no-verify-lock to build against the stale lock anyway)."
        )

    try:
        app = build_app_bundle(
            config,
            lock,
            project_root,
            arch=arch,
            sign=sign,
            no_cache=no_cache,
        )
    except AppBundleError as exc:
        raise ToolchainError(str(exc)) from exc

    click.echo(f"Built {app.relative_to(project_root)}")
    return app


def macos_run(
    project_root: Path,
    *,
    arch: str | None,
    no_build: bool,
) -> None:
    """Build (unless --no-build) and launch the ``.app`` in the foreground."""
    if no_build:
        _require_macos_host()
        config = _load_config(project_root)
        app = project_root / "build" / "macos" / f"{config.display_name}.app"
        if not app.exists():
            raise ToolchainError(
                f"no built app at {app.relative_to(project_root)}; run without "
                "--no-build first."
            )
    else:
        app = macos_build(project_root, arch=arch, no_verify_lock=False, no_cache=False)

    executable = app / "Contents" / "MacOS" / _executable_name(app)
    click.echo(f"Launching {app.name} ...")
    # Foreground exec (not `open`) so the dev sees stdout/stderr + tracebacks,
    # the desktop analog of the simulator console.
    proc = subprocess.run([str(executable)])
    if proc.returncode != 0:
        raise ToolchainError(f"{app.name} exited with status {proc.returncode}.")


def macos_package(
    project_root: Path,
    *,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
) -> Path:
    """Produce the finished, ad-hoc-signed ``.app`` distributable."""
    app = macos_build(
        project_root,
        arch=arch,
        no_verify_lock=no_verify_lock,
        no_cache=no_cache,
        sign=True,
    )
    click.echo(
        f"Packaged {app.relative_to(project_root)} (ad-hoc signed).\n"
        "  Distribute the .app directly, or wrap it in a .dmg with an external "
        "tool (see docs)."
    )
    return app


def _executable_name(app: Path) -> str:
    macos_dir = app / "Contents" / "MacOS"
    entries = (
        [p for p in macos_dir.iterdir() if p.is_file()] if macos_dir.is_dir() else []
    )
    if not entries:
        raise ToolchainError(f"{app.name} has no launcher in Contents/MacOS.")
    return entries[0].name


def _require_macos_host() -> None:
    try:
        get_platform("macos").check_host_capability()
    except HostCapabilityError as exc:
        raise ToolchainError(str(exc)) from exc


def _load_config(project_root: Path):
    try:
        return load_config(
            project_root / "pyproject.toml", require_ios=False, require_macos=True
        )
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc


def _load_lock(project_root: Path) -> MacosLockfile:
    path = lockfile_path_for("macos", project_root)
    if not path.is_file():
        raise ToolchainError(
            f"no {path.name} found. Run `kivyforge lock -p macos` first."
        )
    try:
        return load_macos_lock(path)
    except LockError as exc:
        raise ToolchainError(str(exc)) from exc
