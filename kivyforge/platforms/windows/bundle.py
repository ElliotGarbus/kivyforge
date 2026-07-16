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

The tree is assembled **in place** (see :mod:`.fsswap`): a freshly written tree
cannot be reliably renamed on Windows because the antivirus scanner holds new
files open, so any previous bundle is reserved first and restored if assembly
fails — a broken build never destroys a working one. The onedir folder is itself
a shipped distributable (portable use) *and* the input to the Phase 7 packaging
step.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.config.model import Config

from . import WindowsBundleError
from .fsswap import discard_reserved, reserve_previous, restore_previous
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
    """Build the onedir bundle tree and return its path.

    The tree is assembled **directly into its final location**. Temp-dir + rename
    (the POSIX pattern) is not viable on Windows: a just-written tree cannot be
    reliably renamed because the antivirus real-time scanner holds the new
    executables/DLLs open — on a cold first-sight scan (cloud lookup) that lasts
    well beyond any reasonable retry window. Instead we preserve any previous
    bundle in a trash dir first and restore it if assembly fails, so a broken
    build never destroys a working one. The trash is an already-scanned tree,
    which renames instantly; only freshly written files (which we never rename)
    hit the scan window.
    """
    target_arch = resolve_assembly_arch(lock.archs, arch)
    cache = cache or ArtifactCache()
    staging_dir = staging_dir or (project_root / "build" / "windows")
    bundle = staging_dir / bundle_dir_name(config)

    staging_dir.mkdir(parents=True, exist_ok=True)
    trash = reserve_previous(bundle)
    try:
        echo(
            f"Staging CPython {lock.python_runtime.version} runtime ({target_arch}) ..."
        )
        stage_runtime(
            lock.python_runtime,
            target_arch,
            bundle / "python",
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )

        echo(f"Installing {len(lock.packages)} locked packages ...")
        stage_wheels(
            lock.packages,
            target_arch,
            bundle / "python",
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )

        if lock.native_binaries:
            echo(f"Staging {len(lock.native_binaries)} native binaries ...")
            stage_native_binaries(
                lock,
                bundle,
                target_arch,
                project_root=project_root,
                cache=cache,
                no_cache=no_cache,
            )

        _copy_app_sources(config, project_root, bundle / "app")

        write_bootstrap(
            bundle,
            entry_point=config.kivy.entry_point,
            app_id=config.windows_required.app_id,
        )

        icon = stage_icon(config, project_root, bundle / "app.ico")
        place_launcher(
            bundle,
            display_name=config.display_name,
            patch=_resource_patch(config, icon),
        )
    except BaseException:
        shutil.rmtree(bundle, ignore_errors=True)
        restore_previous(trash, bundle)
        raise

    discard_reserved(trash)
    return bundle


def _first_author(config: Config) -> str | None:
    """First ``[project].authors`` name, or ``None`` — the publisher/copyright.

    Mirrors the iOS ``NSHumanReadableCopyright`` convention (pyproject-ios): the
    first author's name populates both ``LegalCopyright`` and ``CompanyName`` in
    the Windows version resource. Verbatim (no synthesized year) so the patch
    stays deterministic.
    """
    return next((a.name for a in config.project.authors if a.name), None)


def _resource_patch(config: Config, icon: Path | None) -> ResourcePatch:
    """The launcher resource patch from project metadata.

    The string ProductVersion carries the full PEP 440 version; the numeric
    FILEVERSION/PRODUCTVERSION use the deterministic four-part mapping (signing).
    LegalCopyright/CompanyName come from the first ``[project].authors`` entry.
    """
    version = config.project.version
    numeric = pep440_to_file_version(version)
    author = _first_author(config)
    return ResourcePatch(
        icon=icon,
        product_name=config.display_name,
        file_description=config.display_name,
        product_version_string=version,
        legal_copyright=author,
        company_name=author,
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
