"""Assemble the Linux AppDir (linux-spec).

Orchestrates the stages: pick the assembly arch from the lock (+ ``--arch``),
stage the runtime + wheels, copy the app sources, render the icons + ``AppRun``
launcher + ``.desktop`` entry. Produces the layout documented in linux-spec:

    build/linux/<Name>.AppDir/
    ├── AppRun
    ├── <app_id>.desktop
    ├── <app_id>.png
    └── usr/{app, lib, python, share/icons/hicolor/...}
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import click

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.config.model import Config

from . import AppDirError
from .desktop import validate_desktop_file, write_desktop_entry
from .icons import stage_icons
from .launcher import build_apprun, entry_point_rel_path
from .lock import LinuxLockfile
from .runtime_stage import stage_runtime
from .wheels_stage import stage_wheels

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def resolve_assembly_arch(locked: tuple[str, ...], arch: str | None) -> str:
    """The single arch to assemble for an ``--arch`` request.

    Linux ships one arch per AppImage, so this always resolves to exactly one.
    ``None`` -> the lock's arch (there is exactly one this phase). An explicit
    arch not covered by the lock is an error.
    """
    if not locked:
        raise AppDirError("the lock covers no architectures; re-run `kivyforge lock`.")
    if arch is None:
        return locked[0]
    if arch not in locked:
        raise AppDirError(
            f"--arch {arch} is not in the lock (covers {', '.join(locked)}).\n"
            f"  Add {arch!r} to [tool.kivy.linux].archs and re-lock, or pick a "
            "locked arch."
        )
    return arch


def build_appdir(
    config: Config,
    lock: LinuxLockfile,
    project_root: Path,
    *,
    arch: str | None = None,
    staging_dir: Path | None = None,
    no_cache: bool = False,
    cache: ArtifactCache | None = None,
    echo=click.echo,
) -> Path:
    """Build the AppDir tree and return its path."""
    target_arch = resolve_assembly_arch(lock.archs, arch)
    cache = cache or ArtifactCache()
    staging_dir = staging_dir or (project_root / "build" / "linux")
    appdir = staging_dir / f"{config.display_name}.AppDir"

    # Assemble into a temp tree and swap it in only on success, so a failure
    # mid-assembly (e.g. a transient runtime/wheel fetch error) leaves the
    # previous, working AppDir untouched instead of a half-written one.
    staging_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=staging_dir, prefix=f".{appdir.name}.tmp-"))
    try:
        (work / "usr").mkdir(parents=True)

        echo(
            f"Staging CPython {lock.python_runtime.version} runtime ({target_arch}) ..."
        )
        stage_runtime(
            lock.python_runtime,
            target_arch,
            work / "usr" / "python",
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )

        echo(f"Installing {len(lock.packages)} locked packages ...")
        stage_wheels(
            lock.packages,
            target_arch,
            work / "usr" / "lib",
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )

        _copy_app_sources(config, project_root, work / "usr" / "app")
        stage_icons(config, project_root, work)

        build_apprun(
            work / "AppRun",
            entry_point=config.kivy.entry_point,
            app_id=config.linux_required.app_id,
        )
        desktop_path = work / f"{config.linux_required.app_id}.desktop"
        write_desktop_entry(config, desktop_path)
        validate_desktop_file(desktop_path)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise

    # Swap the freshly built tree in for the previous one. The rename is atomic
    # within staging_dir; the brief unlink→rename window only exists after a
    # fully successful build.
    if appdir.exists():
        shutil.rmtree(appdir)
    work.replace(appdir)
    return appdir


def _copy_app_sources(config: Config, project_root: Path, dest: Path) -> None:
    src = (project_root / config.kivy.app_dir).resolve()
    if not src.is_dir():
        raise AppDirError(
            f"[tool.kivy].app_dir points to {config.kivy.app_dir!r}, which is not "
            f"a directory under {project_root}."
        )
    # A dotted entry_point (e.g. "pkg.start") maps to a nested source file
    # (src/pkg/start.py), matching the shared app_dir/entry_point layout.
    entry_rel = f"{entry_point_rel_path(config.kivy.entry_point)}.py"
    entry = src / entry_rel
    if not entry.is_file():
        raise AppDirError(
            f"entry point {entry_rel} not found in "
            f"{config.kivy.app_dir}/ (set [tool.kivy].entry_point)."
        )
    shutil.copytree(src, dest, ignore=_IGNORE)
