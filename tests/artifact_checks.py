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

The Linux half works on a **directory**, not an archive: a type-2 AppImage is an
ELF with a squashfs filesystem appended, so ``zipfile`` cannot read it and there
is no stdlib squashfs reader. The driver extracts it (``--appimage-extract``,
which needs no FUSE) and points these at the resulting tree; the AppDir is also
directly buildable via ``kivyforge package -f folder``. Checks that can only be
made on the single file — that it is an AppImage at all, and for which arch —
live in :func:`linux_appimage_file_problems` so the container itself is covered
rather than assumed.

Paths *inside* an artifact are always rendered with ``as_posix()``, never by
interpolating a ``Path``. The artifact is a Linux or Apple bundle whatever host
is reading it, so ``usr/app/main.py`` is the only correct spelling — inspecting
an extracted AppDir from Windows must not start reporting ``usr\\app\\main.py``.
"""

from __future__ import annotations

import os
import plistlib
import posixpath
import re
import shlex
import struct
import zipfile
from pathlib import Path

from kivyforge.platforms.android.elf import EM_AARCH64, EM_X86_64, machine_name
from kivyforge.platforms.linux.elftools import (
    ARCH_ELF,
    ELF_MAGIC,
    ElfError,
    describe,
    elf_machine,
    is_elf,
)
from kivyforge.platforms.macos.machotools import (
    CPU_TYPE_ARM64,
    CPU_TYPE_X86_64,
    MachoError,
    cpu_type_name,
    read_macho_cpu_type,
)

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


# --- macOS ------------------------------------------------------------------
#
# The macOS ``.app`` is a real directory tree, not a zip, so these walk the
# filesystem directly rather than a ``zipfile.ZipFile``. Payload-stripping scope
# is narrower than Android's: per the settled decision in
# docs/design/dev/macos-x86-removal-and-desktop-stripping.md ("Strip scope: app
# + site-packages only. stdlib is not stripped."), only ``Contents/Resources/app``
# (the developer's own sources) and ``Contents/Resources/lib`` (third-party
# deps — the macos-spec analogue of "site-packages") are ever byte-compiled;
# ``Contents/Resources/python`` (the embedded CPython framework's own stdlib,
# which ships pip) is deliberately left as source and must not be checked as
# if it were part of the same policy.

MACOS_ARCH_MACHINES = {"arm64": CPU_TYPE_ARM64, "x86_64": CPU_TYPE_X86_64}

_MACOS_STRIP_SCOPE = ("Contents/Resources/app", "Contents/Resources/lib")


def macos_app_problems(
    app: Path,
    *,
    arch: str,
    stripped: bool,
    expected_magic: bytes,
    bundle_id: str | None = None,
    executable: str | None = None,
) -> list[str]:
    """Every way *app* fails to be the artifact the build promised.

    ``arch`` is the Mach-O arch name (``"arm64"``, the only one macOS builds
    produce post-Phase-A), ``stripped`` whether ``strip_source`` applied to
    this build, and ``expected_magic`` the first four bytes a ``.pyc`` the
    bundle's own shipped runtime can import must carry (see Android's
    ``shipped_python_tags`` for the reasoning; on macOS the equivalent is
    running the bundle's own ``Contents/Resources/python/bin/python3``).

    ``bundle_id``/``executable``, if given, are checked against
    ``Info.plist``; omitted, only the plist's internal shape (present, parses,
    required keys non-empty) is checked. Exact match against the project's
    full resolved config is left for a follow-up, same as Android's own open
    "merged manifest matches config" item in test-matrix.md §5.1.
    """
    if arch not in MACOS_ARCH_MACHINES:
        return [f"unknown arch {arch!r}; expected one of {sorted(MACOS_ARCH_MACHINES)}"]

    problems = _macos_required_entry_problems(app)
    if problems:
        # Nothing else below can be trusted to mean anything on a bundle
        # that is missing its basic shape.
        return problems

    problems += _macos_plist_problems(app, bundle_id=bundle_id, executable=executable)
    problems += _macos_arch_problems(app, arch=arch)
    problems += _macos_payload_problems(app, stripped=stripped)
    if stripped:
        problems += _macos_pyc_magic_problems(app, expected_magic=expected_magic)
    return problems


def _macos_required_entry_problems(app: Path) -> list[str]:
    """The handful of things without which this is not a launchable ``.app``."""
    problems = []
    if not (app / "Contents" / "Info.plist").is_file():
        problems.append("Contents/Info.plist is missing")
    macos_dir = app / "Contents" / "MacOS"
    if not macos_dir.is_dir() or not any(
        p.is_file() for p in macos_dir.iterdir() if not p.name.startswith(".")
    ):
        problems.append("Contents/MacOS/ has no executable")
    if not (app / "Contents" / "Resources" / "python").is_dir():
        problems.append("Contents/Resources/python (the embedded runtime) is missing")
    if not (app / "Contents" / "Resources" / "app").is_dir():
        problems.append("Contents/Resources/app (the app payload) is missing")
    return problems


def _macos_plist_problems(
    app: Path, *, bundle_id: str | None, executable: str | None
) -> list[str]:
    plist_path = app / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the check
        return [f"Contents/Info.plist does not parse: {exc}"]

    problems = []
    required_keys = (
        "CFBundleIdentifier",
        "CFBundleExecutable",
        "CFBundleShortVersionString",
        "CFBundleVersion",
    )
    for key in required_keys:
        if not plist.get(key):
            problems.append(f"Info.plist is missing (or has an empty) {key}")

    if bundle_id is not None and plist.get("CFBundleIdentifier") != bundle_id:
        problems.append(
            f"Info.plist CFBundleIdentifier is {plist.get('CFBundleIdentifier')!r}, "
            f"expected {bundle_id!r}"
        )
    if executable is not None and plist.get("CFBundleExecutable") != executable:
        problems.append(
            f"Info.plist CFBundleExecutable is {plist.get('CFBundleExecutable')!r}, "
            f"expected {executable!r}"
        )
    elif executable is None and "CFBundleExecutable" in plist:
        exe = plist["CFBundleExecutable"]
        if not (app / "Contents" / "MacOS" / exe).is_file():
            problems.append(
                f"Info.plist CFBundleExecutable {exe!r} does not name a file "
                "in Contents/MacOS/"
            )
    return problems


def _macos_arch_problems(app: Path, *, arch: str) -> list[str]:
    """Every Mach-O under the bundle must be *arch*, and only *arch*.

    Walks ``Contents/MacOS`` (the launcher) and ``Contents/Resources`` (the
    embedded runtime + every staged wheel's compiled extensions) — a
    host-arch binary leaking into a cross-build is exactly the item-1-shaped
    bug this exists to catch, on the one platform where it would otherwise
    surface only as a Gatekeeper/Rosetta failure on a real Mac.
    """
    expected = MACOS_ARCH_MACHINES[arch]
    problems: list[str] = []
    for path in sorted(app.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            head = path.read_bytes()[:8]
        except OSError:
            continue
        try:
            cpu_type = read_macho_cpu_type(head)
        except MachoError:
            continue  # not a Mach-O (or a 32-bit/fat one we don't parse) — skip
        if cpu_type != expected:
            rel = path.relative_to(app).as_posix()
            problems.append(
                f"{rel} is {cpu_type_name(cpu_type)} but this build is {arch} — "
                "a host or cross-arch binary leaked into the bundle"
            )
    return problems


def _macos_payload_problems(app: Path, *, stripped: bool) -> list[str]:
    """Whether the app + third-party payload is source or bytecode.

    Scoped to ``Contents/Resources/{app,lib}`` only — see the module-level
    note on why the embedded stdlib is excluded by design, not by omission.
    """
    problems: list[str] = []
    for scope in _MACOS_STRIP_SCOPE:
        base = app / scope
        if not base.is_dir():
            continue
        sources = sorted(p for p in base.rglob("*.py"))
        compiled = sorted(p for p in base.rglob("*.pyc"))
        cached = sorted(p for p in base.rglob("__pycache__") if p.is_dir())

        if stripped:
            if sources:
                rels = [p.relative_to(app).as_posix() for p in sources[:3]]
                problems.append(
                    f"strip_source was applied but {len(sources)} .py file(s) "
                    f"remain under {scope}, e.g. {rels}"
                )
            if not compiled:
                problems.append(
                    f"strip_source was applied but {scope} contains no .pyc at "
                    "all — the build degraded to shipping source"
                )
            if cached:
                rels = [p.relative_to(app).as_posix() for p in cached[:3]]
                problems.append(
                    f"{scope} has {len(cached)} __pycache__ dir(s), e.g. "
                    f"{rels} — sourceless imports need .pyc in the legacy "
                    "location, not beside a source file that is no longer there"
                )
        elif scope == "Contents/Resources/app" and not sources and not compiled:
            problems.append(
                f"{scope} has neither .py nor .pyc — the app has no entry point"
            )
    return problems


def _macos_pyc_magic_problems(app: Path, *, expected_magic: bytes) -> list[str]:
    """Every ``.pyc`` under the stripped scope must carry the shipped magic.

    Mirrors Android's ``_pyc_magic_problems`` / roadmap item 1's bug, adapted
    to a directory tree: read straight from disk rather than a zip member.
    """
    problems: list[str] = []
    for scope in _MACOS_STRIP_SCOPE:
        base = app / scope
        if not base.is_dir():
            continue
        seen: dict[bytes, list[Path]] = {}
        for pyc in sorted(base.rglob("*.pyc")):
            magic = pyc.read_bytes()[:4]
            seen.setdefault(magic, []).append(pyc)
        for magic, members in sorted(seen.items()):
            if magic != expected_magic:
                rels = [p.relative_to(app).as_posix() for p in members[:3]]
                problems.append(
                    f"{len(members)} .pyc file(s) under {scope} carry magic "
                    f"{_magic_int(magic)} but the bundle's own runtime imports "
                    f"{_magic_int(expected_magic)}, e.g. {rels} — these were "
                    "written by an interpreter of a different CPython build "
                    "and cannot be imported"
                )
    return problems


# --------------------------------------------------------------------------
# Linux: AppDir / AppImage
# --------------------------------------------------------------------------

# The Python payload, and *only* it. ``bundle.build_appdir`` byte-compiles
# exactly ``usr/app`` and ``usr/lib``, so the interpreter's own stdlib under
# ``usr/python`` keeps its source in a stripped build — 1037 ``.py`` and six
# ``__pycache__`` in a real dice-roller release. That is correct (strip_source
# is about the app's code, and the stdlib is public CPython), but a check that
# swept the whole tree would report every one of them as a fault.
PAYLOAD_DIRS = ("usr/app", "usr/lib")
RUNTIME_DIR = "usr/python"

# ``libpython3.13.so``, ``libpython3.13.so.1.0`` — but not ``libpython3.so``,
# which carries no minor and is the ABI-stable stub.
_LIBPYTHON_SO = re.compile(r"^libpython(\d+\.\d+)\.so(\.\d+\.\d+)?$")

# Offset 8 of a type-2 AppImage: ELF e_ident padding repurposed as the format
# marker (``AI`` + version 2). Type 1 is ``AI\x01`` and ISO9660-based.
APPIMAGE_TYPE2_MAGIC = b"AI\x02"


def shipped_python_tags_appdir(appdir: Path) -> list[str]:
    """The CPython minor(s) whose runtime *appdir* ships, e.g. ``["3.13"]``.

    The AppDir analog of :func:`shipped_python_tags`, and it exists for the same
    reason: the expected ``.pyc`` magic has to be anchored to the runtime that
    will do the importing, read out of the artifact. Taking the version from
    config instead would let a build be checked against a runtime it does not
    ship and pass.
    """
    lib = appdir / RUNTIME_DIR / "lib"
    if not lib.is_dir():
        return []
    found = {
        m.group(1)
        for m in map(_LIBPYTHON_SO.match, (p.name for p in lib.iterdir()))
        if m
    }
    return sorted(found)


def linux_appdir_problems(
    appdir: Path,
    *,
    arch: str,
    stripped: bool,
    expected_magic: bytes,
) -> list[str]:
    """Every way the AppDir at *appdir* fails to be the artifact the build promised.

    ``arch`` is a kivyforge arch name (``x86_64``), ``stripped`` whether
    ``strip_source`` applied to this build, and ``expected_magic`` the first four
    bytes a ``.pyc`` the shipped runtime can import must carry — see
    :func:`shipped_python_tags_appdir` for choosing it.
    """
    if arch not in ARCH_ELF:
        return [f"unknown arch {arch!r}; expected one of {sorted(ARCH_ELF)}"]
    if not appdir.is_dir():
        return [f"{appdir} is not a directory"]

    problems = _linux_required_problems(appdir)
    problems += _apprun_target_problems(appdir)
    problems += _linux_payload_problems(appdir, stripped=stripped)
    problems += _linux_elf_problems(appdir, arch=arch)
    if stripped:
        problems += _linux_pyc_magic_problems(appdir, expected_magic=expected_magic)
    return problems


def _payload_files(appdir: Path) -> list[Path]:
    files: list[Path] = []
    for rel in PAYLOAD_DIRS:
        root = appdir / rel
        if root.is_dir():
            files += [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    return files


def _linux_required_problems(appdir: Path) -> list[str]:
    """The pieces without which it is not an AppDir, or cannot start."""
    problems = []

    apprun = appdir / "AppRun"
    if not apprun.is_file():
        problems.append("AppRun is missing; AppImage requires it at the AppDir root")
    elif os.name == "posix" and not apprun.stat().st_mode & 0o111:
        # Only asked where it can be answered. NTFS records no execute bit, so
        # ``st_mode`` is 0o100666 for every file on Windows however it was
        # written -- the honest answer there is "unknown", and reporting "not
        # executable" would be a false positive on every AppDir inspected from
        # a Windows host, synthetic or real. The assertion still runs on every
        # host that can actually build an AppImage.
        problems.append("AppRun is not executable; appimagetool will refuse the AppDir")

    if not list(appdir.glob("*.desktop")):
        problems.append("no .desktop entry at the AppDir root")

    runtimes = sorted(shipped_python_tags_appdir(appdir))
    if not runtimes:
        problems.append(
            f"no libpython3.X.so under {RUNTIME_DIR}/lib — the AppDir ships no runtime"
        )
    elif len(runtimes) > 1:
        problems.append(
            f"AppDir ships {len(runtimes)} CPython runtimes ({runtimes}); AppRun "
            "starts exactly one and the rest are dead weight"
        )

    if not (appdir / "usr" / "app").is_dir():
        problems.append("usr/app is missing from the AppDir")
    return problems


def _apprun_target_problems(appdir: Path) -> list[str]:
    """Whatever ``AppRun`` promises to execute has to exist in the AppDir.

    This is the Linux shape of roadmap item 1, and it is a real shipped bug
    rather than a hypothetical: ``AppRun`` is rendered from a template that
    hardcodes ``usr/app/<entry>.py`` and is never told whether the payload was
    stripped, so ``kivyforge package`` (which applies ``strip_source`` by
    default) emits an AppImage whose first act is to open a file the same build
    deleted. It exits 2 before Python starts.

    The target is parsed out of the artifact rather than rebuilt from config, so
    this asserts the promise the AppDir actually makes. Both launcher shapes are
    understood — a script path, and ``-m <module>`` — so the check stays correct
    once the launcher is fixed rather than starting to fail in the other
    direction.
    """
    apprun = appdir / "AppRun"
    if not apprun.is_file():
        return []  # already reported

    exec_line = next(
        (
            line
            for line in apprun.read_text("utf-8", errors="replace").splitlines()
            if line.strip().startswith("exec ")
        ),
        None,
    )
    if exec_line is None:
        return ["AppRun contains no exec line; nothing starts the interpreter"]

    try:
        argv = shlex.split(exec_line)
    except ValueError as exc:
        return [f"AppRun exec line does not parse as shell: {exc}"]

    if "-m" in argv:
        module = argv[argv.index("-m") + 1] if argv.index("-m") + 1 < len(argv) else ""
        if not module:
            return ["AppRun passes -m with no module name"]
        rel = Path("usr/app") / Path(*module.split("."))
        if (
            not (appdir / rel.with_suffix(".py")).is_file()
            and not (appdir / rel.with_suffix(".pyc")).is_file()
        ):
            return [
                f"AppRun runs `-m {module}`, but neither {rel.as_posix()}.py nor "
                f"{rel.as_posix()}.pyc exists in the payload"
            ]
        return []

    # Positional form: the second "$HERE/..." token is the script, the first
    # being the interpreter.
    here = [a for a in argv if a.startswith("$HERE/")]
    if len(here) < 2:
        return [f"AppRun exec line names no script to run: {exec_line.strip()!r}"]
    rel = here[1].removeprefix("$HERE/")
    if not (appdir / rel).is_file():
        sibling = ""
        if rel.endswith(".py") and (appdir / (rel + "c")).is_file():
            sibling = (
                f" — {rel}c is there, so the payload was byte-compiled and "
                "stripped while AppRun kept pointing at the source"
            )
        return [
            f"AppRun execs {rel}, which does not exist in the AppDir{sibling}; "
            "the app cannot start"
        ]
    return []


def _linux_payload_problems(appdir: Path, *, stripped: bool) -> list[str]:
    """Whether the Python payload is source or bytecode, and nothing in between.

    Same reasoning as the Android version — a ``.pyc`` beside its ``.py`` is
    silently ignored, so a half-stripped payload looks fine while shipping every
    source file the setting existed to remove.
    """
    payload = _payload_files(appdir)
    if not payload:
        return ["usr/app and usr/lib are both empty — the AppDir has no payload"]

    def rel(paths):
        return [p.relative_to(appdir).as_posix() for p in paths[:3]]

    sources = [p for p in payload if p.suffix == ".py"]
    compiled = [p for p in payload if p.suffix == ".pyc"]
    problems = []

    if stripped:
        if sources:
            problems.append(
                f"strip_source was applied but {len(sources)} .py file(s) remain "
                f"in the payload, e.g. {rel(sources)}"
            )
        if not compiled:
            problems.append(
                "strip_source was applied but the payload contains no .pyc at "
                "all — the build degraded to shipping source"
            )
        cached = [p for p in payload if "__pycache__" in p.parts]
        if cached:
            problems.append(
                f"payload has {len(cached)} __pycache__ entrie(s), e.g. "
                f"{rel(cached)} — sourceless imports need .pyc in the legacy "
                "location, not beside a source file that is no longer there"
            )
    elif not sources:
        problems.append(
            "strip_source was not applied but the payload contains no .py at all"
        )

    return problems


def _linux_pyc_magic_problems(appdir: Path, *, expected_magic: bytes) -> list[str]:
    """Every payload ``.pyc`` must carry the magic the shipped runtime imports.

    Roadmap item 1's actual bug. Note the Linux build reaches it down a
    different road than Android: a Linux x86_64 build on a Linux host is
    *native*, so ``select_compiler()`` hands the payload to the **staged**
    interpreter and never calls ``find_interpreter()``. The magic here is
    therefore the AppDir's own runtime's, which is why the driver reads it from
    that runtime rather than from the interpreter running pytest.
    """
    seen: dict[bytes, list[Path]] = {}
    for path in _payload_files(appdir):
        if path.suffix != ".pyc":
            continue
        with path.open("rb") as fh:
            seen.setdefault(fh.read(4), []).append(path)

    problems = []
    for magic, members in sorted(seen.items()):
        if magic != expected_magic:
            problems.append(
                f"{len(members)} .pyc file(s) carry magic {_magic_int(magic)} but "
                f"the shipped runtime imports {_magic_int(expected_magic)}, e.g. "
                f"{[p.name for p in members[:3]]} — these were written by an "
                "interpreter of a different CPython build and cannot be imported"
            )
    return problems


def _linux_elf_problems(appdir: Path, *, arch: str) -> list[str]:
    """Every ELF in the AppDir must be the target's class + machine.

    Deliberately the **whole tree**, which is the coverage that does not exist
    today: ``doctor.check_linux_native_binaries`` looks only under ``usr/bin``
    and SKIPs entirely unless ``[tool.kivy.linux.native.binaries]`` is declared,
    so the staged CPython, its ``lib-dynload`` extension modules, and every
    compiled wheel in site-packages are currently unchecked. A foreign-arch
    object there fails at ``dlopen`` with a message naming the file but not the
    reason.

    Unlike Android there is no hoisting rule to enforce: the Linux loader is
    happy to open a ``.so`` from anywhere the rpath reaches, so a shared object
    living in site-packages is correct rather than stranded.
    """
    expected = ARCH_ELF[arch]
    problems = []
    for path in sorted(appdir.rglob("*")):
        if not is_elf(path):
            continue
        try:
            found = elf_machine(path)
        except ElfError as exc:
            problems.append(f"{path.relative_to(appdir).as_posix()}: {exc}")
            continue
        if found != expected:
            problems.append(
                f"{path.relative_to(appdir).as_posix()} is {describe(*found)} but "
                f"{arch} requires {describe(*expected)}"
            )
    return problems


def linux_appimage_file_problems(appimage: Path, *, arch: str) -> list[str]:
    """The checks that can only be made on the ``.AppImage`` file itself.

    Extracting and inspecting the tree says nothing about the container
    ``appimagetool`` wrapped it in, and that tool had never run in this project
    before this artifact existed. A type-2 AppImage is an ELF whose e_ident
    padding carries ``AI\\x02`` at offset 8, with a squashfs filesystem appended
    — so this reads the header and nothing more.
    """
    if arch not in ARCH_ELF:
        return [f"unknown arch {arch!r}; expected one of {sorted(ARCH_ELF)}"]
    if not appimage.is_file():
        return [f"{appimage} is not a file"]

    with appimage.open("rb") as fh:
        header = fh.read(12)
    if header[:4] != ELF_MAGIC:
        return [f"{appimage.name} is not an ELF file; AppImage runtimes are ELF"]

    problems = []
    if header[8:11] != APPIMAGE_TYPE2_MAGIC:
        problems.append(
            f"{appimage.name} carries {header[8:11]!r} at offset 8, not the "
            f"type-2 AppImage marker {APPIMAGE_TYPE2_MAGIC!r} — appimagetool "
            "did not produce this, or produced a type-1 image"
        )
    try:
        found = elf_machine(appimage)
    except ElfError as exc:
        return [*problems, str(exc)]
    if found != ARCH_ELF[arch]:
        problems.append(
            f"{appimage.name} runtime is {describe(*found)} but {arch} requires "
            f"{describe(*ARCH_ELF[arch])} — the wrong type2-runtime was fetched"
        )
    return problems
