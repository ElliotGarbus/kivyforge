"""Platform-neutral native-binary staging mechanics (shared by desktop backends).

Each desktop backend declares a ``[tool.kivy.<platform>.native.binaries]``
channel whose entries are fetched + SHA-256-verified from the platform lock and
staged into the bundle's ``bin`` directory — a single native file copied in with
its exec bit set, or a ``.zip`` / ``.tar.gz`` / ``.tgz`` of several extracted
with a path-traversal guard. ``bin/`` is a single flat namespace, so two entries
staging to the same path is a hard error (a silent clobber otherwise).

This module owns the mechanics so the security-sensitive ``_safe_extract``
(zip path-traversal) and the ``tarfile`` ``filter="data"`` extractor live in
exactly one audited place. It raises the neutral
:class:`NativeStageError`; each backend's thin wrapper translates that into its
own bundle-error type (the ``NativeBinaryResolverError`` →
``WheelRuntimeBuildError`` pattern used in the lock builder).
"""

from __future__ import annotations

import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.artifacts.verify import HashMismatch

if TYPE_CHECKING:
    from kivyforge.lock.wheelruntime.model import LockedNativeBinary


class NativeStageError(Exception):
    """A native-binary staging failure (translated to the caller's bundle error)."""


def stage_binaries(
    binaries: tuple[LockedNativeBinary, ...],
    parent_dir: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
    bin_label: str,
) -> None:
    """Stage every pinned native binary into ``parent_dir/bin``.

    ``bin/`` is created under *parent_dir* only when *binaries* is non-empty
    (no empty ``bin/``). *bin_label* is the human-readable path used in the
    collision message (e.g. ``"Contents/Resources/bin"`` or ``"usr/bin"``).
    """
    if not binaries:
        return
    cache = cache or ArtifactCache()
    bin_dir = parent_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    # bin/ is a single flat namespace (helpers run by name off PATH; libraries
    # load by path/soname), so two entries must never stage a file to the same
    # path — the second would silently clobber the first. Track every claimed
    # path and fail loudly instead.
    claimed: dict[str, str] = {}
    for entry in binaries:
        _stage_one(
            entry,
            bin_dir,
            claimed,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
            bin_label=bin_label,
        )


def _stage_one(
    entry: LockedNativeBinary,
    bin_dir: Path,
    claimed: dict[str, str],
    *,
    project_root: Path,
    cache: ArtifactCache,
    no_cache: bool,
    bin_label: str,
) -> None:
    source = entry.url or entry.path or ""
    # Stage single files under their *source* basename (copied "as-is") so a
    # library keeps its extension for by-path/by-name loads.
    filename = source.rsplit("/", 1)[-1] or entry.name
    fetched = _fetch(entry, filename, project_root, cache, no_cache)
    lowered = source.lower()
    if lowered.endswith(".zip"):
        _extract_zip(fetched, bin_dir, claimed, entry.name, bin_label)
    elif lowered.endswith((".tar.gz", ".tgz")):
        _extract_tar(fetched, bin_dir, claimed, entry.name, bin_label)
    else:
        rel = Path(filename)
        _claim(claimed, rel, entry.name, bin_label)
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
        raise NativeStageError(str(exc)) from exc


def _extract_zip(
    archive: Path,
    bin_dir: Path,
    claimed: dict[str, str],
    entry_name: str,
    bin_label: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="kivy-nb-stage-") as tmp:
        staged = Path(tmp)
        with zipfile.ZipFile(archive) as zf:
            _safe_extract(zf, staged)
        for src in sorted(staged.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(staged)
            _claim(claimed, rel, entry_name, bin_label)
            dest = bin_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            _make_executable(dest)


def _extract_tar(
    archive: Path,
    bin_dir: Path,
    claimed: dict[str, str],
    entry_name: str,
    bin_label: str,
) -> None:
    """Extract a ``.tar.gz`` / ``.tgz`` into ``bin_dir`` with the same guards as zip.

    ``.tar.gz`` is the dominant distribution format for Linux SDKs; without this
    a tarball ``source`` would land in ``bin/`` as one opaque, exec-bit'd file.
    Uses ``tarfile``'s hardened ``filter="data"`` extractor — the tar analog of
    :func:`_safe_extract` — which strips symlinks/hardlinks/device nodes and
    rejects absolute/escaping members (more important for tar than zip, since
    tar *restores* symlinks and special files).
    """
    with tempfile.TemporaryDirectory(prefix="kivy-nb-stage-") as tmp:
        staged = Path(tmp)
        try:
            with tarfile.open(archive, "r:*") as tf:
                tf.extractall(staged, filter="data")  # noqa: S202 — hardened filter
        except tarfile.FilterError as exc:
            raise NativeStageError(
                f"unsafe path in native-binary archive: {exc}"
            ) from exc
        except tarfile.TarError as exc:
            raise NativeStageError(
                f"could not read native-binary archive {archive.name}: {exc}"
            ) from exc
        for src in sorted(staged.rglob("*")):
            # The "data" filter drops symlinks/special files; copy only regular
            # files (a lingering symlink is skipped rather than dereferenced).
            if src.is_symlink() or not src.is_file():
                continue
            rel = src.relative_to(staged)
            _claim(claimed, rel, entry_name, bin_label)
            dest = bin_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            _make_executable(dest)


def _claim(claimed: dict[str, str], rel: Path, entry_name: str, bin_label: str) -> None:
    """Reserve ``bin/<rel>`` for *entry_name*; raise if already taken.

    Prevents one native-binary entry from silently overwriting another (two
    single files with the same basename, two zips sharing a member path, or a
    single file colliding with a zip member).
    """
    key = rel.as_posix()
    prev = claimed.get(key)
    if prev is not None:
        owners = entry_name if prev == entry_name else f"{prev!r} and {entry_name!r}"
        raise NativeStageError(
            f"native binaries stage colliding path bin/{key} "
            f"({'duplicate inside ' + owners if prev == entry_name else owners}).\n"
            f"  Every native binary must stage to a unique path in "
            f"{bin_label}. Rename the artifact (or its source), or "
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
            raise NativeStageError(f"unsafe path in native-binary archive: {member!r}")
    zf.extractall(target)  # noqa: S202 — members validated just above
