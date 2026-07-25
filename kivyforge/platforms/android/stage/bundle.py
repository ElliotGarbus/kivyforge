"""Assemble the ABI-independent Python asset bundle (android/04 §asset bundle).

Layout under ``app/src/main/assets/_python_bundle/``:

- ``stdlib/``        — the runtime's pure-Python stdlib (no ``lib-dynload``,
  no ``__pycache__``, no ``*.gz`` — AGP auto-decompresses ``.gz`` assets,
  loadmodel findings §corrections #5; ``test``/``idlelib``/``turtledemo``
  excluded for size, matching the proven prototype).
- ``site-packages/`` — pure-Python content of the installed wheels (``.so``s
  and ``.libs/`` were hoisted into ``jniLibs``).
- ``app/``           — the user's ``app_dir`` payload.
- ``bootstrap/``     — the finder module, Kivy's ``_kivy_bootstrap`` contract
  module, and ``ext_manifest.json``.
- ``VERSION``        — content stamp; a changed bundle re-extracts on-device.

**ABI-independent by construction, and verified so**: the bundle is assembled
from the canonical ABI (first in ``abis``); every other ABI's non-``.so``
site-packages payload must be byte-for-byte identical or the build fails
naming the path and both hashes (version skew is already rejected at lock
time; this catches content skew).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from kivyforge.artifacts.verify import sha256_file

BUNDLE_DIRNAME = "_python_bundle"

_STDLIB_EXCLUDED_DIRS = {
    "__pycache__",
    "lib-dynload",
    "site-packages",
    "test",
    "idlelib",
    "turtledemo",
}


class BundleError(Exception):
    pass


def assemble_bundle(
    bundle_dir: Path,
    *,
    stdlib_src: Path,
    site_packages_by_abi: dict[str, Path],
    canonical_abi: str,
    app_src: Path,
    finder_source: str,
    kivy_bootstrap_source: str,
    ext_manifest_json: str,
    selftest_source: str = "",
) -> str:
    """Assemble the bundle; returns the content stamp written to ``VERSION``."""
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    _copy_stdlib(stdlib_src, bundle_dir / "stdlib")
    canonical_sp = site_packages_by_abi[canonical_abi]
    _copy_pure(canonical_sp, bundle_dir / "site-packages")
    _assert_abi_identity(site_packages_by_abi, canonical_abi)
    _copy_app(app_src, bundle_dir / "app")

    bootstrap = bundle_dir / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "_kivyforge_bootstrap.py").write_text(
        finder_source, encoding="utf-8"
    )
    # Required, not optional: Kivy resolves the Activity by importing this
    # module, so an app built without it would start and then fail the moment
    # Kivy needed the Activity.
    (bootstrap / "_kivy_bootstrap.py").write_text(
        kivy_bootstrap_source, encoding="utf-8"
    )
    if selftest_source:
        (bootstrap / "_kivyforge_selftest.py").write_text(
            selftest_source, encoding="utf-8"
        )
    (bootstrap / "ext_manifest.json").write_text(
        ext_manifest_json, encoding="utf-8"
    )

    stamp = _content_stamp(bundle_dir)
    (bundle_dir / "VERSION").write_text(stamp, encoding="utf-8")
    return stamp


def _copy_stdlib(src: Path, dest: Path) -> None:
    def ignore(directory: str, names: list[str]) -> list[str]:
        return [
            n
            for n in names
            if n in _STDLIB_EXCLUDED_DIRS or n.endswith(".gz")
        ]

    shutil.copytree(src, dest, ignore=ignore)


def _copy_pure(src: Path, dest: Path) -> None:
    """Copy an installed site-packages tree minus native payload.

    ``dist-info/direct_url.json`` is dropped entirely: pip writes the install
    source into it (a per-ABI ``file:///`` URL for vendored wheels), which
    both breaks ABI identity by design and would leak local host paths into
    the shipped APK.
    """

    def ignore(directory: str, names: list[str]) -> list[str]:
        out = [n for n in names if n == "__pycache__" or n.endswith(".so")]
        if Path(directory).name.endswith(".dist-info"):
            out += [n for n in names if n == "direct_url.json"]
        # top-level flat .libs/ was hoisted into jniLibs
        if Path(directory).resolve() == src.resolve():
            out += [n for n in names if n == ".libs"]
        return out

    if src.exists():
        shutil.copytree(src, dest, ignore=ignore)
    else:
        dest.mkdir(parents=True)


def _copy_app(src: Path, dest: Path) -> None:
    if not src.is_dir():
        raise BundleError(
            f"[tool.kivy].app_dir does not exist or is not a directory: {src}"
        )

    def ignore(directory: str, names: list[str]) -> list[str]:
        return [n for n in names if n == "__pycache__"]

    shutil.copytree(src, dest, ignore=ignore)


def _assert_abi_identity(
    site_packages_by_abi: dict[str, Path], canonical_abi: str
) -> None:
    """Every ABI's non-``.so`` payload must match the canonical ABI's exactly."""
    canonical = _pure_hashes(site_packages_by_abi[canonical_abi])
    for abi, sp in site_packages_by_abi.items():
        if abi == canonical_abi:
            continue
        other = _pure_hashes(sp)
        if other == canonical:
            continue
        for rel in sorted(set(canonical) | set(other)):
            a, b = canonical.get(rel), other.get(rel)
            if a != b:
                raise BundleError(
                    f"ABI content skew in the pure-Python payload: {rel!r} is "
                    f"{'missing' if a is None else a[:12] + '…'} for "
                    f"{canonical_abi} but "
                    f"{'missing' if b is None else b[:12] + '…'} for {abi}.\n"
                    f"  An ABI slice shipping different Python source/data at "
                    f"the same version cannot back a single shared bundle "
                    f"(android/04 §asset bundle)."
                )
        raise BundleError(  # pragma: no cover - loop above always raises
            f"ABI content skew between {canonical_abi} and {abi}"
        )


def _pure_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        parts = rel.parts
        if "__pycache__" in parts or parts[0] == ".libs":
            continue
        if path.suffix == ".so":
            continue
        # dist-info RECORD/WHEEL are per-ABI BY DESIGN (they list the wheel's
        # own files/tags, which include the ABI-specific .so names), so they
        # are exempt from the identity assertion; the canonical ABI's copies
        # ship in the bundle. Everything else in dist-info stays checked.
        if (
            len(parts) >= 2
            and parts[-2].endswith(".dist-info")
            and parts[-1] in ("RECORD", "WHEEL", "direct_url.json")
        ):
            continue
        out[rel.as_posix()] = sha256_file(path)
    return out


def _content_stamp(bundle_dir: Path) -> str:
    """A deterministic stamp over every (relpath, sha256) pair in the bundle."""
    digest = hashlib.sha256()
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle_dir).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    return digest.hexdigest()[:16]
