"""Stage locked native binaries into the AppDir's ``usr/bin`` (linux-spec).

The ``[tool.kivy.linux.native.binaries]`` channel: each entry is fetched +
SHA-256-verified from ``pylock.linux.toml`` (URL or vendored path), then staged
into ``usr/bin`` — a single native file copied in with its exec bit set, or a
``.zip`` / ``.tar.gz`` / ``.tgz`` of several extracted with a path-traversal
guard. The directory is created only when the lock actually pins binaries (no
empty ``bin/``). AppRun exposes ``usr/bin`` on ``PATH`` (helpers by name) and
appends it to ``LD_LIBRARY_PATH`` (libraries by soname).

The staging mechanics live in the shared
:mod:`kivyforge.artifacts.native_stage_util`; this module is the Linux-facing
wrapper that translates the neutral :class:`NativeStageError` into
``AppDirError``.
"""

from __future__ import annotations

from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.native_stage_util import NativeStageError, stage_binaries

from . import AppDirError
from .lock import LinuxLockfile


def stage_native_binaries(
    lock: LinuxLockfile,
    usr_dir: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
) -> None:
    """Stage every pinned native binary for the lock into ``usr_dir/bin``."""
    try:
        stage_binaries(
            lock.native_binaries,
            usr_dir,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
            bin_label="usr/bin",
        )
    except NativeStageError as exc:
        raise AppDirError(str(exc)) from exc
