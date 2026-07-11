"""macOS dispatch for the shared ``build`` / ``run`` / ``package`` verbs.

Keeps the macOS ``.app`` flow out of the (iOS/Xcode-centric) verb modules: each
verb resolves the target platform and, when it is macOS, calls in here. Loads the
macOS config + ``pylock.macos.toml``, runs the drift check, and drives the
``.app`` bundler.
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
from . import AppBundleError
from .bundle import build_app_bundle
from .lock import MacosLockfile
from .lock import load as load_macos_lock
from .notarize import notarize_and_staple
from .signing import sign_bundle_developer_id


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
    signing_identity: str | None = None,
    notarize: bool | None = None,
    notary_profile: str | None = None,
) -> Path:
    """Produce the finished, signed ``.app`` distributable.

    Signing tier is config-driven: with ``[tool.kivy.macos.signing].identity``
    set (or ``--signing-identity``), the bundle is Developer-ID deep-signed
    (Hardened Runtime + timestamp) and — when a notary profile is configured —
    notarized and stapled. Without an identity, the ad-hoc floor applies.
    """
    _require_macos_host()
    config = _load_config(project_root)
    signing = config.macos_required.signing
    identity = signing_identity or signing.identity
    profile = notary_profile or signing.notary_profile
    # None = config-driven: notarize whenever a profile is configured.
    do_notarize = notarize if notarize is not None else bool(profile)

    if not identity:
        if notarize:
            raise ToolchainError(
                "--notarize requires Developer ID signing, but no identity is "
                "configured.\n"
                "  Set [tool.kivy.macos.signing].identity to your 'Developer ID "
                "Application: ...' certificate (or pass --signing-identity)."
            )
        app = macos_build(
            project_root,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
            sign=True,
        )
        click.echo(
            f"Packaged {app.relative_to(project_root)} (ad-hoc signed).\n"
            "  Distribute the .app directly, or wrap it in a .dmg with an "
            "external tool (see docs). For Gatekeeper-trusted distribution, "
            "configure [tool.kivy.macos.signing]."
        )
        return app

    if do_notarize and not profile:
        raise ToolchainError(
            "notarization needs a notary keychain profile.\n"
            "  Create one: `xcrun notarytool store-credentials <name> "
            "--apple-id <id> --team-id <team>` and set "
            '[tool.kivy.macos.signing].notary_profile = "<name>" '
            "(or pass --notary-profile)."
        )

    # Assemble unsigned; the Developer ID deep-sign below seals every Mach-O.
    app = macos_build(
        project_root,
        arch=arch,
        no_verify_lock=no_verify_lock,
        no_cache=no_cache,
        sign=False,
    )
    try:
        click.echo(f"Developer ID signing with {identity!r} ...")
        count = sign_bundle_developer_id(
            app,
            identity,
            extra_entitlements=config.macos_required.entitlements,
        )
        click.echo(f"  signed {count} Mach-O binaries + the bundle")
        if do_notarize:
            notarize_and_staple(app, profile=profile)
    except AppBundleError as exc:
        raise ToolchainError(str(exc)) from exc

    trust = "notarized + stapled" if do_notarize else "signed (not notarized)"
    click.echo(
        f"Packaged {app.relative_to(project_root)} (Developer ID {trust}).\n"
        "  Distribute the .app directly, or wrap it in a .dmg with an external "
        "tool (see docs)."
    )
    return app


def macos_status(project_root: Path) -> None:
    """Show app identity, Python version, lock sync, and build state."""
    config = _load_config(project_root)
    macos = config.macos_required
    click.echo(f"App:        {config.display_name}  ({macos.bundle_id})")
    click.echo(f"Python:     {macos.python_version or '(unset)'}")
    click.echo(f"Lock:       {_lock_state(project_root)}")

    app = project_root / "build" / "macos" / f"{config.display_name}.app"
    click.echo(f"Build:      {_build_state(app)}")


def _lock_state(project_root: Path) -> str:
    path = lockfile_path_for("macos", project_root)
    if not path.is_file():
        return "missing (run `kivyforge lock -p macos`)"
    try:
        lock = load_macos_lock(path)
    except LockError:
        return "unreadable (run `kivyforge lock -p macos`)"
    pyproject = project_root / "pyproject.toml"
    if is_in_sync(lock, pyproject.read_text("utf-8")):
        return "in sync"
    return "out of date (run `kivyforge lock -p macos`)"


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
