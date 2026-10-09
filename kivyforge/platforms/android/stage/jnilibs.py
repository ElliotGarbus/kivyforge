"""Populate ``jniLibs/<abi>/`` (android/04 §"Native libraries and the .so load model").

Two kinds of ``.so``, found two different ways at runtime:

- **Shared libraries** resolved by soname (``System.loadLibrary`` /
  ``DT_NEEDED``): ``libpython3.X.so``, the runtime's ``lib*_python.so``, a
  package's own ``lib*.so``, and everything in a wheel's libraries directory --
  kivy-mobile-wheels' shared
  ``.libs/`` (the SDL family) or auditwheel's ``<dist>.libs/`` (what
  cibuildwheel's default Android repair grafts, e.g.
  ``numpy.libs/libc++_shared-d523468d.so``). Copied verbatim, names
  unchanged: the extensions' ``DT_NEEDED`` already names them that way.
- **Extension modules** imported by dotted name: flattened to
  ``libpy.<dotted>.so`` (the platform's native-lib extraction requires the
  ``lib*.so`` shape — proven on-device, loadmodel findings §confirmed #1) and
  recorded in the ``ext_manifest.json`` the bootstrap finder consumes.

A libraries directory is **flat-only**: a nested subdirectory is a malformed
wheel and fails the build (android/03/04 — the wheel tag is the sole ABI
truth). A package can also carry its own libraries (``ffmpeg/.libs/``,
``blosc2/lib/``); those are copied verbatim too, see ``is_package_library``.
The duplicate policy is the iOS rule adapted: identical content dedupes
silently; same basename with different bytes aborts naming both providers.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from kivyforge.artifacts.verify import sha256_file

from ..elf import ElfError, machine_name, read_elf

EXT_MANIFEST_NAME = "ext_manifest.json"

# Suffix pattern of CPython extension modules: everything from the first "."
# after the module path is the ABI suffix (".cpython-314-....so" or just ".so").
_SO_SUFFIX = ".so"

_LIBS_SUFFIX = ".libs"

# A shared object by name: ".so", or versioned (".so.5", ".so.1.2").
_SHARED_OBJECT = re.compile(r"\.so(\.\d+)*$")

# The suffixes that mark a .so as an extension module (a bare ".so" may be one too).
_EXTENSION_SUFFIX = re.compile(r"\.(cpython-\d+-[^.]+|abi3)\.so$")


def is_wheel_libs_dir(name: str) -> bool:
    """Whether a top-level site-packages entry is a libraries directory.

    ``.libs`` and ``<dist>.libs``. A name ending in ``.libs`` is never an
    importable package, so the suffix cannot capture one.
    """
    return name.endswith(_LIBS_SUFFIX)


class JniLibsError(Exception):
    pass


class UnloadableLibrary(JniLibsError):
    """A wheel's ``.so`` the device would not load; ``source`` is the file."""

    def __init__(self, message: str, *, source: Path) -> None:
        super().__init__(message)
        self.source = source


class NativeLibWrongArch(UnloadableLibrary):
    """A library built for another architecture than the ABI it is staged for."""


class ExtensionWrongSuffix(UnloadableLibrary):
    """An extension module named so that CPython on Android would not import it."""


@dataclass
class JniLibsStager:
    """Accumulates ``.so`` files for one ABI, enforcing the duplicate policy.

    ``provider`` strings name where a file came from (e.g. ``"runtime"``,
    ``"wheel kivy"``) so a conflict diagnostic can name both sides.

    ``machine`` is the ELF ``e_machine`` this ABI needs. An ELF built for any
    other fails the build here, not at load time on the device: the wheel's
    tag is what routed it to this ABI, and its contents disagree.

    ``extension_suffixes`` are the suffixes CPython on Android imports an
    extension module under. The bootstrap finder imports by dotted name and
    never looks at the suffix, so without this check a module standard CPython
    would not find (a build host's ``.cpython-314-x86_64-linux-gnu.so``, or
    another Python's ``.cpython-313-...``) would load anyway.
    """

    dest: Path
    machine: int | None = None
    extension_suffixes: tuple[str, ...] = ()
    # basename -> (sha256, provider)
    _seen: dict[str, tuple[str, str]] = field(default_factory=dict)
    # dotted module -> flattened filename
    _manifest: dict[str, str] = field(default_factory=dict)
    _strip_unsafe: set[str] = field(default_factory=set)

    def add_shared_library(self, source: Path, *, provider: str) -> None:
        """Copy a soname-resolved library verbatim (name unchanged)."""
        self._add(source, source.name, provider=provider)

    def add_extension_module(self, source: Path, *, dotted: str, provider: str) -> None:
        """Flatten one extension module and record it in the finder manifest."""
        suffix = source.name[len(source.name.split(".", 1)[0]) :]
        if self.extension_suffixes and suffix not in self.extension_suffixes:
            raise ExtensionWrongSuffix(
                f"{provider} supplies the extension module {source.name}, "
                f"which CPython on Android would not import: for "
                f"{self.dest.name} it imports only "
                f"{', '.join(self.extension_suffixes)}. A wheel built with "
                f"another platform's or another Python's suffix is broken, "
                f"even though kivyforge's loader would load it.",
                source=source,
            )
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

    def strip_unsafe(self) -> list[str]:
        """Staged names AGP's strip would corrupt (android/04 §Stripping)."""
        return sorted(self._strip_unsafe)

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
        try:
            info = read_elf(source)
        except (ElfError, OSError):
            info = None
        if info is not None and self.machine is not None:
            if info.machine != self.machine:
                raise NativeLibWrongArch(
                    f"{provider} supplies {source.name}, which is built for "
                    f"{machine_name(info.machine)}, but it is being staged for "
                    f"{self.dest.name}, which needs "
                    f"{machine_name(self.machine)}. The wheel's platform tag "
                    f"and its contents disagree, so the library would fail to "
                    f"load on the device.",
                    source=source,
                )
        self.dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, self.dest / basename)
        self._seen[basename] = (digest, provider)
        if info is not None and info.strip_unsafe:
            self._strip_unsafe.add(basename)


def dotted_module_name(so_path: Path, site_packages_root: Path) -> str:
    """``site-packages/jnius/jnius.cpython-314-….so`` -> ``jnius.jnius``."""
    rel = so_path.relative_to(site_packages_root)
    stem = rel.name.split(".", 1)[0]
    parts = [*rel.parts[:-1], stem]
    return ".".join(parts)


def stage_wheel_libs_dir(
    stager: JniLibsStager, libs_dir: Path, *, wheel_name: str
) -> int:
    """Ingest one flat libraries directory (``.libs/`` or ``<dist>.libs/``).

    Returns the count. Flat-only: any subdirectory is a malformed wheel
    (android/03). The ABI is the wheel tag's business — the caller already
    routed this stager to the right ABI.

    Android packages only ``lib*.so`` files as native libraries, and these
    cannot be renamed: other libraries link against them by file name.
    """
    count = 0
    for entry in sorted(libs_dir.iterdir()):
        if entry.is_dir():
            raise JniLibsError(
                f"wheel {wheel_name!r} has a nested {libs_dir.name}/ "
                f"subdirectory ({entry.name!r}); {libs_dir.name}/ must be "
                f"flat — the wheel platform tag is the sole source of truth "
                f"for the ABI (android/03 §flat only)."
            )
        name = entry.name
        if name.startswith("lib") and name.endswith(_SO_SUFFIX):
            stager.add_shared_library(entry, provider=f"wheel {wheel_name}")
            count += 1
        elif _SHARED_OBJECT.search(name):
            raise JniLibsError(
                f"wheel {wheel_name!r} ships {libs_dir.name}/{name}, which "
                f"Android cannot package: native libraries must be named "
                f"lib*.so, and kivyforge cannot rename this one because "
                f"other libraries link against it by that name."
            )
    return count


def stage_wheel_libs_dirs(stager: JniLibsStager, site_packages: Path) -> int:
    """Ingest every top-level libraries directory. Returns the count."""
    count = 0
    for entry in sorted(site_packages.iterdir()):
        if entry.is_dir() and is_wheel_libs_dir(entry.name):
            # pip merges every wheel's .libs/ into one, so it has no single owner.
            owner = entry.name.removesuffix(_LIBS_SUFFIX) or "site-packages"
            count += stage_wheel_libs_dir(stager, entry, wheel_name=owner)
    return count


def is_package_library(so: Path, site_packages: Path) -> bool:
    """Whether a ``.so`` inside a package is a shared library, not an extension.

    ``ffmpeg/.libs/libavcodec.so``, ``blosc2/lib/libtcc.so``: named ``lib*.so``
    with no extension-module suffix, in a directory that is not a regular
    package. Such a file is linked by name or opened by path, never imported.
    """
    rel = so.relative_to(site_packages)
    return (
        len(rel.parts) >= 2
        and so.name.startswith("lib")
        and so.name.endswith(_SO_SUFFIX)
        and not _EXTENSION_SUFFIX.search(so.name)
        and not (so.parent / "__init__.py").exists()
    )


def stage_package_libraries(stager: JniLibsStager, site_packages: Path) -> int:
    """Copy each package's own shared libraries verbatim. Returns the count.

    They go into ``jniLibs`` under their own names, like a top-level ``.libs/``:
    that is where the linker resolves ``DT_NEEDED`` and where the package finds
    them when it searches the directory of its extension modules.
    """
    count = 0
    for so in sorted(site_packages.rglob(f"*{_SO_SUFFIX}")):
        top = so.relative_to(site_packages).parts[0]
        if is_wheel_libs_dir(top) or not is_package_library(so, site_packages):
            continue
        stager.add_shared_library(so, provider=f"package {top}")
        count += 1
    return count


def stage_site_packages_extensions(
    stager: JniLibsStager, site_packages: Path, *, wheel_name: str
) -> int:
    """Flatten every extension ``.so`` under an installed wheel's tree."""
    count = 0
    for so in sorted(site_packages.rglob(f"*{_SO_SUFFIX}")):
        if is_wheel_libs_dir(so.relative_to(site_packages).parts[0]):
            continue  # handled by stage_wheel_libs_dirs
        if is_package_library(so, site_packages):
            continue  # handled by stage_package_libraries
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
