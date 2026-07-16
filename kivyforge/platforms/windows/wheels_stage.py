r"""Install the locked wheels into the bundled prefix — a no-pip scheme installer.

Wheels are fetched + SHA-256-verified from ``pylock.windows.toml`` (URL or
vendored path) and unpacked directly. This is a **Windows-only, deterministic
wheel-scheme installer**: it never resolves dependencies, never shells out to
the host ``pip``, and never applies the host interpreter's compatibility rules —
the lock already decided everything. Windows ships one arch (``amd64``) per
onedir, so per package a single wheel satisfies coverage: a pure-Python
(``py3-none-any``) wheel or a ``win_amd64`` wheel.

arm64: this staging logic is already arch-generic (it routes by
``wheel_arch(tag)``), so only this docstring's "one arch (amd64)" /
"``win_amd64``" wording changes when ``win_arm64`` lands — no code change here.
See arm64-windows.md §9.

Scheme routing into the ``<bundle>\python`` prefix (the load-bearing part):

* package root + ``.data/{purelib,platlib}`` -> ``Lib\site-packages``
* ``.data/data`` -> the **prefix root** (so ``share\<dep>\bin`` lands at
  ``<prefix>\share\<dep>\bin`` and survives) -- a site-packages-only copy
  silently drops every SDL DLL and Kivy dies importing its window provider. This
  is the real DLL-discovery invariant; "pip is load-bearing" it is not.
* ``.data/scripts`` -> ``Scripts``
* ``.data/headers`` -> ``Include``

The shipped macOS/Linux ``_unpack`` is intentionally left untouched.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.lock.model import LockedPackage, LockedWheel

from . import WindowsBundleError
from .lock import wheel_arch


def stage_wheels(
    packages: tuple[LockedPackage, ...],
    arch: str,
    prefix: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
) -> None:
    """Install every package's wheel for *arch* into the *prefix* schemes.

    *prefix* is the staged CPython home (``<bundle>\\python``). Its existing
    ``Lib\\site-packages`` (from the runtime archive) is preserved and installed
    into; the runtime must already be staged.
    """
    cache = cache or ArtifactCache()
    site_packages = prefix / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    for pkg in packages:
        wheel = _select_wheel(pkg, arch)
        _install(_fetch(wheel, project_root, cache, no_cache), prefix, site_packages)


def _select_wheel(pkg: LockedPackage, arch: str) -> LockedWheel:
    """Pick the wheel to install: pure-Python, else the one covering *arch*."""
    for wheel in pkg.wheels:
        if wheel.is_pure_python:
            return wheel
    for wheel in pkg.wheels:
        if any(wheel_arch(sub) == arch for sub in wheel.platform_tag.split(".")):
            return wheel
    raise WindowsBundleError(
        f"{pkg.name} {pkg.version} has no wheel for arch {arch} in the lock.\n"
        "  Re-run `kivyforge lock -p windows`."
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
        raise WindowsBundleError(str(exc)) from exc


def _install(wheel: Path, prefix: Path, site_packages: Path) -> None:
    """Unpack *wheel*, routing each install scheme to its prefix location."""
    with zipfile.ZipFile(wheel) as zf:
        _safe_extract(zf, site_packages)
    # Route the .data schemes out of site-packages to their prefix locations.
    # purelib/platlib stay in site-packages; the rest move relative to prefix.
    scheme_targets = {
        "purelib": site_packages,
        "platlib": site_packages,
        "data": prefix,
        "scripts": prefix / "Scripts",
        "headers": prefix / "Include",
    }
    for data_dir in list(site_packages.glob("*.data")):
        for sub in sorted(p.name for p in data_dir.iterdir() if p.is_dir()):
            target = scheme_targets.get(sub)
            if target is None:
                # An unknown scheme subdir: route to the prefix root by name so
                # nothing declared in the wheel is silently dropped.
                target = prefix / sub
                _merge_tree(data_dir / sub, target)
                continue
            _merge_tree(data_dir / sub, target)
        shutil.rmtree(data_dir, ignore_errors=True)


def _merge_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            _merge_tree(item, target)
        else:
            shutil.copy2(item, target)


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    base = target.resolve()
    for member in zf.namelist():
        resolved = (target / member).resolve()
        if not (resolved == base or base in resolved.parents):
            raise WindowsBundleError(f"unsafe path in wheel: {member!r}")
    zf.extractall(target)  # noqa: S202 — members validated just above
