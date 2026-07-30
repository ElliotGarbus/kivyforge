"""Assemble (and optionally sign) the macOS ``.app`` bundle (macos-spec).

Orchestrates the pieces: resolve the assembly arch from the lock + ``--arch``
(macOS is arm64-only, so this is always a single arch), stage the runtime +
wheels, copy the app sources, render the icon + Info.plist + launcher, and
ad-hoc sign. Produces the layout documented in macos-spec:

    <Name>.app/Contents/{Info.plist, MacOS/<exe>,
                         Resources/{app,lib,python,<exe>.icns}}
"""

from __future__ import annotations

import platform
import plistlib
import shutil
import tempfile
from pathlib import Path

import click

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.bundle.pycompile import PycompileError, byte_compile, select_compiler
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
    settings = config.macos_required.build_settings
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
            raise AppBundleError(
                "[tool.kivy.macos.build_settings].byte_compile = true but "
                f"{message}.\n"
                "  Install a matching CPython, or set byte_compile = false."
            )
        click.echo(f"[stage] not byte-compiling: {message}.")
        return None, False
    strip = _setting_applies(settings.strip_source, release=release)
    return compiler, strip


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
    release: bool = False,
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

        # Byte-compile before signing: codesign seals every file it signs, so
        # mutating the payload afterward (deleting .py, writing .pyc) would
        # invalidate the very signature this function is about to produce.
        compiler, strip_source = _resolve_byte_compile(
            config,
            staged_interpreter=resources / "python" / "bin" / "python3",
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
                    [resources / "app", resources / "lib"],
                    compiler=compiler,
                    strip_source=strip_source,
                    stripdir=work,
                )
            except PycompileError as exc:
                raise AppBundleError(
                    f"{exc}\n  Fix it, or set "
                    "[tool.kivy.macos.build_settings].byte_compile = false."
                ) from exc

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
