"""Native-binary resolver (the ``native.binaries`` channel, macos-spec).

``kivyforge lock`` reads each declared ``[tool.kivy.<platform>.native.binaries]``
entry's ``source`` (a single native binary or a ``.zip`` of several, referenced
by URL or repo-relative path) and computes its SHA-256. Those pins land in
``pylock.<platform>.toml`` so ``kivyforge build`` can re-fetch the artifact by
``url``+``sha256`` (or ``path``) and stage it into the bundle's ``bin`` directory
reproducibly.

The download backend is injectable (``Downloader``) so unit tests stay hermetic
(no network). This mirrors ``platforms/ios/lock/xcframework.py`` without the
per-slice framework enumeration — a native binary has no slices to read.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from kivyforge.artifacts.verify import sha256_file
from kivyforge.config.model import NativeBinaryDep
from kivyforge.lock.find_links import FindLinksError, wheel_path_from_project_root

from .model import LockedNativeBinary

if TYPE_CHECKING:
    from kivyforge.artifacts.cache import ArtifactCache
    from kivyforge.artifacts.download import Downloader


class NativeBinaryResolverError(Exception):
    """A native-binary resolution failure surfaced with an actionable message."""


def resolve_native_binaries(
    declared: tuple[NativeBinaryDep, ...],
    *,
    project_root: Path,
    downloader: Downloader | None = None,
    cache: ArtifactCache | None = None,
    offline: bool = False,
) -> tuple[LockedNativeBinary, ...]:
    """Resolve declared native binaries into SHA-256-pinned lock entries.

    Returns entries sorted by ``(name, version)``. The downloader is only invoked
    for remote (URL) sources, so a project with only vendored binaries (or none)
    never needs network access. ``cache`` is accepted for call-site symmetry with
    the build-time fetch path; lock resolution computes the pin from scratch.
    """
    if not declared:
        return ()
    out = [
        _resolve_one(
            dep, project_root=project_root, downloader=downloader, offline=offline
        )
        for dep in declared
    ]
    out.sort(key=lambda x: (x.name.lower(), x.version))
    return tuple(out)


def _resolve_one(
    dep: NativeBinaryDep,
    *,
    project_root: Path,
    downloader: Downloader | None,
    offline: bool,
) -> LockedNativeBinary:
    is_url = dep.source.startswith(("http://", "https://"))
    if is_url:
        with tempfile.TemporaryDirectory(prefix="kivy-nb-lock-") as tmp:
            archive = _download(dep, Path(tmp), downloader=downloader, offline=offline)
            sha256 = sha256_file(archive)
        return LockedNativeBinary(
            name=dep.name, version=dep.version, sha256=sha256, url=dep.source
        )
    resolved, rel = _resolve_local(dep, project_root=project_root)
    return LockedNativeBinary(
        name=dep.name, version=dep.version, sha256=sha256_file(resolved), path=rel
    )


def _download(
    dep: NativeBinaryDep,
    tmpdir: Path,
    *,
    downloader: Downloader | None,
    offline: bool,
) -> Path:
    # Imported lazily: artifacts.download imports lock.find_links, so a top-level
    # import here would close an import cycle (lock <-> artifacts).
    from kivyforge.artifacts.download import DownloadError, UrllibDownloader

    if offline:
        raise NativeBinaryResolverError(
            f"native binary {dep.name!r}: cannot download {dep.source} while "
            f"offline.\n  Re-run `kivyforge lock` with network access, or vendor "
            f"the file and point `source` at a repo-relative path."
        )
    dl = downloader or UrllibDownloader()
    filename = dep.source.rsplit("/", 1)[-1] or dep.name
    dest = tmpdir / filename
    try:
        dl.fetch_to(dep.source, dest)
    except DownloadError as exc:
        raise NativeBinaryResolverError(f"native binary {dep.name!r}: {exc}") from exc
    return dest


def _resolve_local(dep: NativeBinaryDep, *, project_root: Path) -> tuple[Path, str]:
    root = project_root.resolve()
    resolved = (root / dep.source).resolve()
    try:
        rel = wheel_path_from_project_root(root, resolved)
    except FindLinksError as exc:
        raise NativeBinaryResolverError(
            f"native binary {dep.name!r}: source {dep.source!r} resolves to "
            f"{resolved}, which is outside the project directory and its parent.\n"
            f"  Vendored native binaries must live under the project directory "
            f"or a shared sibling directory (e.g. examples/binaries/)."
        ) from exc
    if not resolved.is_file():
        raise NativeBinaryResolverError(
            f"native binary {dep.name!r}: vendored file not found at {dep.source!r}."
        )
    return resolved, rel
