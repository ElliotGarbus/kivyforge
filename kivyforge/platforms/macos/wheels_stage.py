"""Install the locked wheels into the ``.app``'s ``lib/`` (site-packages).

Wheels are fetched + SHA-256-verified from ``pylock.macos.toml`` (URL or vendored
path) and unpacked directly — no pip, so the bundler is independent of the host
interpreter's version/arch. Per package, coverage for the assembly archs is
satisfied by a ``universal2`` wheel, a pure-Python (``py3-none-any``) wheel, or a
matching per-arch wheel; a universal2 *build* assembled from per-arch wheels
``lipo``-merges the ``.so``/``.dylib`` extensions of the extra arch(es) into the
base tree.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.lock.model import LockedPackage, LockedWheel

from . import AppBundleError
from .lock import wheel_arch
from .machotools import is_macho, lipo_create


def stage_wheels(
    packages: tuple[LockedPackage, ...],
    archs: tuple[str, ...],
    lib_dir: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
) -> None:
    """Unpack every package's wheels for *archs* into *lib_dir*."""
    cache = cache or ArtifactCache()
    if lib_dir.exists():
        shutil.rmtree(lib_dir)
    lib_dir.mkdir(parents=True)

    for pkg in packages:
        base_wheel, extra_wheels = _select_wheels(pkg, archs)
        _unpack(_fetch(base_wheel, project_root, cache, no_cache), lib_dir)
        for extra in extra_wheels:
            _merge_wheel_binaries(_fetch(extra, project_root, cache, no_cache), lib_dir)


def _select_wheels(
    pkg: LockedPackage, archs: tuple[str, ...]
) -> tuple[LockedWheel, list[LockedWheel]]:
    """Pick the base wheel to unpack + any per-arch wheels to lipo-merge in.

    Prefers a single fat wheel (pure-Python or universal2); otherwise assembles
    from per-arch wheels (base = first arch, extras = the rest).
    """
    by_arch: dict[str, LockedWheel] = {}
    for wheel in pkg.wheels:
        if wheel.is_pure_python:
            return wheel, []
        arch = wheel_arch(wheel.platform_tag)
        if arch == "universal2":
            return wheel, []
        if arch is not None:
            by_arch[arch] = wheel

    per_arch = [by_arch[a] for a in archs if a in by_arch]
    if len(per_arch) != len(archs):
        missing = [a for a in archs if a not in by_arch]
        raise AppBundleError(
            f"{pkg.name} {pkg.version} has no wheel for arch(es) "
            f"{', '.join(missing)} in the lock.\n"
            "  Re-run `kivyforge lock -p macos` (or narrow [tool.kivy.macos].archs)."
        )
    return per_arch[0], per_arch[1:]


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


def _merge_wheel_binaries(wheel: Path, lib_dir: Path) -> None:
    """lipo-merge the Mach-O extensions of a per-arch *wheel* into *lib_dir*."""
    with tempfile.TemporaryDirectory(prefix="kivy-wheel-arch-") as tmp:
        staged = Path(tmp)
        _unpack(wheel, staged)
        for src in sorted(staged.rglob("*")):
            if not is_macho(src):
                continue
            rel = src.relative_to(staged)
            dest = lib_dir / rel
            if not is_macho(dest):
                # New extension only this arch ships; copy it in thin.
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                continue
            merged = dest.with_suffix(dest.suffix + ".universal")
            lipo_create([dest, src], merged)
            merged.replace(dest)


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
