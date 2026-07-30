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

import platform
import shutil
import tempfile
from pathlib import Path

import click

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.bundle.pycompile import PycompileError, byte_compile, select_compiler
from kivyforge.config.model import Config

from . import AppDirError
from .desktop import validate_desktop_file, write_desktop_entry
from .icons import stage_icons
from .launcher import build_apprun, entry_point_rel_path
from .lock import LinuxLockfile
from .native_stage import stage_native_binaries
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


def _setting_applies(value: bool | str, *, release: bool) -> bool:
    """A ``build_settings`` tri-state resolved for the build being produced."""
    if isinstance(value, bool):
        return value
    return release  # DESKTOP_RELEASE_ONLY


def _resolve_byte_compile(
    config: Config,
    *,
    staged_interpreter: Path,
    target_arch: str,
    python_version: str,
    release: bool,
) -> tuple[tuple[str, ...] | None, bool]:
    """Decide whether to byte-compile, and with which interpreter.

    Returns ``(compiler_argv_or_None, strip_source)``; ``None`` means do not
    byte-compile. ``byte_compile = true`` is read as "I insist", so a missing
    interpreter is an error; the default ``"release"`` degrades to shipping
    source with a warning rather than breaking a build the user never
    configured.
    """
    settings = config.linux_required.build_settings
    if not _setting_applies(settings.byte_compile, release=release):
        return None, False
    native = platform.machine().lower() == target_arch
    compiler = select_compiler(
        staged_interpreter=staged_interpreter,
        native=native,
        python_version=python_version,
    )
    if compiler is None:
        message = (
            f"this project ships CPython {python_version}, and no CPython of "
            "that minor could be found to byte-compile with (a .pyc is only "
            "loadable by the exact CPython minor that wrote it)"
        )
        if settings.byte_compile is True:
            raise AppDirError(
                "[tool.kivy.linux.build_settings].byte_compile = true but "
                f"{message}.\n"
                "  Install a matching CPython, or set byte_compile = false."
            )
        click.echo(f"[stage] not byte-compiling: {message}.")
        return None, False
    strip = _setting_applies(settings.strip_source, release=release)
    return compiler, strip


def build_appdir(
    config: Config,
    lock: LinuxLockfile,
    project_root: Path,
    *,
    arch: str | None = None,
    staging_dir: Path | None = None,
    no_cache: bool = False,
    cache: ArtifactCache | None = None,
    release: bool = False,
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

        if lock.native_binaries:
            echo(f"Staging {len(lock.native_binaries)} native binaries ...")
            stage_native_binaries(
                lock,
                work / "usr",
                project_root=project_root,
                cache=cache,
                no_cache=no_cache,
            )

        _copy_app_sources(config, project_root, work / "usr" / "app")

        compiler, strip_source = _resolve_byte_compile(
            config,
            staged_interpreter=work / "usr" / "python" / "bin" / "python3",
            target_arch=target_arch,
            python_version=lock.python_runtime.version,
            release=release,
        )
        if compiler is not None:
            with_what = " ".join(compiler) if compiler else "this interpreter"
            echo(
                f"[stage] byte-compiling the Python payload with {with_what}"
                + (" (.pyc only)" if strip_source else "")
            )
            try:
                byte_compile(
                    [work / "usr" / "app", work / "usr" / "lib"],
                    compiler=compiler,
                    strip_source=strip_source,
                    stripdir=work,
                )
            except PycompileError as exc:
                raise AppDirError(
                    f"{exc}\n  Fix it, or set "
                    "[tool.kivy.linux.build_settings].byte_compile = false."
                ) from exc

        stage_icons(config, project_root, work)

        build_apprun(
            work / "AppRun",
            entry_point=config.kivy.entry_point,
            app_id=config.linux_required.app_id,
            has_native_binaries=bool(lock.native_binaries),
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
