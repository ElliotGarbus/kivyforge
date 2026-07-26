"""Resolve declared ``.aar``/``.jar`` archives to lock pins (android/02, channel 3).

Each ``[tool.kivy.android.native.aars]`` / ``.jars`` entry has an explicit
``source`` — a direct URL or a repo-relative vendored path. ``kivyforge lock``
reads the artifact (download for a URL, local read for a path) and pins its
SHA-256 into ``[[tool.kivyforge.android_libs]]``. Mirrors the iOS xcframework
resolver's posture, minus slice enumeration (an archive is a single flat file).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import Downloader, DownloadError, UrllibDownloader
from kivyforge.artifacts.verify import sha256_file
from kivyforge.config.model import AndroidArchiveDep

from .model import LockedAndroidLib


class ArchiveResolverError(Exception):
    pass


def resolve_android_libs(
    declared: tuple[AndroidArchiveDep, ...],
    *,
    project_root: Path,
    downloader: Downloader | None = None,
    cache: ArtifactCache | None = None,
    offline: bool = False,
) -> list[LockedAndroidLib]:
    """Pin every declared archive; deterministic (name, version) order."""
    out: list[LockedAndroidLib] = []
    for dep in sorted(declared, key=lambda d: (d.name.lower(), d.version)):
        out.append(
            _resolve_one(
                dep,
                project_root=project_root,
                downloader=downloader,
                cache=cache,
                offline=offline,
            )
        )
    return out


def _resolve_one(
    dep: AndroidArchiveDep,
    *,
    project_root: Path,
    downloader: Downloader | None,
    cache: ArtifactCache | None,
    offline: bool,
) -> LockedAndroidLib:
    if dep.source.startswith(("http://", "https://")):
        sha256 = _hash_remote(dep, downloader=downloader, cache=cache, offline=offline)
        return LockedAndroidLib(
            name=dep.name,
            kind=dep.kind,
            version=dep.version,
            url=dep.source,
            sha256=sha256,
        )
    local = (project_root / dep.source).resolve()
    if not local.is_file():
        raise ArchiveResolverError(
            f"{dep.kind} {dep.name!r}: vendored source does not exist: "
            f"{dep.source} (resolved to {local})"
        )
    return LockedAndroidLib(
        name=dep.name,
        kind=dep.kind,
        version=dep.version,
        path=dep.source,
        sha256=sha256_file(local),
    )


def _hash_remote(
    dep: AndroidArchiveDep,
    *,
    downloader: Downloader | None,
    cache: ArtifactCache | None,
    offline: bool,
) -> str:
    filename = dep.source.rsplit("/", 1)[-1]
    store = cache or ArtifactCache()
    cached = store.find_by_filename(filename)
    if cached is not None:
        return sha256_file(cached)
    if offline:
        raise ArchiveResolverError(
            f"{dep.kind} {dep.name!r} ({filename}) is not in the artifact cache "
            f"and --offline was passed.\n"
            f"  Run `kivyforge lock` online once, then retry."
        )
    fetcher = downloader or UrllibDownloader()
    with tempfile.TemporaryDirectory(prefix="kivyforge-lib-") as tmp:
        dest = Path(tmp) / filename
        try:
            fetcher.fetch_to(dep.source, dest)
        except DownloadError as exc:
            raise ArchiveResolverError(
                f"could not fetch {dep.kind} {dep.name!r} from {dep.source}: {exc}"
            ) from exc
        return sha256_file(dest)
