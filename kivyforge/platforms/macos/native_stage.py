"""Stage locked native binaries into the ``.app``'s ``Resources/bin`` (macos-spec).

The ``[tool.kivy.macos.native.binaries]`` channel: each entry is fetched +
SHA-256-verified from ``pylock.macos.toml`` (URL or vendored path), then staged
into ``Contents/Resources/bin`` — a single native file copied in with its exec
bit set, or a ``.zip`` of several extracted with a path-traversal guard. The
directory is created only when the lock actually pins binaries (no empty
``bin/``). The bundle's signing sweep later covers everything under it.
"""

from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.artifacts.verify import HashMismatch
from kivyforge.lock.wheelruntime.model import LockedNativeBinary

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
    if not lock.native_binaries:
        return
    cache = cache or ArtifactCache()
    bin_dir = resources / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    # bin/ is a single flat namespace (helpers run by name off PATH; dylibs load
    # by path), so two entries must never stage a file to the same path — the
    # second would silently clobber the first. Track every claimed path and fail
    # loudly instead.
    claimed: dict[str, str] = {}
    for entry in lock.native_binaries:
        _stage_one(
            entry,
            bin_dir,
            claimed,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )


def _stage_one(
    entry: LockedNativeBinary,
    bin_dir: Path,
    claimed: dict[str, str],
    *,
    project_root: Path,
    cache: ArtifactCache,
    no_cache: bool,
) -> None:
    source = entry.url or entry.path or ""
    # Stage single files under their *source* basename (copied "as-is", macos-
    # spec) so a dylib keeps its .dylib extension for by-path ctypes loads.
    filename = source.rsplit("/", 1)[-1] or entry.name
    fetched = _fetch(entry, filename, project_root, cache, no_cache)
    if source.lower().endswith(".zip"):
        _extract_zip(fetched, bin_dir, claimed, entry.name)
    else:
        rel = Path(filename)
        _claim(claimed, rel, entry.name)
        dest = bin_dir / rel
        shutil.copy2(fetched, dest)
        _make_executable(dest)


def _fetch(
    entry: LockedNativeBinary,
    filename: str,
    project_root: Path,
    cache: ArtifactCache,
    no_cache: bool,
) -> Path:
    try:
        return fetch_artifact(
            name=entry.name,
            sha256=entry.sha256,
            filename=filename,
            url=entry.url,
            path=entry.path,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )
    except (DownloadError, HashMismatch) as exc:
        raise AppBundleError(str(exc)) from exc


def _extract_zip(
    archive: Path, bin_dir: Path, claimed: dict[str, str], entry_name: str
) -> None:
    with tempfile.TemporaryDirectory(prefix="kivy-nb-stage-") as tmp:
        staged = Path(tmp)
        with zipfile.ZipFile(archive) as zf:
            _safe_extract(zf, staged)
        for src in sorted(staged.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(staged)
            _claim(claimed, rel, entry_name)
            dest = bin_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            _make_executable(dest)


def _claim(claimed: dict[str, str], rel: Path, entry_name: str) -> None:
    """Reserve ``bin/<rel>`` for *entry_name*; raise if already taken.

    Prevents one native-binary entry from silently overwriting another (two
    single files with the same basename, two zips sharing a member path, or a
    single file colliding with a zip member).
    """
    key = rel.as_posix()
    prev = claimed.get(key)
    if prev is not None:
        owners = entry_name if prev == entry_name else f"{prev!r} and {entry_name!r}"
        raise AppBundleError(
            f"native binaries stage colliding path bin/{key} "
            f"({'duplicate inside ' + owners if prev == entry_name else owners}).\n"
            f"  Every native binary must stage to a unique path in "
            f"Contents/Resources/bin. Rename the artifact (or its source), or "
            f"drop the duplicate, so no two entries write the same file."
        )
    claimed[key] = entry_name


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    base = target.resolve()
    for member in zf.namelist():
        resolved = (target / member).resolve()
        if not (resolved == base or base in resolved.parents):
            raise AppBundleError(f"unsafe path in native-binary archive: {member!r}")
    zf.extractall(target)  # noqa: S202 — members validated just above
