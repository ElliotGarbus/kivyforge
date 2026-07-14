"""Stage locked native binaries into the ``.app``'s ``Resources/bin`` (macos-spec).

The ``[tool.kivy.macos.native.binaries]`` channel: each entry is fetched +
SHA-256-verified from ``pylock.macos.toml`` (URL or vendored path), then staged
into ``Contents/Resources/bin`` — a single native file copied in with its exec
bit set, or a ``.zip`` of several extracted with a path-traversal guard. The
directory is created only when the lock actually pins binaries (no empty
``bin/``). The bundle's signing sweep later covers everything under it.

The staging mechanics live in the shared
:mod:`kivyforge.artifacts.native_stage_util`; this module is the macOS-facing
wrapper that translates the neutral :class:`NativeStageError` into
``AppBundleError``.
"""

from __future__ import annotations

from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.native_stage_util import NativeStageError, stage_binaries

from . import AppBundleError
from .lock import MacosLockfile


def stage_native_binaries(
    lock: MacosLockfile,
    resources: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
) -> None:
    """Stage every pinned native binary for the lock into ``resources/bin``."""
    try:
        stage_binaries(
            lock.native_binaries,
            resources,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
            bin_label="Contents/Resources/bin",
        )
    except NativeStageError as exc:
        raise AppBundleError(str(exc)) from exc
