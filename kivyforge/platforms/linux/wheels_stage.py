"""Install the locked wheels into the AppDir's ``usr/lib`` (site-packages).

Wheels are fetched + SHA-256-verified from ``pylock.linux.toml`` (URL or
vendored path) and unpacked directly — no pip, so the bundler is independent of
the host interpreter. Linux ships one arch per AppImage, so per package a single
wheel satisfies coverage: a pure-Python (``py3-none-any``) wheel or a manylinux
(or vendored ``linux_x86_64``) wheel matching the assembly arch. There is no
``lipo``-style merge as on macOS.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.lock.model import LockedPackage, LockedWheel

from . import AppDirError
from .lock import linux_wheel_arch


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
    """Pick the wheel to unpack: pure-Python, else the one covering *arch*."""
    for wheel in pkg.wheels:
        if wheel.is_pure_python:
            return wheel
    for wheel in pkg.wheels:
        if any(linux_wheel_arch(sub) == arch for sub in wheel.platform_tag.split(".")):
            return wheel
    raise AppDirError(
        f"{pkg.name} {pkg.version} has no wheel for arch {arch} in the lock.\n"
        "  Re-run `kivyforge lock -p linux`."
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
        raise AppDirError(str(exc)) from exc


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
            raise AppDirError(f"unsafe path in wheel: {member!r}")
    zf.extractall(target)  # noqa: S202 — members validated just above
