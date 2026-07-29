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

``byte_compile``/``strip_source`` (android/01 §build_settings) act on the
assembled tree just before the stamp is taken, so the stamp always describes
what actually ships.

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
    entry_point: str = "main",
    service_entry_points: dict[str, str] | None = None,
    byte_compile: tuple[str, ...] | None = None,
    strip_source: bool = False,
) -> str:
    """Assemble the bundle; returns the content stamp written to ``VERSION``."""
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    _copy_stdlib(stdlib_src, bundle_dir / "stdlib")
    canonical_sp = site_packages_by_abi[canonical_abi]
    _copy_pure(canonical_sp, bundle_dir / "site-packages")
    _assert_abi_identity(site_packages_by_abi, canonical_abi)
    _copy_app(
        app_src,
        bundle_dir / "app",
        entry_point=entry_point,
        service_entry_points=service_entry_points or {},
    )

    bootstrap = bundle_dir / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "_kivyforge_bootstrap.py").write_text(finder_source, encoding="utf-8")
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
    (bootstrap / "ext_manifest.json").write_text(ext_manifest_json, encoding="utf-8")

    if byte_compile is not None:
        _byte_compile(bundle_dir, compiler=byte_compile, strip_source=strip_source)

    stamp = _content_stamp(bundle_dir)
    (bundle_dir / "VERSION").write_text(stamp, encoding="utf-8")
    return stamp


def _byte_compile(
    bundle_dir: Path, *, compiler: tuple[str, ...], strip_source: bool
) -> None:
    """Compile the bundle's Python payload to ``.pyc`` in place (android/01).

    *compiler* is an interpreter argv prefix whose version matches the target
    runtime (empty for this interpreter); the caller is what establishes that,
    because a ``.pyc`` is only loadable by the exact CPython that wrote it.

    Two layouts, and the difference matters:

    - Keeping the source, the ``.pyc`` goes in ``__pycache__/`` as usual, so
      imports find it next to the ``.py`` it was built from.
    - Shipping ``.pyc`` only requires the *legacy* layout — PEP 3147 sourceless
      imports look for ``foo.pyc`` at the source's own path, never inside
      ``__pycache__/``. Compiling to ``__pycache__/`` and then deleting the
      ``.py`` would produce a bundle that imports nothing at all.

    Hash-based, unchecked invalidation (PEP 552) is used rather than the default
    mtime+size: it saves a stat per import on a device that cannot have a newer
    source than the one shipped, and it keeps an mtime out of every ``.pyc``.

    Paths are stripped to be bundle-relative for the same reason
    ``_copy_pure`` drops ``direct_url.json``: a ``.pyc`` records the path it was
    compiled from, so the default would both leak local host paths into the
    shipped APK and make the content stamp differ per machine.
    """
    for name in ("stdlib", "site-packages", "app", "bootstrap"):
        target = bundle_dir / name
        if not target.is_dir():
            continue
        if not _compile_tree(
            target, compiler=compiler, legacy=strip_source, stripdir=bundle_dir
        ):
            raise BundleError(
                f"byte-compiling the bundle's {name}/ failed; the output above "
                "names the file.\n"
                "  A syntax error in app code fails here rather than on-device; "
                "fix it, or set [tool.kivy.android.build_settings].byte_compile "
                "= false."
            )
        if strip_source:
            for source in target.rglob("*.py"):
                if source.with_suffix(".pyc").is_file():
                    source.unlink()
            # Nothing can import from __pycache__ once the sources are gone.
            for cache in target.rglob("__pycache__"):
                shutil.rmtree(cache, ignore_errors=True)


def _compile_tree(
    target: Path, *, compiler: tuple[str, ...], legacy: bool, stripdir: Path
) -> bool:
    if not compiler:
        import compileall
        import py_compile

        return bool(
            compileall.compile_dir(
                target,
                quiet=1,
                legacy=legacy,
                optimize=0,
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
                force=True,
                stripdir=str(stripdir),
            )
        )
    import subprocess

    argv = [
        *compiler,
        "-m",
        "compileall",
        "-q",
        "-f",
        "--invalidation-mode",
        "unchecked-hash",
        "-s",
        str(stripdir),
    ]
    if legacy:
        argv.append("-b")
    argv.append(str(target))
    try:
        return subprocess.run(argv, check=False).returncode == 0
    except OSError as exc:
        raise BundleError(
            f"could not run {' '.join(compiler)} to byte-compile the bundle: {exc}"
        ) from exc


def _copy_stdlib(src: Path, dest: Path) -> None:
    def ignore(directory: str, names: list[str]) -> list[str]:
        return [n for n in names if n in _STDLIB_EXCLUDED_DIRS or n.endswith(".gz")]

    shutil.copytree(src, dest, ignore=ignore)


def _copy_pure(src: Path, dest: Path) -> None:
    """Copy an installed site-packages tree minus native payload.

    ``dist-info/direct_url.json`` is dropped entirely: pip writes the install
    source into it (a per-ABI ``file:///`` URL for vendored wheels), which
    both breaks ABI identity by design and would leak local host paths into
    the shipped APK.

    ``bin/`` — pip's console-script launchers — is dropped for the same class
    of reason, and it is worth being explicit because the symptom is
    confusing. Nothing on Android can invoke a console script, and pip
    generates the launchers for the *host*: installing from Windows yields
    Windows ``.exe`` wrappers (``filetype.exe``, ``idna.exe``, …) inside an
    Android APK. They also embed the per-ABI target path, so they differ
    between slices and trip the ABI-identity assertion — which is how this was
    found: ``kivyforge build -p android`` across both ABIs failed with
    "ABI content skew in the pure-Python payload: 'bin/filetype.exe'".
    """

    def ignore(directory: str, names: list[str]) -> list[str]:
        out = [n for n in names if n == "__pycache__" or n.endswith(".so")]
        if Path(directory).name.endswith(".dist-info"):
            out += [n for n in names if n == "direct_url.json"]
        if Path(directory).resolve() == src.resolve():
            # top-level flat .libs/ was hoisted into jniLibs
            out += [n for n in names if n == ".libs"]
            # host-generated console scripts; see the docstring
            out += [n for n in names if n == "bin"]
        return out

    if src.exists():
        shutil.copytree(src, dest, ignore=ignore)
    else:
        dest.mkdir(parents=True)


def _require_module(src: Path, entry_point: str, hint: str) -> None:
    """A dotted entry point must resolve to a module or package in ``app_dir``.

    ``pkg.start`` maps to a nested module; a package entry point is imported
    through its ``__init__.py``. Catching an unresolvable one here beats a black
    screen and an ImportError in logcat.
    """
    rel = "/".join(entry_point.split("."))
    if not (src / f"{rel}.py").is_file() and not (src / rel / "__init__.py").is_file():
        raise BundleError(f"entry point {rel}.py not found in {src.name}/ ({hint}).")


def _copy_app(
    src: Path,
    dest: Path,
    *,
    entry_point: str = "main",
    service_entry_points: dict[str, str],
) -> None:
    if not src.is_dir():
        raise BundleError(
            f"[tool.kivy].app_dir does not exist or is not a directory: {src}"
        )
    _require_module(src, entry_point, "set [tool.kivy].entry_point")
    # A service whose entry point does not exist starts, comes up, and then dies
    # on the import in a separate process — where nothing is watching.
    for name, service_entry in sorted(service_entry_points.items()):
        _require_module(
            src,
            service_entry,
            f"set entry_point for [[tool.kivy.android.services]] {name!r}",
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
        # Mirrors _copy_pure's exclusions: anything not shipped must not be
        # compared either, or the assertion fails on files the bundle drops.
        if "__pycache__" in parts or parts[0] in (".libs", "bin"):
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
