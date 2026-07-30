"""Windows dispatch for the shared ``build`` / ``run`` / ``package`` verbs.

Keeps the Windows onedir flow out of the (iOS/Xcode-centric) verb modules: each
verb resolves the target platform and, when it is Windows, calls in here. Loads
the Windows config + ``pylock.windows.toml``, runs the drift check, and drives
the onedir bundler. The onedir folder is both the ``run`` target and — copied to
``dist/windows`` — the ``package`` output (installers stay external).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import click

from kivyforge.cli._common import ToolchainError, lockfile_path_for
from kivyforge.config import ConfigError, load_config
from kivyforge.lock.reader import LockError, is_in_sync

from .. import HostCapabilityError, get_platform
from . import WindowsBundleError
from .bundle import (
    build_onedir,
    bundle_dir_name,
    launcher_name,
    onedir_path,
    resolve_assembly_arch,
)
from .fsswap import discard_reserved, reserve_previous, restore_previous
from .lock import WindowsLockfile
from .lock import load as load_windows_lock
from .signing import select_signer

# Never copy build cache, VCS metadata, or editor droppings into the shipped
# dist tree. The onedir bundle is assembled clean, so this is defense in depth
# (and covers a build/ dir a user pointed packaging at directly).
_PACKAGE_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".git",
    ".gitignore",
    ".gitattributes",
    ".svn",
    ".hg",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".idea",
    ".vscode",
    "*.swp",
    "*~",
)


def windows_build(
    project_root: Path,
    *,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
) -> Path:
    """Assemble the Windows onedir bundle; return its path."""
    _require_windows_host()
    config, lock = _load_and_verify(project_root, no_verify_lock)
    bundle = _assemble(
        config, lock, project_root, arch=arch, no_cache=no_cache, release=False
    )
    click.echo(f"Built {bundle.relative_to(project_root)}")
    return bundle


def windows_package(
    project_root: Path,
    *,
    fmt: str,
    arch: str | None,
    no_verify_lock: bool,
    no_cache: bool,
) -> Path:
    """Produce the distributable: the onedir folder copied to ``dist/windows``.

    ``folder`` is the only Windows package format (installers stay external). The
    copied tree is the portable, run-from-folder distributable.
    """
    _require_windows_host()
    config, lock = _load_and_verify(project_root, no_verify_lock)
    target_arch = _resolve_arch(lock, arch)
    bundle = _assemble(
        config, lock, project_root, arch=target_arch, no_cache=no_cache, release=True
    )

    # The dist folder name matches the build tree: the display_name run through
    # the Windows filename sanitizer (windows-spec), not the raw project.name.
    dest = (
        project_root
        / "dist"
        / "windows"
        / f"{bundle_dir_name(config)}-{config.project.version}-{target_arch}"
    )
    # Reserve any prior package and keep it until *signing* also succeeds, so a
    # signer failure (missing cert, timestamp outage) rolls back to the previous
    # known-good artifact rather than leaving a half-baked unsigned tree in place.
    trash = _stage_dist_copy(bundle, dest)
    try:
        # Signing (when configured) targets the dist copy only, after the resource
        # patch (done at build) and before any external installer. The build tree
        # stays unsigned as the dev-run target.
        signed = _sign_launcher(config, dest)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        restore_previous(trash, dest)
        raise
    discard_reserved(trash)

    note = (
        "signed + timestamped"
        if signed
        else "unsigned (configure [tool.kivy.windows.signing] to sign)"
    )
    click.echo(
        f"Packaged {dest.relative_to(project_root)} (onedir folder, {note}).\n"
        f"  Run it by double-clicking {launcher_name(config)}, or zip the folder "
        "to distribute. An installer is an external step."
    )
    return dest


def windows_run(
    project_root: Path,
    *,
    arch: str | None,
    no_build: bool,
) -> None:
    """Build (unless --no-build) and launch the app ``.exe`` in the foreground."""
    if no_build:
        _require_windows_host()
        config = _load_config(project_root)
        bundle = onedir_path(config, project_root)
        if not bundle.exists():
            raise ToolchainError(
                f"no built bundle at {bundle.relative_to(project_root)}; run "
                "without --no-build first."
            )
    else:
        config = _load_config(project_root)
        bundle = windows_build(
            project_root, arch=arch, no_verify_lock=False, no_cache=False
        )

    exe = bundle / launcher_name(config)
    click.echo(f"Launching {bundle.name} ...")
    # Foreground: the launcher attaches to this console so the dev sees
    # stdout/stderr + tracebacks (the Phase 3 console handoff).
    proc = subprocess.run([str(exe)])
    if proc.returncode != 0:
        raise ToolchainError(f"{bundle.name} exited with status {proc.returncode}.")


def windows_status(project_root: Path) -> None:
    """Show app identity, Python version, lock sync, and build state."""
    config = _load_config(project_root)
    windows = config.windows_required
    click.echo(f"App:        {config.display_name}  ({windows.app_id})")
    click.echo(f"Python:     {windows.python_version or '(unset)'}")
    click.echo(f"Lock:       {_lock_state(project_root)}")
    click.echo(f"Build:      {_build_state(onedir_path(config, project_root))}")


def _assemble(config, lock, project_root, *, arch, no_cache, release) -> Path:
    try:
        return build_onedir(
            config, lock, project_root, arch=arch, no_cache=no_cache, release=release
        )
    except WindowsBundleError as exc:
        raise ToolchainError(str(exc)) from exc


def _resolve_arch(lock: WindowsLockfile, arch: str | None) -> str:
    try:
        return resolve_assembly_arch(lock.archs, arch)
    except WindowsBundleError as exc:
        raise ToolchainError(str(exc)) from exc


def _sign_launcher(config, dest: Path) -> bool:
    """Sign the launcher in the dist copy when signing is configured.

    Returns whether the artifact was signed. Translates any signing failure into
    a :class:`ToolchainError` so ``package`` reports it cleanly.
    """
    signer = select_signer(config.windows_required.signing)
    if not signer.configured:
        return False
    exe = dest / launcher_name(config)
    try:
        signer.sign([exe])
    except WindowsBundleError as exc:
        raise ToolchainError(str(exc)) from exc
    return True


def _stage_dist_copy(bundle: Path, dest: Path) -> Path | None:
    """Copy *bundle* into *dest*, returning the reserved previous tree (or None).

    Copies **directly into the final location**: like the build step, a freshly
    written tree cannot be reliably renamed on Windows (the antivirus scanner
    holds new files open), so temp-dir + rename is not viable. Any previous dist
    copy is reserved first and restored if the copy fails, so a broken package
    never destroys a working one.

    The reserved previous tree is **not** discarded here: the caller must call
    :func:`discard_reserved` only after every later step (e.g. signing) succeeds,
    or :func:`restore_previous` to roll back. This keeps the previous known-good
    artifact recoverable across a post-copy failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        trash = reserve_previous(dest)
    except WindowsBundleError as exc:
        raise ToolchainError(str(exc)) from exc
    try:
        # copytree needs a non-existent target; the reserve moved any prior away.
        shutil.copytree(bundle, dest, ignore=_PACKAGE_IGNORE)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        restore_previous(trash, dest)
        raise
    return trash


def _load_and_verify(
    project_root: Path, no_verify_lock: bool
) -> tuple[object, WindowsLockfile]:
    config = _load_config(project_root)
    lock = _load_lock(project_root)
    pyproject = project_root / "pyproject.toml"
    if not no_verify_lock and not is_in_sync(lock, pyproject.read_text("utf-8")):
        raise ToolchainError(
            f"{lockfile_path_for('windows').name} is out of date with "
            "pyproject.toml.\n"
            "  Run `kivyforge lock -p windows` to regenerate it (or pass "
            "--no-verify-lock to build against the stale lock anyway)."
        )
    return config, lock


def _lock_state(project_root: Path) -> str:
    path = lockfile_path_for("windows", project_root)
    if not path.is_file():
        return "missing (run `kivyforge lock -p windows`)"
    try:
        lock = load_windows_lock(path)
    except LockError:
        return "unreadable (run `kivyforge lock -p windows`)"
    pyproject = project_root / "pyproject.toml"
    if is_in_sync(lock, pyproject.read_text("utf-8")):
        return "in sync"
    return "out of date (run `kivyforge lock -p windows`)"


def _build_state(bundle: Path) -> str:
    if not bundle.exists():
        return "not built"
    age = time.time() - bundle.stat().st_mtime
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


def _require_windows_host() -> None:
    try:
        get_platform("windows").check_host_capability()
    except HostCapabilityError as exc:
        raise ToolchainError(str(exc)) from exc


def _load_config(project_root: Path):
    try:
        return load_config(
            project_root / "pyproject.toml", require_ios=False, require_windows=True
        )
    except ConfigError as exc:
        raise ToolchainError(exc.format()) from exc


def _load_lock(project_root: Path) -> WindowsLockfile:
    path = lockfile_path_for("windows", project_root)
    if not path.is_file():
        raise ToolchainError(
            f"no {path.name} found. Run `kivyforge lock -p windows` first."
        )
    try:
        return load_windows_lock(path)
    except LockError as exc:
        raise ToolchainError(str(exc)) from exc
