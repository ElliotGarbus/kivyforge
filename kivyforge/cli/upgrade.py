"""``kivyforge upgrade`` — re-download pinned runtime/native artifacts per the
resolved platform's lock (spec 05).

Platform-aware: resolves the target the same way as ``lock``/``build``/``run``
(``-p`` / ``KIVYFORGE_PLATFORM`` / host default, gated on the lock already
being configured). iOS refreshes ``Python.xcframework`` + xcframework
artifacts; macOS/Linux refresh the pinned python-build-standalone runtime
archive(s) — their locks have no xcframework-equivalent entries. Dependency
wheels are deliberately never touched here on any platform (that is
``build``'s/``lock``'s job); ``upgrade`` only re-fetches bytes already pinned
by the existing lock, it never changes what is pinned.
"""

from __future__ import annotations

from pathlib import Path

import click

from ..artifacts.download import DownloadError, fetch_artifact
from ..artifacts.verify import HashMismatch
from ..lock import LockError
from ..platforms.ios.lock import load as load_ios_lock
from ._common import ToolchainError, lockfile_path_for
from ._platform import platform_option, resolve_target


@click.command()
@platform_option
@click.option(
    "--python",
    "python_only",
    is_flag=True,
    help="Only refresh the bundled Python runtime (iOS: Python.xcframework; "
    "macOS/Linux: the runtime archive(s) — a no-op flag there, it's already "
    "the only refreshable artifact).",
)
@click.option(
    "--xcframeworks",
    "xcframeworks_only",
    is_flag=True,
    help="Only refresh native xcframework artifacts (iOS only).",
)
@click.option(
    "--name",
    default=None,
    help="Only refresh a specific artifact by name (iOS: an xcframework name "
    "or 'Python.xcframework'; macOS/Linux: a locked arch, e.g. 'arm64').",
)
def upgrade(
    cli_platform: str | None,
    python_only: bool,
    xcframeworks_only: bool,
    name: str | None,
) -> None:
    """Re-fetch pinned runtime/native artifacts for the resolved platform's lock."""
    backend, project_root = resolve_target(cli_platform, verb="upgrade")

    if backend.name == "ios":
        _upgrade_ios(project_root, python_only, xcframeworks_only, name)
    elif backend.name == "android":
        if xcframeworks_only:
            raise ToolchainError(
                "--xcframeworks is iOS-only; Android uses --libs for .aar/.jar."
            )
        _upgrade_android(project_root, python_only, name)
    elif backend.name in ("macos", "linux", "windows"):
        if xcframeworks_only:
            raise ToolchainError(
                f"--xcframeworks is iOS-only; {backend.name} locks have no "
                "xcframework artifacts. Use --python (or no flag) to refresh "
                "the bundled runtime."
            )
        _upgrade_wheelruntime(backend.name, project_root, name)
    else:
        raise ToolchainError(
            f"`kivyforge upgrade` does not support platform {backend.name!r} yet."
        )


def _upgrade_android(
    project_root: Path, python_only: bool, name: str | None
) -> None:
    """Re-fetch the pinned python.org runtime + .aar/.jar per the existing lock.

    Does not reinstall wheels, regenerate the project, or invoke Gradle
    (android/06 §upgrade): to take newer versions, edit pyproject.toml and
    re-lock.
    """
    from ..platforms.android.lock import reader as android_reader

    lock_path = project_root / "pylock.android.toml"
    if not lock_path.is_file():
        raise ToolchainError(
            "pylock.android.toml not found. Run `kivyforge lock -p android` first."
        )
    try:
        lock = android_reader.load(lock_path)
    except LockError as exc:
        raise ToolchainError(str(exc)) from exc

    do_libs = not python_only
    refreshed = skipped = 0
    for runtime in lock.python_android:
        if name and name not in (runtime.abi, "python"):
            continue
        if runtime.path:
            skipped += 1
            continue
        click.echo(
            f"Refreshing python.org runtime {runtime.version} ({runtime.abi}) ..."
        )
        fetch_artifact(
            name=f"python-android-{runtime.abi}",
            sha256=runtime.sha256,
            filename=(runtime.url or "").rsplit("/", 1)[-1],
            url=runtime.url,
            project_root=project_root,
            no_cache=True,
        )
        refreshed += 1
    if do_libs:
        for lib in lock.android_libs:
            if name and name != lib.name:
                continue
            if lib.path:
                skipped += 1
                continue
            click.echo(f"Refreshing {lib.kind} {lib.name} {lib.version} ...")
            fetch_artifact(
                name=lib.name,
                sha256=lib.sha256,
                filename=(lib.url or "").rsplit("/", 1)[-1],
                url=lib.url,
                project_root=project_root,
                no_cache=True,
            )
            refreshed += 1
    click.echo(
        f"Refreshed {refreshed} artifact(s)"
        + (f"; {skipped} vendored (path) entry(ies) skipped." if skipped else ".")
    )


# --------------------------------------------------------------------------- #
# iOS — Python.xcframework + [[xcframeworks]]
# --------------------------------------------------------------------------- #
def _upgrade_ios(
    project_root: Path,
    python_only: bool,
    xcframeworks_only: bool,
    name: str | None,
) -> None:
    lock = _load_ios_lock(project_root)

    # No selector flag => refresh everything.
    do_python = python_only or not (python_only or xcframeworks_only or name)
    do_xc = xcframeworks_only or not (python_only or xcframeworks_only or name)
    if name:
        do_python = name == "Python.xcframework"
        do_xc = True

    refreshed = 0
    skipped_vendored = 0
    try:
        if do_python and (not name or name == "Python.xcframework"):
            px = lock.python_xcframework
            click.echo(f"Refreshing Python.xcframework {px.version} ...")
            fetch_artifact(
                name="Python.xcframework",
                sha256=px.sha256,
                filename=px.url.rsplit("/", 1)[-1],
                url=px.url,
                no_cache=True,
            )
            refreshed += 1

        if do_xc:
            for xc in lock.xcframeworks:
                if name and xc.name != name:
                    continue
                if xc.path:
                    skipped_vendored += 1
                    continue
                url = xc.url
                if url is None:
                    continue
                click.echo(f"Refreshing {xc.name} {xc.version} ...")
                fetch_artifact(
                    name=xc.name,
                    sha256=xc.sha256,
                    filename=url.rsplit("/", 1)[-1],
                    url=url,
                    project_root=project_root,
                    no_cache=True,
                )
                refreshed += 1
    except HashMismatch as exc:
        raise ToolchainError(str(exc)) from exc
    except DownloadError as exc:
        raise ToolchainError(str(exc)) from exc

    if name and refreshed == 0 and skipped_vendored == 0:
        raise ToolchainError(
            f"no artifact named {name!r} found in {lockfile_path_for('ios').name}."
        )
    msg = f"Refreshed {refreshed} artifact(s)."
    if skipped_vendored:
        msg += f" Skipped {skipped_vendored} vendored (path-based) entry/entries."
    click.echo(msg)


def _load_ios_lock(project_root: Path):
    path = lockfile_path_for("ios", project_root)
    if not path.is_file():
        raise ToolchainError(f"no {path.name} found. Run `kivyforge lock` first.")
    try:
        return load_ios_lock(path)
    except LockError as exc:
        raise ToolchainError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# macOS / Linux — bundled python-build-standalone runtime archive(s)
# --------------------------------------------------------------------------- #
def _upgrade_wheelruntime(
    platform_name: str, project_root: Path, name: str | None
) -> None:
    lock = _load_wheelruntime_lock(platform_name, project_root)
    runtime = lock.python_runtime
    artifacts = runtime.artifacts
    if name:
        artifacts = [art for art in artifacts if art.arch == name]

    refreshed = 0
    try:
        for art in artifacts:
            click.echo(
                f"Refreshing the {platform_name} Python runtime "
                f"({art.arch}) {runtime.version} ..."
            )
            fetch_artifact(
                name=f"python-runtime-{art.arch}",
                sha256=art.sha256,
                filename=art.url.rsplit("/", 1)[-1],
                url=art.url,
                project_root=project_root,
                no_cache=True,
            )
            refreshed += 1
    except HashMismatch as exc:
        raise ToolchainError(str(exc)) from exc
    except DownloadError as exc:
        raise ToolchainError(str(exc)) from exc

    if name and refreshed == 0:
        locked = ", ".join(sorted(art.arch for art in runtime.artifacts))
        path = lockfile_path_for(platform_name, project_root)
        raise ToolchainError(
            f"no runtime artifact for arch {name!r} in {path.name}. "
            f"Locked arch(s): {locked}."
        )
    click.echo(f"Refreshed {refreshed} artifact(s).")


def _load_wheelruntime_lock(platform_name: str, project_root: Path):
    path = lockfile_path_for(platform_name, project_root)
    if not path.is_file():
        raise ToolchainError(f"no {path.name} found. Run `kivyforge lock` first.")
    if platform_name == "macos":
        from ..platforms.macos.lock import load as loader
    elif platform_name == "windows":
        from ..platforms.windows.lock import load as loader
    else:
        from ..platforms.linux.lock import load as loader
    try:
        return loader(path)
    except LockError as exc:
        raise ToolchainError(str(exc)) from exc
