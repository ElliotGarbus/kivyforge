"""Post-build assertions on a produced artifact — tier T3 in ``test-matrix.md``.

Everything here is a **file read on a finished artifact**: no device, no human,
no toolchain beyond the build that already happened. That is the whole appeal.
Roadmap item 1 shipped a `strip_source` that had never once run on a mobile
target, and CI was building the affected artifact the entire time and throwing
it away unexamined — a single pass over the zip would have caught it on day one.

The functions return **lists of problem strings rather than asserting**, so one
run reports every fault instead of stopping at the first, and so they can be
unit-tested against synthetic artifacts without a build. Same shape as
``scripts/check_sdl_glue_sync.py``.

ELF headers are parsed from the 20 bytes read straight out of the zip rather
than via ``platforms/android/elf.py``'s :func:`read_elf`, which takes a
``Path``: extracting 120 shared objects to disk to look at six bytes of each is
not worth it. The *constants* are imported from that module even so, so the
machine codes asserted here cannot drift from the ones the build uses.
"""

from __future__ import annotations

import posixpath
import re
import struct
import zipfile
from pathlib import Path

from kivyforge.platforms.android.elf import EM_AARCH64, EM_X86_64, machine_name

BUNDLE_ROOT = "assets/_python_bundle/"

_LIBPYTHON = re.compile(r"^lib/[^/]+/libpython(\d+\.\d+)\.so$")

# Android's dashed ABI directory names (the wheel-tag spelling with underscores
# is what pyproject uses; the generator maps between them) to the ELF e_machine
# every shared object under lib/<abi>/ must report. 64-bit only, permanently:
# the python.org Android runtime ships no 32-bit build.
ABI_MACHINES = {"arm64-v8a": EM_AARCH64, "x86_64": EM_X86_64}

ELFCLASS64 = 2


def shipped_python_tags(apk: Path) -> list[str]:
    """The CPython minor(s) whose runtime *apk* actually ships, e.g. ``["3.14"]``.

    Read out of the artifact rather than passed in, so the expected ``.pyc``
    magic is anchored to the runtime that will do the importing. Passing the
    version in would let a caller assert an APK against the wrong runtime and
    get a green result, which is the shape of bug these checks exist to catch.
    """
    with zipfile.ZipFile(apk) as zf:
        found = {m.group(1) for m in map(_LIBPYTHON.match, zf.namelist()) if m}
    return sorted(found)


def android_apk_problems(
    apk: Path,
    *,
    abi: str,
    stripped: bool,
    expected_magic: bytes,
) -> list[str]:
    """Every way *apk* fails to be the artifact the build promised.

    ``abi`` is the dashed Android name (``arm64-v8a``), ``stripped`` whether
    ``strip_source`` applied to this build, and ``expected_magic`` the first four
    bytes a ``.pyc`` the shipped runtime can import must carry — see
    :func:`shipped_python_tags` for choosing it.
    """
    if abi not in ABI_MACHINES:
        return [f"unknown ABI {abi!r}; expected one of {sorted(ABI_MACHINES)}"]

    with zipfile.ZipFile(apk) as zf:
        names = zf.namelist()
        problems = _required_entry_problems(names, abi=abi)
        problems += _payload_problems(names, stripped=stripped)
        problems += _native_lib_problems(zf, names, abi=abi)
        if stripped:
            problems += _pyc_magic_problems(zf, names, expected_magic=expected_magic)
        return problems


def _required_entry_problems(names: list[str], *, abi: str) -> list[str]:
    """The three things without which the app cannot start at all."""
    problems = []
    if f"lib/{abi}/libmain.so" not in names:
        problems.append(f"lib/{abi}/libmain.so is missing from the APK")

    runtimes = sorted(n for n in names if _LIBPYTHON.match(n))
    if not runtimes:
        problems.append(
            f"no libpython3.X.so under lib/{abi}/ — the APK ships no runtime"
        )
    elif len(runtimes) > 1:
        problems.append(
            f"APK ships {len(runtimes)} CPython runtimes ({runtimes}); the "
            "bootstrap loads exactly one and the rest are dead weight"
        )

    if not any(n.startswith(BUNDLE_ROOT) for n in names):
        problems.append(f"{BUNDLE_ROOT} is missing from the APK")
    return problems


def _payload_problems(names: list[str], *, stripped: bool) -> list[str]:
    """Whether the Python payload is source or bytecode, and nothing in between.

    The mixed case is the interesting one. A ``.pyc`` sitting next to its
    ``.py`` is silently ignored by the import system, so a half-stripped bundle
    looks fine on device while shipping every source file the setting was meant
    to remove.
    """
    bundle = [n for n in names if n.startswith(BUNDLE_ROOT) and not n.endswith("/")]
    if not bundle:
        return []  # _required_entry_problems already reported the empty bundle

    sources = [n for n in bundle if n.endswith(".py")]
    compiled = [n for n in bundle if n.endswith(".pyc")]
    problems = []

    if stripped:
        if sources:
            problems.append(
                f"strip_source was applied but {len(sources)} .py file(s) "
                f"remain in the payload, e.g. {sources[:3]}"
            )
        if not compiled:
            problems.append(
                "strip_source was applied but the payload contains no .pyc at "
                "all — the build degraded to shipping source"
            )
        # PEP 3147 puts a .pyc in __pycache__ *beside* its source; sourceless
        # imports need it in the legacy location instead, so a __pycache__ dir
        # here means the stripping step moved nothing.
        cached = [n for n in bundle if "__pycache__" in n]
        if cached:
            problems.append(
                f"payload has {len(cached)} __pycache__ entrie(s), e.g. "
                f"{cached[:3]} — sourceless imports need .pyc in the legacy "
                "location, not beside a source file that is no longer there"
            )
        if f"{BUNDLE_ROOT}app/main.pyc" not in names:
            problems.append(
                f"{BUNDLE_ROOT}app/main.pyc is missing; the entry point must be "
                "compiled in the legacy sourceless layout"
            )
    else:
        if f"{BUNDLE_ROOT}app/main.py" not in names:
            problems.append(
                f"{BUNDLE_ROOT}app/main.py is missing from an unstripped build"
            )

    # Extension modules are hoisted to lib/<abi>/ because Android's loader will
    # not open a .so from inside the unpacked assets tree. One left behind is a
    # staging bug that surfaces as an ImportError on device.
    stranded = [n for n in bundle if n.endswith(".so")]
    if stranded:
        problems.append(
            f"{len(stranded)} shared object(s) left inside the payload instead "
            f"of hoisted to lib/, e.g. {stranded[:3]}"
        )
    return problems


def _pyc_magic_problems(
    zf: zipfile.ZipFile, names: list[str], *, expected_magic: bytes
) -> list[str]:
    """Every ``.pyc`` must carry the magic the shipped runtime imports.

    This is roadmap item 1's actual bug. CPython bumps the magic number through
    the alpha/beta cycle and freezes it at the first release candidate, so a
    pre-release of the *right* minor writes bytecode a release runtime refuses —
    while answering the same "3.14" to any version check. When the source has
    been stripped there is nothing to fall back to, so the app dies on import.
    """
    pycs = [n for n in names if n.startswith(BUNDLE_ROOT) and n.endswith(".pyc")]
    seen: dict[bytes, list[str]] = {}
    for name in pycs:
        with zf.open(name) as handle:
            magic = handle.read(4)
        seen.setdefault(magic, []).append(name)

    problems = []
    for magic, members in sorted(seen.items()):
        if magic != expected_magic:
            problems.append(
                f"{len(members)} .pyc file(s) carry magic "
                f"{_magic_int(magic)} but the shipped runtime imports "
                f"{_magic_int(expected_magic)}, e.g. "
                f"{[posixpath.basename(m) for m in members[:3]]} — these were "
                "written by an interpreter of a different CPython build and "
                "cannot be imported"
            )
    return problems


def _magic_int(magic: bytes) -> int:
    """The human-readable half of a ``.pyc`` header (the trailing ``\\r\\n``)."""
    return struct.unpack("<H", magic[:2])[0] if len(magic) >= 2 else -1


def _native_lib_problems(
    zf: zipfile.ZipFile, names: list[str], *, abi: str
) -> list[str]:
    """Every shared object under ``lib/`` must be 64-bit ELF for exactly *abi*.

    The failure this exists for is a cross-build that picked up a host-arch
    binary — it installs, and then dlopen fails on device with a message that
    names the file but not the reason. A stray *second* ABI directory is the
    related bug: it doubles the APK and ships code the manifest never claimed.
    """
    expected = ABI_MACHINES[abi]
    libs = [n for n in names if n.startswith("lib/") and n.endswith(".so")]
    problems = []

    strays = sorted({n.split("/")[1] for n in libs} - {abi})
    if strays:
        problems.append(
            f"APK carries shared objects for unrequested ABI(s) {strays}; "
            f"only {abi} was built"
        )

    for name in libs:
        if name.split("/")[1] != abi:
            continue  # already reported as a stray ABI
        with zf.open(name) as handle:
            header = handle.read(20)
        if header[:4] != b"\x7fELF":
            problems.append(f"{name} is not an ELF file")
            continue
        if header[4] != ELFCLASS64:
            problems.append(f"{name} is 32-bit ELF; every Android ABI is 64-bit")
        machine = struct.unpack("<H", header[18:20])[0]
        if machine != expected:
            problems.append(
                f"{name} is {machine_name(machine)} but {abi} requires "
                f"{machine_name(expected)} — a host binary leaked into a "
                "cross-build"
            )
    return problems
