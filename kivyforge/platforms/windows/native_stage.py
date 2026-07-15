"""Stage locked native binaries into the onedir ``bin\\`` (windows-spec).

The ``[tool.kivy.windows.native.binaries]`` channel: each entry is fetched +
SHA-256-verified from ``pylock.windows.toml`` (URL or vendored path) and staged
into ``<bundle>\\bin`` — a single native file, or a ``.zip`` / ``.tar.gz`` /
``.tgz`` of several extracted with a path-traversal guard. ``bin\\`` is created
only when the lock actually pins binaries. The bootstrap registers ``<bundle>\\bin`` with
``os.add_dll_directory`` and prepends it to ``PATH``.

The staging mechanics live in the shared
:mod:`kivyforge.artifacts.native_stage_util`; this is the Windows-facing wrapper
that translates :class:`NativeStageError` into :class:`WindowsBundleError` and
supplies the Windows-specific guards: case-insensitive collision keys, reserved
DOS device name / alternate-data-stream rejection, and a PE machine-architecture
check (:mod:`~kivyforge.platforms.windows.petools`) so a wrong-arch DLL is caught
at assembly time rather than at load.
"""

from __future__ import annotations

from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.native_stage_util import NativeStageError, stage_binaries

from . import WindowsBundleError
from .lock import WindowsLockfile
from .petools import PeArchError, verify_pe_arch


def stage_native_binaries(
    lock: WindowsLockfile,
    bundle: Path,
    arch: str,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
) -> None:
    """Stage every pinned native binary for the lock into ``<bundle>\\bin``.

    Each staged PE is checked against *arch* (a wrong-architecture DLL fails the
    build with a clear message); non-PE members (data files, scripts) are
    ignored by the check.
    """

    def _validate(path: Path) -> None:
        try:
            verify_pe_arch(path, arch)
        except PeArchError as exc:
            raise NativeStageError(str(exc)) from exc

    try:
        stage_binaries(
            lock.native_binaries,
            bundle,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
            bin_label="bin",
            casefold=True,
            reject_windows_names=True,
            validate=_validate,
        )
    except NativeStageError as exc:
        raise WindowsBundleError(str(exc)) from exc
