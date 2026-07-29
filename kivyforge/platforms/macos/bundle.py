"""Assemble (and optionally sign) the macOS ``.app`` bundle (macos-spec).

Orchestrates the pieces: resolve the assembly arch from the lock + ``--arch``
(macOS is arm64-only, so this is always a single arch), stage the runtime +
wheels, copy the app sources, render the icon + Info.plist + launcher, and
ad-hoc sign. Produces the layout documented in macos-spec:

    <Name>.app/Contents/{Info.plist, MacOS/<exe>,
                         Resources/{app,lib,python,<exe>.icns}}
"""

from __future__ import annotations

import plistlib
import shutil
import tempfile
from pathlib import Path

import click

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.config.model import Config

from . import AppBundleError
from .icns import generate_icns
from .launcher import build_launcher
from .lock import MacosLockfile
from .native_stage import stage_native_binaries
from .plist import build_info_plist
from .runtime_stage import stage_runtime
from .signing import sign_bundle_adhoc
from .wheels_stage import stage_wheels

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def resolve_assembly_arch(locked: tuple[str, ...], arch: str | None) -> str:
    """The single arch to assemble. macOS ships arm64 only."""
    if not locked:
        raise AppBundleError(
            "the lock covers no architectures; re-run `kivyforge lock -p macos`."
        )
    if arch is None:
        return locked[0]
    if arch not in locked:
        raise AppBundleError(
            f"--arch {arch} is not in the lock (covers {', '.join(locked)}).\n"
            f"  macOS builds are arm64-only; pick a locked arch."
        )
    return arch


def build_app_bundle(
    config: Config,
    lock: MacosLockfile,
    project_root: Path,
    *,
    arch: str | None = None,
    staging_dir: Path | None = None,
    sign: bool = True,
    no_cache: bool = False,
    cache: ArtifactCache | None = None,
    echo=click.echo,
) -> Path:
    """Build the ``.app`` and return its path."""
    target_arch = resolve_assembly_arch(lock.archs, arch)
    cache = cache or ArtifactCache()
    staging_dir = staging_dir or (project_root / "build" / "macos")
    exe = config.app_slug
    app = staging_dir / f"{config.display_name}.app"

    # Assemble into a temp .app and swap it in only on success, so a failure
    # mid-assembly (e.g. a transient runtime/wheel fetch error, or a signing
    # failure) leaves the previous, working .app untouched instead of a
    # half-written one. Mirrors the Linux AppDir builder's write-then-swap.
    staging_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=staging_dir, prefix=f".{app.name}.tmp-"))
    try:
        contents = work / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        resources = contents / "Resources"
        resources.mkdir()

        echo(
            f"Staging CPython {lock.python_runtime.version} runtime ({target_arch}) ..."
        )
        stage_runtime(
            lock.python_runtime,
            target_arch,
            resources / "python",
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )

        echo(f"Installing {len(lock.packages)} locked packages ...")
        stage_wheels(
            lock.packages,
            target_arch,
            resources / "lib",
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )

        if lock.native_binaries:
            echo(f"Staging {len(lock.native_binaries)} native binaries ...")
            stage_native_binaries(
                lock,
                resources,
                project_root=project_root,
                cache=cache,
                no_cache=no_cache,
            )

        _copy_app_sources(config, project_root, resources / "app")
        icon_file = _stage_icon(config, project_root, resources, exe)

        build_launcher(
            contents / "MacOS" / exe,
            entry_point=config.kivy.entry_point,
            arch=target_arch,
        )

        plist = build_info_plist(config, executable=exe, icon_file=icon_file)
        with (contents / "Info.plist").open("wb") as fh:
            plistlib.dump(plist, fh)

        # Sign the temp bundle before the swap: codesign embeds signatures in the
        # Mach-O files + Contents/_CodeSignature, so an atomic rename preserves
        # them, and a signing failure never displaces the previous good .app.
        if sign:
            echo("Ad-hoc signing the bundle ...")
            count = sign_bundle_adhoc(work)
            echo(f"  signed {count} Mach-O binaries + the bundle")
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise

    # Swap the freshly built tree in for the previous one. The rename is atomic
    # within staging_dir; the brief rmtree→rename window only exists after a
    # fully successful build.
    if app.exists():
        shutil.rmtree(app)
    work.replace(app)
    return app


def _copy_app_sources(config: Config, project_root: Path, dest: Path) -> None:
    src = (project_root / config.kivy.app_dir).resolve()
    if not src.is_dir():
        raise AppBundleError(
            f"[tool.kivy].app_dir points to {config.kivy.app_dir!r}, which is not "
            f"a directory under {project_root}."
        )
    entry = src / f"{config.kivy.entry_point}.py"
    if not entry.is_file():
        raise AppBundleError(
            f"entry point {config.kivy.entry_point}.py not found in "
            f"{config.kivy.app_dir}/ (set [tool.kivy].entry_point)."
        )
    shutil.copytree(src, dest, ignore=_IGNORE)


def _stage_icon(
    config: Config, project_root: Path, resources: Path, exe: str
) -> str | None:
    source = config.macos_required.icons.source
    if not source:
        return None
    icns = f"{exe}.icns"
    generate_icns((project_root / source).resolve(), resources / icns)
    return icns
