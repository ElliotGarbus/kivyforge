"""Install the locked wheels into the ``.app``'s ``lib/`` (site-packages).

Wheels are fetched + SHA-256-verified from ``pylock.macos.toml`` (URL or vendored
path) and unpacked directly — no pip, so the bundler is independent of the host
interpreter's version/arch.

macOS builds are arm64-only, so exactly one wheel is unpacked per package and
there is no ``lipo`` merge. A ``universal2`` wheel is still perfectly valid — it
*contains* arm64 — which is why the arch match accepts it alongside a thin
``arm64`` wheel and a pure-Python one.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.lock.model import LockedPackage, LockedWheel

from . import AppBundleError
from .lock import wheel_arch


def stage_wheels(
    packages: tuple[LockedPackage, ...],
    arch: str,
    lib_dir: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
) -> None:
    """Unpack every package's wheel for *arch* into *lib_dir*."""
    cache = cache or ArtifactCache()
    if lib_dir.exists():
        shutil.rmtree(lib_dir)
    lib_dir.mkdir(parents=True)

    for pkg in packages:
        wheel = _select_wheel(pkg, arch)
        _unpack(_fetch(wheel, project_root, cache, no_cache), lib_dir)


def _select_wheel(pkg: LockedPackage, arch: str) -> LockedWheel:
    """The one wheel to unpack for *arch*.

    Pure-Python and ``universal2`` wheels both satisfy an arm64 build — the
    latter *contains* arm64 — as does a thin ``arm64`` wheel.
    """
    for wheel in pkg.wheels:
        if wheel.is_pure_python:
            return wheel
        if wheel_arch(wheel.platform_tag) in ("universal2", arch):
            return wheel
    raise AppBundleError(
        f"{pkg.name} {pkg.version} has no {arch} wheel in the lock.\n"
        f"  Re-run `kivyforge lock -p macos`."
    )


def _fetch(wheel: LockedWheel, project_root, cache, no_cache) -> Path:
    try:
        return fetch_artifact(
            name=wheel.name,
            sha256=wheel.sha256,
            filename=wheel.name,
            url=wheel.url,
            path=wheel.path,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )
    except DownloadError as exc:
        raise AppBundleError(str(exc)) from exc


def _unpack(wheel: Path, target: Path) -> None:
    """Extract a wheel into *target*, normalizing ``.data/{purelib,platlib}``."""
    with zipfile.ZipFile(wheel) as zf:
        _safe_extract(zf, target)
    for data_dir in list(target.glob("*.data")):
        for sub in ("purelib", "platlib"):
            src = data_dir / sub
            if src.is_dir():
                _merge_tree(src, target)
        shutil.rmtree(data_dir, ignore_errors=True)


def _merge_tree(src: Path, dest: Path) -> None:
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            target.mkdir(exist_ok=True)
            _merge_tree(item, target)
        else:
            shutil.copy2(item, target)


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    base = target.resolve()
    for member in zf.namelist():
        resolved = (target / member).resolve()
        if not (resolved == base or base in resolved.parents):
            raise AppBundleError(f"unsafe path in wheel: {member!r}")
    zf.extractall(target)  # noqa: S202 — members validated just above
