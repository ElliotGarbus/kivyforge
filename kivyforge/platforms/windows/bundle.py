r"""Assemble the Windows onedir bundle (windows-spec).

Orchestrates the stages: pick the assembly arch from the lock (+ ``--arch``),
stage the whole runtime prefix, install the locked wheels into it (no pip),
copy the app sources, stage any declared native binaries, generate the bootstrap
module, then place + resource-patch the launcher. Produces:

    build/windows/<Name>/
    ├── <Name>.exe                ← prebuilt launcher, resource-patched per app
    ├── _kivyforge_bootstrap.py   ← generated (fixed name)
    ├── app/                      ← user code ([tool.kivy].app_dir)
    ├── bin/                      ← declared native binaries (absent when empty)
    └── python/                   ← WHOLE PBS prefix

The tree is assembled into a temp directory and swapped in only on success, so a
failure mid-assembly leaves the previous, working bundle untouched instead of a
half-written one. The onedir folder is itself a shipped distributable (portable
use) *and* the input to the Phase 7 packaging step.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import click

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.config.model import Config

from . import WindowsBundleError
from .icons import stage_icon
from .launcher import launcher_exe_name, place_launcher, write_bootstrap
from .lock import WindowsLockfile
from .naming import windows_safe_name
from .native_stage import stage_native_binaries
from .rcedit import ResourcePatch
from .runtime_stage import stage_runtime
from .signing import pep440_to_file_version
from .wheels_stage import stage_wheels

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def resolve_assembly_arch(locked: tuple[str, ...], arch: str | None) -> str:
    """The single arch to assemble. Windows ships one arch (``amd64``) per onedir."""
    if not locked:
        raise WindowsBundleError(
            "the lock covers no architectures; re-run `kivyforge lock -p windows`."
        )
    if arch is None:
        return locked[0]
    if arch not in locked:
        raise WindowsBundleError(
            f"--arch {arch} is not in the lock (covers {', '.join(locked)}).\n"
            f"  Add {arch!r} to [tool.kivy.windows].archs and re-lock, or pick a "
            "locked arch."
        )
    return arch


def bundle_dir_name(config: Config) -> str:
    """The onedir folder name for *config* (Windows-safe display name)."""
    return windows_safe_name(config.display_name)


def build_onedir(
    config: Config,
    lock: WindowsLockfile,
    project_root: Path,
    *,
    arch: str | None = None,
    staging_dir: Path | None = None,
    no_cache: bool = False,
    cache: ArtifactCache | None = None,
    echo=click.echo,
) -> Path:
    """Build the onedir bundle tree and return its path."""
    target_arch = resolve_assembly_arch(lock.archs, arch)
    cache = cache or ArtifactCache()
    staging_dir = staging_dir or (project_root / "build" / "windows")
    bundle = staging_dir / bundle_dir_name(config)

    staging_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=staging_dir, prefix=f".{bundle.name}.tmp-"))
    try:
        echo(
            f"Staging CPython {lock.python_runtime.version} runtime ({target_arch}) ..."
        )
        stage_runtime(
            lock.python_runtime,
            target_arch,
            work / "python",
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )

        echo(f"Installing {len(lock.packages)} locked packages ...")
        stage_wheels(
            lock.packages,
            target_arch,
            work / "python",
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )

        if lock.native_binaries:
            echo(f"Staging {len(lock.native_binaries)} native binaries ...")
            stage_native_binaries(
                lock,
                work,
                target_arch,
                project_root=project_root,
                cache=cache,
                no_cache=no_cache,
            )

        _copy_app_sources(config, project_root, work / "app")

        write_bootstrap(
            work,
            entry_point=config.kivy.entry_point,
            app_id=config.windows_required.app_id,
        )

        icon = stage_icon(config, project_root, work / "app.ico")
        place_launcher(
            work,
            display_name=config.display_name,
            patch=_resource_patch(config, icon),
        )
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise

    if bundle.exists():
        shutil.rmtree(bundle)
    work.replace(bundle)
    return bundle


def _resource_patch(config: Config, icon: Path | None) -> ResourcePatch:
    """The launcher resource patch from project metadata.

    The string ProductVersion carries the full PEP 440 version; the numeric
    FILEVERSION/PRODUCTVERSION use the deterministic four-part mapping (signing).
    """
    version = config.project.version
    numeric = pep440_to_file_version(version)
    return ResourcePatch(
        icon=icon,
        product_name=config.display_name,
        file_description=config.display_name,
        product_version_string=version,
        file_version=numeric,
        product_version=numeric,
    )


def _copy_app_sources(config: Config, project_root: Path, dest: Path) -> None:
    src = (project_root / config.kivy.app_dir).resolve()
    if not src.is_dir():
        raise WindowsBundleError(
            f"[tool.kivy].app_dir points to {config.kivy.app_dir!r}, which is not "
            f"a directory under {project_root}."
        )
    entry_rel = f"{config.kivy.entry_point.replace('.', '/')}.py"
    entry = src / entry_rel
    if not entry.is_file():
        raise WindowsBundleError(
            f"entry point {entry_rel} not found in "
            f"{config.kivy.app_dir}/ (set [tool.kivy].entry_point)."
        )
    shutil.copytree(src, dest, ignore=_IGNORE)


# Re-exported for the verbs/status so they compute the same path.
def onedir_path(config: Config, project_root: Path) -> Path:
    return project_root / "build" / "windows" / bundle_dir_name(config)


def launcher_name(config: Config) -> str:
    return launcher_exe_name(config.display_name)
