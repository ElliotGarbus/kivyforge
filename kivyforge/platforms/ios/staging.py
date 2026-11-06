"""Create and maintain the ``<app>-ios/`` staging tree (spec 06)."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kivyforge.build_outcome import discard_note
from kivyforge.bundle import app_metadata
from kivyforge.bundle.hostpython import pinned_compiler
from kivyforge.bundle.pycompile import PycompileError, byte_compile
from kivyforge.config.model import Config
from kivyforge.lock.host_python import HostPython
from kivyforge.report.failures import ClassifiedError, reclassify

_APP_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")

#: Where ``kivyforge build`` stages the app's package metadata for the Build
#: Python script to copy into the bundle. Never on the app's import path (D4).
APP_METADATA_DIR = "_kivyforge_meta"


class StagingError(ClassifiedError):
    """Staging tree cannot be created (e.g. ``app_dir`` does not exist)."""


@dataclass(frozen=True)
class StagingLayout:
    root: Path  # <app>-ios/

    @property
    def xcodeproj(self) -> Path:
        return self.root / f"{self.root.name[:-4]}.xcodeproj"

    @property
    def python_xcframework(self) -> Path:
        return self.root / "Python.xcframework"

    @property
    def frameworks(self) -> Path:
        return self.root / "Frameworks"

    @property
    def app(self) -> Path:
        return self.root / "app"

    @property
    def pip_deps_simulator(self) -> Path:
        return self.root / "pip-deps-simulator"

    @property
    def pip_deps_device(self) -> Path:
        return self.root / "pip-deps-device"

    def pip_deps_for_slice(self, target: str) -> Path:
        """Return the slice-specific pip-deps directory for *target*."""
        return (
            self.pip_deps_simulator if target == "simulator" else self.pip_deps_device
        )

    @property
    def resources(self) -> Path:
        return self.root / "Resources"

    @property
    def app_metadata(self) -> Path:
        return self.root / APP_METADATA_DIR


def staging_dir_name(config: Config) -> str:
    return f"{config.app_slug}-ios"


def create_staging(
    config: Config,
    project_root: str | Path,
    *,
    release: bool = False,
    python_version: str | None = None,
    host_python: tuple[HostPython, ...] | None = None,
    no_cache: bool = False,
    echo: Callable[[str], None] = lambda msg: None,
    note=discard_note,
) -> StagingLayout:
    """Create the ``<app>-ios/`` tree and the ``app/`` source.

    Dev builds (``release=False``, the default) get a symlink to ``app_dir``
    (spec 06 "symlink, not copy") for fast edit-rebuild iteration — the
    symlink is created once and refreshed only if it points somewhere other
    than the current ``app_dir``. Release builds (``kivyforge package``) get a
    real, disposable copy instead, so ``[tool.kivy.ios.python.build_settings]``
    byte-compilation/stripping can run against it without ever touching the
    user's actual source tree — *release* requires *python_version* (the
    pinned ``Python.xcframework`` version) for that.
    """
    if release and python_version is None:
        raise ValueError("create_staging(release=True) requires python_version")

    project_root = Path(project_root)
    root = project_root / staging_dir_name(config)
    layout = StagingLayout(root=root)

    for d in (
        root,
        layout.frameworks,
        layout.pip_deps_device,
        layout.pip_deps_simulator,
        layout.resources,
    ):
        d.mkdir(parents=True, exist_ok=True)

    if release:
        assert python_version is not None  # checked before any directory exists
        _materialize_app_copy(
            layout,
            project_root,
            config,
            python_version,
            echo,
            note=note,
            host_python=host_python,
            no_cache=no_cache,
        )
    else:
        _refresh_app_symlink(layout, project_root, config.kivy.app_dir)
    _stage_app_metadata(layout, project_root, config)
    return layout


def _stage_app_metadata(
    layout: StagingLayout, project_root: Path, config: Config
) -> None:
    """Stage the app's package metadata for the Build Python script.

    docs/design/dev/package-metadata-proposal.md 2.2: the bundle's ``app/`` is
    Xcode's copy, made at Xcode build time -- a debug build's ``app/`` links to
    ``app_dir``, so nothing can be written there -- and the script swaps the
    staged folder in for the copy's development egg-info. Rewritten on every
    build, and removed when kivyforge generates nothing (entry points in
    ``dynamic``), so the script then leaves the copy alone. Only *reads*
    ``app_dir``, for ``top_level.txt``.
    """
    staged = layout.app_metadata
    if staged.exists():
        shutil.rmtree(staged)
    metadata = app_metadata.for_build(config)
    if metadata is None:
        return
    staged.mkdir()
    source = project_root / config.kivy.app_dir
    top_level = app_metadata.top_level_names(source, metadata.main_module)
    app_metadata.write_dist_info(metadata, staged, top_level)


def _refresh_app_symlink(
    layout: StagingLayout, project_root: Path, app_dir: str
) -> None:
    source = project_root / app_dir
    if not source.is_dir():
        raise StagingError(
            f"app_dir '{app_dir}' is not an existing directory "
            f"(looked for {source}). Create it or fix [tool.kivy].app_dir in "
            f"pyproject.toml — it must point at your app's Python source."
        )
    # The symlink target is relative to <app>-ios/ (e.g. ../src).
    target = os.path.relpath(source.resolve(), layout.root)
    link = layout.app
    if link.is_symlink():
        if os.readlink(link) == target:
            return
        link.unlink()
    elif link.is_dir():
        # A real directory here is a previous release build's materialized
        # copy (create_staging(release=True)), not foreign user data — always
        # kivyforge-owned output at this exact path. Reclaim it for the
        # symlink so switching back to build/run after a package works.
        shutil.rmtree(link)
    elif link.exists():
        raise StagingError(
            f"{link} exists and is not a symlink; remove it and re-run build."
        )
    link.symlink_to(target)


def _materialize_app_copy(
    layout: StagingLayout,
    project_root: Path,
    config: Config,
    python_version: str,
    echo: Callable[[str], None],
    note=discard_note,
    *,
    host_python: tuple[HostPython, ...] | None = None,
    no_cache: bool = False,
) -> None:
    source = project_root / config.kivy.app_dir
    if not source.is_dir():
        raise StagingError(
            f"app_dir '{config.kivy.app_dir}' is not an existing directory "
            f"(looked for {source}). Create it or fix [tool.kivy].app_dir in "
            f"pyproject.toml — it must point at your app's Python source."
        )
    link = layout.app
    # Always start clean: byte-compiling mutates the copy destructively
    # (deletes .py once a .pyc exists), so a stale copy must never be reused
    # across builds, and a leftover symlink from an earlier dev build must
    # never be mistaken for the release copy.
    if link.is_symlink():
        link.unlink()
    elif link.is_dir():
        shutil.rmtree(link)
    elif link.exists():
        raise StagingError(
            f"{link} exists and is neither a symlink nor a directory; remove "
            "it and re-run build."
        )
    shutil.copytree(source, link, ignore=_APP_COPY_IGNORE)
    _compile_app_copy(
        link,
        config,
        python_version,
        echo,
        note=note,
        host_python=host_python,
        no_cache=no_cache,
    )


def _setting_applies(value: bool | str, *, release: bool) -> bool:
    """A ``build_settings`` tri-state resolved for the build being produced."""
    if isinstance(value, bool):
        return value
    return release  # DESKTOP_RELEASE_ONLY


def _compile_app_copy(
    app: Path,
    config: Config,
    python_version: str,
    echo: Callable[[str], None],
    note=discard_note,
    *,
    host_python: tuple[HostPython, ...] | None = None,
    no_cache: bool = False,
) -> None:
    """Byte-compile/strip the materialized app copy, per ``build_settings``.

    Only ever called for the release copy (``release=True`` is implicit here
    — this function is unreachable from the dev symlink path), so the
    tri-state resolves against ``release=True`` unconditionally. Mirrors
    ``artifacts/collect.py::_compile_pip_deps``: the Python.xcframework ships
    no standalone interpreter to shell out to, so the compiler is the host
    CPython the lock pins for this machine (*host_python*), or none.
    """
    settings = config.ios_required.python_build_settings
    if not _setting_applies(settings.byte_compile, release=True):
        return
    compiler = pinned_compiler(
        host_python,
        platform="ios",
        python_version=python_version,
        byte_compile=settings.byte_compile,
        table="tool.kivy.ios.python.build_settings",
        what=" app sources",
        error=StagingError,
        echo=echo,
        note=note,
        context={"payload": "app-sources"},
        no_cache=no_cache,
    )
    if compiler is None:
        return
    strip_source = _setting_applies(settings.strip_source, release=True)
    with_what = " ".join(compiler) if compiler else "this interpreter"
    echo(
        f"[stage] byte-compiling app sources with {with_what}"
        + (" (.pyc only)" if strip_source else "")
    )
    try:
        byte_compile(
            [app], compiler=compiler, strip_source=strip_source, stripdir=app.parent
        )
    except PycompileError as exc:
        raise StagingError(
            f"{exc}\n  Fix it, or set "
            "[tool.kivy.ios.python.build_settings].byte_compile = false.",
            **reclassify(exc),
        ) from exc
