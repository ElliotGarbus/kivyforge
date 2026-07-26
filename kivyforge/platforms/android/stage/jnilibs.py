"""Populate ``jniLibs/<abi>/`` (android/04 §"Native libraries and the .so load model").

Two kinds of ``.so``, found two different ways at runtime:

- **Shared libraries** resolved by soname (``System.loadLibrary`` /
  ``DT_NEEDED``): ``libpython3.X.so``, the runtime's ``lib*_python.so``, the
  SDL family from a wheel's ``.libs/``. Copied verbatim, names unchanged.
- **Extension modules** imported by dotted name: flattened to
  ``libpy.<dotted>.so`` (the platform's native-lib extraction requires the
  ``lib*.so`` shape — proven on-device, loadmodel findings §confirmed #1) and
  recorded in the ``ext_manifest.json`` the bootstrap finder consumes.

Wheel ``.libs/`` is **flat-only**: a nested subdirectory is a malformed wheel
and fails the build (android/03/04 — the wheel tag is the sole ABI truth).
The duplicate policy is the iOS rule adapted: identical content dedupes
silently; same basename with different bytes aborts naming both providers.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from kivyforge.artifacts.verify import sha256_file

EXT_MANIFEST_NAME = "ext_manifest.json"

# Suffix pattern of CPython extension modules: everything from the first "."
# after the module path is the ABI suffix (".cpython-314-....so" or just ".so").
_SO_SUFFIX = ".so"


class JniLibsError(Exception):
    pass


@dataclass
class JniLibsStager:
    """Accumulates ``.so`` files for one ABI, enforcing the duplicate policy.

    ``provider`` strings name where a file came from (e.g. ``"runtime"``,
    ``"wheel kivy"``) so a conflict diagnostic can name both sides.
    """

    dest: Path
    # basename -> (sha256, provider)
    _seen: dict[str, tuple[str, str]] = field(default_factory=dict)
    # dotted module -> flattened filename
    _manifest: dict[str, str] = field(default_factory=dict)

    def add_shared_library(self, source: Path, *, provider: str) -> None:
        """Copy a soname-resolved library verbatim (name unchanged)."""
        self._add(source, source.name, provider=provider)

    def add_extension_module(self, source: Path, *, dotted: str, provider: str) -> None:
        """Flatten one extension module and record it in the finder manifest."""
        flattened = f"libpy.{dotted}.so"
        existing = self._manifest.get(dotted)
        if existing is not None and existing != flattened:
            raise JniLibsError(
                f"extension module {dotted!r} maps to both {existing!r} and "
                f"{flattened!r}"
            )
        self._add(source, flattened, provider=provider)
        self._manifest[dotted] = flattened

    def manifest(self) -> dict[str, str]:
        return dict(sorted(self._manifest.items()))

    def write_manifest(self, bootstrap_dir: Path) -> Path:
        bootstrap_dir.mkdir(parents=True, exist_ok=True)
        out = bootstrap_dir / EXT_MANIFEST_NAME
        out.write_text(
            json.dumps(self.manifest(), indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return out

    def _add(self, source: Path, basename: str, *, provider: str) -> None:
        digest = sha256_file(source)
        prior = self._seen.get(basename)
        if prior is not None:
            prior_sha, prior_provider = prior
            if prior_sha == digest:
                return  # identical -> silent dedupe
            raise JniLibsError(
                f"conflicting native library {basename!r} for {self.dest.name}: "
                f"{prior_provider} and {provider} supply different contents "
                f"(sha256 {prior_sha[:12]}… vs {digest[:12]}…).\n"
                f"  kivyforge never picks a winner — a version-mismatched .so "
                f"can link and then crash at runtime (android/04 §duplicate "
                f".so policy)."
            )
        self.dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, self.dest / basename)
        self._seen[basename] = (digest, provider)


def dotted_module_name(so_path: Path, site_packages_root: Path) -> str:
    """``site-packages/jnius/jnius.cpython-314-….so`` -> ``jnius.jnius``."""
    rel = so_path.relative_to(site_packages_root)
    stem = rel.name.split(".", 1)[0]
    parts = [*rel.parts[:-1], stem]
    return ".".join(parts)


def stage_wheel_libs_dir(
    stager: JniLibsStager, libs_dir: Path, *, wheel_name: str
) -> int:
    """Ingest one wheel's flat ``.libs/`` (SDL family etc.). Returns the count.

    Flat-only: any subdirectory is a malformed wheel (android/03). The ABI is
    the wheel tag's business — the caller already routed this stager to the
    right ABI.
    """
    count = 0
    for entry in sorted(libs_dir.iterdir()):
        if entry.is_dir():
            raise JniLibsError(
                f"wheel {wheel_name!r} has a nested .libs/ subdirectory "
                f"({entry.name!r}); .libs/ must be flat — the wheel platform "
                f"tag is the sole source of truth for the ABI (android/03 "
                f"§flat only)."
            )
        if entry.suffix == _SO_SUFFIX:
            stager.add_shared_library(entry, provider=f"wheel {wheel_name}")
            count += 1
    return count


def stage_site_packages_extensions(
    stager: JniLibsStager, site_packages: Path, *, wheel_name: str
) -> int:
    """Flatten every extension ``.so`` under an installed wheel's tree."""
    count = 0
    for so in sorted(site_packages.rglob(f"*{_SO_SUFFIX}")):
        if ".libs" in so.relative_to(site_packages).parts[:1]:
            continue  # the flat .libs/ dir is handled by stage_wheel_libs_dir
        stager.add_extension_module(
            so,
            dotted=dotted_module_name(so, site_packages),
            provider=f"wheel {wheel_name}",
        )
        count += 1
    return count


def stage_runtime_libs(
    stager: JniLibsStager, prefix_lib: Path, *, python_stem: str
) -> tuple[int, int]:
    """Stage the extracted runtime's ``prefix/lib`` for one ABI.

    Returns ``(shared_count, extension_count)``. Follows the python.org
    app-integration split, extended for multi-ABI (android/03 channel 2):

    - ``lib<python_stem>.so`` + ``lib*_python.so`` -> verbatim (soname libs).
      The runtime's plain ``lib{ssl,crypto,sqlite3}.so`` / ``engines-3`` /
      ``ossl-modules`` are NOT shipped — the ``_python``-soname copies are the
      ones the extensions link against (proven on-device; loadmodel findings
      §runtime-package facts).
    - ``lib/<python_stem>/lib-dynload/*.so`` -> flattened extension modules
      (all top-level stdlib names).
    """
    shared = 0
    libpython = prefix_lib / f"lib{python_stem}.so"
    if not libpython.is_file():
        raise JniLibsError(
            f"runtime prefix has no lib{python_stem}.so under {prefix_lib}"
        )
    stager.add_shared_library(libpython, provider="runtime")
    shared += 1
    for candidate in sorted(prefix_lib.glob("lib*_python.so")):
        stager.add_shared_library(candidate, provider="runtime")
        shared += 1

    extensions = 0
    dynload = prefix_lib / python_stem / "lib-dynload"
    if not dynload.is_dir():
        raise JniLibsError(f"runtime prefix has no lib-dynload directory at {dynload}")
    for so in sorted(dynload.glob(f"*{_SO_SUFFIX}")):
        dotted = so.name.split(".", 1)[0]
        stager.add_extension_module(so, dotted=dotted, provider="runtime")
        extensions += 1
    return shared, extensions
