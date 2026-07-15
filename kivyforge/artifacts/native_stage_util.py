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
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.artifacts.verify import HashMismatch

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from kivyforge.lock.wheelruntime.model import LockedNativeBinary

# Reserved DOS device names (case-insensitive), illegal as a path component on
# Windows even with an extension (``NUL.dll`` is still reserved).
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


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
    casefold: bool = False,
    reject_windows_names: bool = False,
    validate: Callable[[Path], None] | None = None,
) -> None:
    """Stage every pinned native binary into ``parent_dir/bin``.

    ``bin/`` is created under *parent_dir* only when *binaries* is non-empty
    (no empty ``bin/``). *bin_label* is the human-readable path used in the
    collision message (e.g. ``"Contents/Resources/bin"`` or ``"usr/bin"``).

    Windows-facing options (defaults keep macOS/Linux behavior unchanged):
    *casefold* keys the collision check case-insensitively (so ``SDK.dll`` and
    ``sdk.dll`` collide on a case-insensitive filesystem); *reject_windows_names*
    rejects members that are reserved DOS device names, contain ``:`` (alternate
    data streams), or end in a dot/space; *validate* is called on each staged
    file (e.g. a PE architecture check).
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
            casefold=casefold,
            reject_windows_names=reject_windows_names,
            validate=validate,
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
    casefold: bool,
    reject_windows_names: bool,
    validate: Callable[[Path], None] | None,
) -> None:
    source = entry.url or entry.path or ""
    # Stage single files under their *source* basename (copied "as-is") so a
    # library keeps its extension for by-path/by-name loads.
    filename = source.rsplit("/", 1)[-1] or entry.name
    fetched = _fetch(entry, filename, project_root, cache, no_cache)
    lowered = source.lower()
    if lowered.endswith(".zip"):
        _extract_zip(
            fetched,
            bin_dir,
            claimed,
            entry.name,
            bin_label,
            casefold=casefold,
            reject_windows_names=reject_windows_names,
            validate=validate,
        )
    elif lowered.endswith((".tar.gz", ".tgz")):
        _extract_tar(
            fetched,
            bin_dir,
            claimed,
            entry.name,
            bin_label,
            casefold=casefold,
            reject_windows_names=reject_windows_names,
            validate=validate,
        )
    else:
        rel = Path(filename)
        if reject_windows_names:
            _reject_windows_unsafe(rel, entry.name, bin_label)
        _claim(claimed, rel, entry.name, bin_label, casefold=casefold)
        dest = bin_dir / rel
        shutil.copy2(fetched, dest)
        _make_executable(dest)
        if validate is not None:
            validate(dest)


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
    *,
    casefold: bool = False,
    reject_windows_names: bool = False,
    validate: Callable[[Path], None] | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="kivy-nb-stage-") as tmp:
        staged = Path(tmp)
        with zipfile.ZipFile(archive) as zf:
            if reject_windows_names:
                _reject_windows_unsafe_names(zf.namelist(), entry_name, bin_label)
            _safe_extract(zf, staged)
        for src in sorted(staged.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(staged)
            _claim(claimed, rel, entry_name, bin_label, casefold=casefold)
            dest = bin_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            _make_executable(dest)
            if validate is not None:
                validate(dest)


def _extract_tar(
    archive: Path,
    bin_dir: Path,
    claimed: dict[str, str],
    entry_name: str,
    bin_label: str,
    *,
    casefold: bool = False,
    reject_windows_names: bool = False,
    validate: Callable[[Path], None] | None = None,
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
                if reject_windows_names:
                    _reject_windows_unsafe_names(tf.getnames(), entry_name, bin_label)
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
            _claim(claimed, rel, entry_name, bin_label, casefold=casefold)
            dest = bin_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            _make_executable(dest)
            if validate is not None:
                validate(dest)


def _claim(
    claimed: dict[str, str],
    rel: Path,
    entry_name: str,
    bin_label: str,
    *,
    casefold: bool = False,
) -> None:
    """Reserve ``bin/<rel>`` for *entry_name*; raise if already taken.

    Prevents one native-binary entry from silently overwriting another (two
    single files with the same basename, two zips sharing a member path, or a
    single file colliding with a zip member). When *casefold* is set the key is
    lowercased, so ``SDK.dll`` and ``sdk.dll`` collide on a case-insensitive
    target filesystem (Windows).
    """
    key = rel.as_posix()
    if casefold:
        key = key.lower()
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
    # NTFS has no POSIX exec bit; "executable" is determined by extension/loader.
    # Skip explicitly on Windows so the POSIX chmod is a documented no-op there.
    if sys.platform == "win32":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _reject_windows_unsafe_names(
    names: Iterable[str], entry_name: str, bin_label: str
) -> None:
    """Reject any archive member illegal on Windows (reserved / ADS / trailing)."""
    for name in names:
        _reject_windows_unsafe(Path(name.replace("\\", "/")), entry_name, bin_label)


def _reject_windows_unsafe(rel: Path, entry_name: str, bin_label: str) -> None:
    """Raise if any component of *rel* is illegal on a Windows filesystem.

    Reserved DOS device names (``NUL``, ``COM1`` ...), alternate data streams
    (a ``:`` in a component), and trailing dots/spaces (which Windows silently
    strips, changing the staged name) are all rejected loudly rather than
    producing a surprising or unusable ``bin/`` layout.
    """
    for part in rel.parts:
        if not part or part in (".", ".."):
            continue
        if ":" in part:
            raise NativeStageError(
                f"native binary {entry_name!r} stages a path with an alternate "
                f"data stream (':') in {bin_label}/{rel.as_posix()!r}; rename it."
            )
        if part != part.rstrip(" ."):
            raise NativeStageError(
                f"native binary {entry_name!r} stages a component ending in a dot "
                f"or space ({part!r}) in {bin_label}; Windows would silently strip "
                "it. Rename the artifact."
            )
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise NativeStageError(
                f"native binary {entry_name!r} stages a reserved Windows device "
                f"name ({part!r}) in {bin_label}; rename the artifact."
            )


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    base = target.resolve()
    for member in zf.namelist():
        resolved = (target / member).resolve()
        if not (resolved == base or base in resolved.parents):
            raise NativeStageError(f"unsafe path in native-binary archive: {member!r}")
    zf.extractall(target)  # noqa: S202 — members validated just above
