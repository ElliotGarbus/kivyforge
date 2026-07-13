"""Assemble (and optionally sign) the macOS ``.app`` bundle (macos-spec).

Orchestrates the pieces: resolve the assembly arch set from the lock + ``--arch``,
stage the runtime + wheels, copy the app sources, render the icon + Info.plist +
launcher, and ad-hoc sign. Produces the layout documented in macos-spec:

    <Name>.app/Contents/{Info.plist, MacOS/<exe>,
                         Resources/{app,lib,python,<exe>.icns}}
"""

from __future__ import annotations

import plistlib
import shutil
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


def resolve_assembly_archs(
    locked: tuple[str, ...], arch: str | None
) -> tuple[str, ...]:
    """The subset of the locked archs to assemble for an ``--arch`` request.

    ``None`` -> the full locked set (universal2 when two). ``universal2`` -> the
    full set (requires a multi-arch lock). A single arch -> just that arch.
    Requesting an arch (or universal2) not covered by the lock is an error.
    """
    locked_set = set(locked)
    if arch is None:
        return locked
    if arch == "universal2":
        if len(locked) < 2:
            raise AppBundleError(
                "--arch universal2 needs a lock covering both arm64 and x86_64, "
                f"but the lock only covers {', '.join(locked)}.\n"
                '  Set [tool.kivy.macos].archs = ["arm64", "x86_64"] and re-lock.'
            )
        return locked
    if arch not in locked_set:
        raise AppBundleError(
            f"--arch {arch} is not in the lock (covers {', '.join(locked)}).\n"
            f"  Add {arch!r} to [tool.kivy.macos].archs and re-lock, or pick a "
            "locked arch."
        )
    return (arch,)


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
    archs = resolve_assembly_archs(lock.archs, arch)
    cache = cache or ArtifactCache()
    staging_dir = staging_dir or (project_root / "build" / "macos")
    exe = config.app_slug
    app = staging_dir / f"{config.display_name}.app"
    contents = app / "Contents"

    if app.exists():
        shutil.rmtree(app)
    (contents / "MacOS").mkdir(parents=True)
    resources = contents / "Resources"
    resources.mkdir()

    label = "universal2" if len(archs) > 1 else archs[0]
    echo(f"Staging CPython {lock.python_runtime.version} runtime ({label}) ...")
    stage_runtime(
        lock.python_runtime,
        archs,
        resources / "python",
        project_root=project_root,
        cache=cache,
        no_cache=no_cache,
    )

    echo(f"Installing {len(lock.packages)} locked packages ...")
    stage_wheels(
        lock.packages,
        archs,
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
        archs=archs,
    )

    plist = build_info_plist(config, executable=exe, icon_file=icon_file)
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump(plist, fh)

    if sign:
        echo("Ad-hoc signing the bundle ...")
        count = sign_bundle_adhoc(app)
        echo(f"  signed {count} Mach-O binaries + the bundle")

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
