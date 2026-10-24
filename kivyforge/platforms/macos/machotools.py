"""Thin wrappers over the macOS binary tools the bundler needs.

``lipo -archs`` (read a Mach-O's architectures), ``codesign`` (ad-hoc signing —
the mandatory Apple-Silicon floor), Mach-O detection (so we only ever sign
actual binaries, not text/data files), and a pure reader for the headers and
load commands dyld acts on (file type, dependencies, run paths, install name).
Kept isolated + injectable-friendly so
the higher-level bundler logic stays testable and these are the only lines that
shell out to Apple tools.

There is no ``lipo -create`` wrapper: macOS builds are arm64-only, so nothing
is ever merged into a universal binary.
"""

from __future__ import annotations

import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from kivyforge.report.failures import spawn_failure

from . import AppBundleError

# codesign, when signing with a real (keychain-backed) identity, intermittently
# fails with errSecInternalComponent under rapid successive invocations — a
# long-standing macOS securityd flakiness (not a config problem; ad-hoc signing
# uses no keychain and never hits it). A short retry with backoff reliably
# clears it; see e.g. https://developer.apple.com/forums/thread/700333.
_CODESIGN_TRANSIENT_ERRORS = ("errSecInternalComponent",)
_CODESIGN_MAX_ATTEMPTS = 5
_CODESIGN_RETRY_DELAY_S = 1.0

# Mach-O magic numbers (little/big-endian, 32/64-bit) and the fat/universal
# magics. A file that starts with any of these is a Mach-O we may lipo/sign.
_MACHO_MAGICS = frozenset(
    {
        0xFEEDFACE,  # MH_MAGIC (32-bit)
        0xCEFAEDFE,  # MH_CIGAM
        0xFEEDFACF,  # MH_MAGIC_64
        0xCFFAEDFE,  # MH_CIGAM_64
        0xCAFEBABE,  # FAT_MAGIC (universal)
        0xBEBAFECA,  # FAT_CIGAM
        0xCAFEBABF,  # FAT_MAGIC_64 (universal, 64-bit offsets)
        0xBFBAFECA,  # FAT_CIGAM_64
    }
)

# The two thin-Mach-O magics we can parse a cpu_type out of directly (64-bit
# only — Phase A of macos-x86-removal-and-desktop-stripping.md dropped 32-bit
# and universal support, so kivyforge itself never produces anything else).
_MH_MAGIC_64 = 0xFEEDFACF
_MH_CIGAM_64 = 0xCFFAEDFE

# mach/machine.h cpu_type_t values for the two archs kivyforge cares about.
# CPU_ARCH_ABI64 (0x01000000) OR'd with the 32-bit CPU_TYPE_{ARM,X86}.
CPU_TYPE_ARM64 = 0x0100000C
CPU_TYPE_X86_64 = 0x01000007
_CPU_TYPE_NAMES = {CPU_TYPE_ARM64: "arm64", CPU_TYPE_X86_64: "x86_64"}


class MachoError(Exception):
    pass


class NotMachoError(MachoError):
    """The bytes are not a Mach-O at all (as opposed to a damaged one)."""


def cpu_type_name(cpu_type: int) -> str:
    return _CPU_TYPE_NAMES.get(cpu_type, f"cpu_type 0x{cpu_type:x}")


def read_macho_cpu_type(data: bytes) -> int:
    """Parse the ``cpu_type`` out of a thin 64-bit Mach-O header's raw bytes.

    Pure — no ``lipo`` subprocess — so it works against a real binary's bytes
    *or* a synthetic one built for a hermetic test, the same reason
    ``platforms/android/elf.py`` parses ELF headers directly instead of
    shelling out to ``readelf``.

    The magic tells you the byte order the rest of the header was written in,
    not (directly) which order to read it back in: ``MH_MAGIC_64`` means "this
    file's byte order already matches whatever order you used to read the
    magic", so a big-endian read landing on it implies a big-endian file, and
    landing on ``MH_CIGAM_64`` (the byte-swapped twin) implies the opposite —
    which for every arch kivyforge builds (arm64, x86_64) is little-endian, so
    a real macOS binary always resolves to ``MH_CIGAM_64`` here.

    Raises :class:`MachoError` for anything that is not a thin 64-bit Mach-O —
    32-bit and fat/universal binaries are out of scope; see above.
    """
    if len(data) < 8:
        raise MachoError("too short to be a Mach-O header")
    magic = struct.unpack(">I", data[:4])[0]
    if magic == _MH_MAGIC_64:
        order = ">"
    elif magic == _MH_CIGAM_64:
        order = "<"
    else:
        raise MachoError(
            f"not a thin 64-bit Mach-O (magic 0x{magic:08x}); 32-bit and "
            "fat/universal binaries are not supported"
        )
    return struct.unpack(order + "I", data[4:8])[0]


def is_macho(path: Path) -> bool:
    """True if *path* is a regular file whose first 4 bytes are a Mach-O magic.

    Note ``0xCAFEBABE`` is also the Java class-file magic, but the bundler only
    ever walks a CPython tree + installed wheels, where it unambiguously means a
    universal Mach-O.
    """
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    if len(head) < 4:
        return False
    return struct.unpack(">I", head)[0] in _MACHO_MAGICS


# mach-o/loader.h file types. Only EXECUTE and DYLIB are ever staged by the
# native-binaries channel; the rest are named so a refusal can say which it is.
MH_EXECUTE = 0x2
MH_DYLIB = 0x6
MH_BUNDLE = 0x8
_FILETYPE_NAMES = {
    0x1: "MH_OBJECT",
    MH_EXECUTE: "MH_EXECUTE",
    0x3: "MH_FVMLIB",
    0x4: "MH_CORE",
    0x5: "MH_PRELOAD",
    MH_DYLIB: "MH_DYLIB",
    0x7: "MH_DYLINKER",
    MH_BUNDLE: "MH_BUNDLE",
    0x9: "MH_DYLIB_STUB",
    0xA: "MH_DSYM",
    0xB: "MH_KEXT_BUNDLE",
    0xC: "MH_FILESET",
}

_LC_REQ_DYLD = 0x80000000
_LC_LOAD_DYLIB = 0xC
_LC_ID_DYLIB = 0xD
_LC_LOAD_WEAK_DYLIB = 0x18 | _LC_REQ_DYLD
_LC_RPATH = 0x1C | _LC_REQ_DYLD
_LC_REEXPORT_DYLIB = 0x1F | _LC_REQ_DYLD
_LC_LAZY_LOAD_DYLIB = 0x20
_LC_LOAD_UPWARD_DYLIB = 0x23 | _LC_REQ_DYLD
#: The load commands that make dyld load another image, by the name a message
#: uses for them.
_DEPENDENCY_COMMANDS = {
    _LC_LOAD_DYLIB: "LC_LOAD_DYLIB",
    _LC_LOAD_WEAK_DYLIB: "LC_LOAD_WEAK_DYLIB",
    _LC_REEXPORT_DYLIB: "LC_REEXPORT_DYLIB",
    _LC_LAZY_LOAD_DYLIB: "LC_LAZY_LOAD_DYLIB",
    _LC_LOAD_UPWARD_DYLIB: "LC_LOAD_UPWARD_DYLIB",
}

# Thin headers: (magic as read big-endian) -> (byte order, header size).
_THIN_HEADERS = {
    0xFEEDFACE: (">", 28),
    0xCEFAEDFE: ("<", 28),
    0xFEEDFACF: (">", 32),
    0xCFFAEDFE: ("<", 32),
}
# Fat headers: (magic as read big-endian) -> (byte order, 64-bit offsets).
_FAT_HEADERS = {
    0xCAFEBABE: (">", False),
    0xBEBAFECA: ("<", False),
    0xCAFEBABF: (">", True),
    0xBFBAFECA: ("<", True),
}
# A fat header shares 0xCAFEBABE with a Java class file, whose next word (the
# class-file version) is far larger than any real slice count.
_MAX_FAT_SLICES = 32


@dataclass(frozen=True)
class Dependency:
    """One image a Mach-O asks dyld to load, as its load command spells it."""

    name: str
    command: str

    @property
    def weak(self) -> bool:
        return self.command == "LC_LOAD_WEAK_DYLIB"


@dataclass(frozen=True)
class MachoSlice:
    """What dyld reads from one architecture's Mach-O header."""

    cpu_type: int
    filetype: int
    install_name: str | None
    dependencies: tuple[Dependency, ...]
    rpaths: tuple[str, ...]

    @property
    def arch(self) -> str:
        return cpu_type_name(self.cpu_type)


@dataclass(frozen=True)
class MachoFile:
    """A thin Mach-O (one slice) or a universal one (several)."""

    slices: tuple[MachoSlice, ...]

    @property
    def filetypes(self) -> frozenset[int]:
        return frozenset(s.filetype for s in self.slices)

    def slice_for(self, arch: str) -> MachoSlice | None:
        return next((s for s in self.slices if s.arch == arch), None)


def filetype_name(filetype: int) -> str:
    return _FILETYPE_NAMES.get(filetype, f"file type 0x{filetype:x}")


def parse_macho(data: bytes) -> MachoFile:
    """Parse a thin or universal Mach-O's headers and load commands.

    Pure, like :func:`read_macho_cpu_type`, so the hermetic suite can feed it
    synthetic headers. Every offset and size is checked against the data, so a
    truncated or hostile file raises :class:`MachoError` instead of reading out
    of bounds.
    """
    if len(data) < 8:
        raise NotMachoError("too short to be a Mach-O header")
    magic = struct.unpack(">I", data[:4])[0]
    if magic in _THIN_HEADERS:
        return MachoFile((_parse_thin(data, 0, len(data)),))
    fat = _FAT_HEADERS.get(magic)
    if fat is None:
        raise NotMachoError(f"not a Mach-O file (magic 0x{magic:08x})")
    order, wide = fat
    count = struct.unpack(order + "I", data[4:8])[0]
    if not 0 < count < _MAX_FAT_SLICES:
        raise NotMachoError(f"not a Mach-O file ({count} universal slices)")
    entry = 32 if wide else 20
    if 8 + count * entry > len(data):
        raise MachoError("universal header runs past the end of the file")
    slices = []
    for i in range(count):
        at = 8 + i * entry
        if wide:
            offset, size = struct.unpack(order + "QQ", data[at + 8 : at + 24])
        else:
            offset, size = struct.unpack(order + "II", data[at + 8 : at + 16])
        if offset + size > len(data):
            raise MachoError(f"universal slice {i} runs past the end of the file")
        slices.append(_parse_thin(data, offset, size))
    return MachoFile(tuple(slices))


def read_macho(path: Path) -> MachoFile:
    """:func:`parse_macho` over a file on disk."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise MachoError(f"could not read {path.name}: {exc}") from exc
    return parse_macho(data)


def _parse_thin(data: bytes, start: int, size: int) -> MachoSlice:
    if size < 28:
        raise MachoError("Mach-O slice too short for its header")
    magic = struct.unpack(">I", data[start : start + 4])[0]
    header = _THIN_HEADERS.get(magic)
    if header is None:
        raise MachoError(f"universal slice is not a Mach-O (magic 0x{magic:08x})")
    order, header_size = header
    cpu_type, _subtype, filetype, ncmds, sizeofcmds = struct.unpack(
        order + "5I", data[start + 4 : start + 24]
    )
    end = start + header_size + sizeofcmds
    if header_size + sizeofcmds > size:
        raise MachoError("load commands run past the end of the Mach-O")
    install_name = None
    deps: list[Dependency] = []
    rpaths: list[str] = []
    at = start + header_size
    for _ in range(ncmds):
        if at + 8 > end:
            raise MachoError("load command runs past the end of the header")
        cmd, cmdsize = struct.unpack(order + "II", data[at : at + 8])
        if cmdsize < 8 or at + cmdsize > end:
            raise MachoError(f"load command 0x{cmd:x} has a bad size ({cmdsize})")
        body = data[at : at + cmdsize]
        if cmd in _DEPENDENCY_COMMANDS:
            deps.append(Dependency(_lc_str(body, order), _DEPENDENCY_COMMANDS[cmd]))
        elif cmd == _LC_ID_DYLIB:
            install_name = _lc_str(body, order)
        elif cmd == _LC_RPATH:
            rpaths.append(_lc_str(body, order))
        at += cmdsize
    return MachoSlice(cpu_type, filetype, install_name, tuple(deps), tuple(rpaths))


def _lc_str(body: bytes, order: str) -> str:
    """The NUL-terminated string a load command points at (an ``lc_str``)."""
    if len(body) < 12:
        raise MachoError("load command too short for its string")
    offset = struct.unpack(order + "I", body[8:12])[0]
    if not 12 <= offset < len(body):
        raise MachoError("load command string offset is out of range")
    raw = body[offset:].split(b"\x00", 1)[0]
    return raw.decode("utf-8", errors="replace")


def macho_arches(path: Path) -> tuple[str, ...]:
    """The architectures present in a Mach-O, via ``lipo -archs`` (empty on error)."""
    proc = _run(["lipo", "-archs", str(path)], check=False)
    if proc.returncode != 0:
        return ()
    return tuple(proc.stdout.split())


def codesign_adhoc(path: Path) -> None:
    """Ad-hoc sign a single Mach-O / bundle in place (``codesign --sign -``)."""
    _run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(path)])


def codesign_identity(
    path: Path, identity: str, *, entitlements: Path | None = None
) -> None:
    """Developer ID sign a Mach-O / bundle with Hardened Runtime + timestamp.

    ``--options runtime`` (Hardened Runtime) and a secure ``--timestamp`` are
    both notarization requirements. *entitlements* only applies to the main
    executable, so callers pass it when sealing the ``.app`` (and the launcher),
    not for nested dylib/so binaries.
    """
    cmd = [
        "codesign",
        "--force",
        "--sign",
        identity,
        "--options",
        "runtime",
        "--timestamp",
    ]
    if entitlements is not None:
        cmd += ["--entitlements", str(entitlements)]
    cmd.append(str(path))
    _run_with_retry(cmd)


def codesign_verify(path: Path) -> bool:
    """True if *path* has a valid signature (``codesign --verify``)."""
    return _run(["codesign", "--verify", str(path)], check=False).returncode == 0


def _run_with_retry(cmd: list[str]) -> None:
    """Run *cmd* (a codesign invocation), retrying transient keychain flakiness.

    Only retries errors matching ``_CODESIGN_TRANSIENT_ERRORS``; anything else
    (a genuinely missing/expired identity, a bad entitlements plist, ...)
    raises immediately.
    """
    for attempt in range(1, _CODESIGN_MAX_ATTEMPTS + 1):
        try:
            _run(cmd)
            return
        except AppBundleError as exc:
            transient = any(m in str(exc) for m in _CODESIGN_TRANSIENT_ERRORS)
            if not transient or attempt == _CODESIGN_MAX_ATTEMPTS:
                raise
            time.sleep(_CODESIGN_RETRY_DELAY_S * attempt)


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
    except OSError as exc:
        reason = (
            "not found" if isinstance(exc, FileNotFoundError) else f"unusable ({exc})"
        )
        raise AppBundleError(
            f"required macOS tool {cmd[0]!r} {reason}.\n"
            "  Install the Xcode command-line tools: xcode-select --install",
            **spawn_failure(cmd[0], exc),
        ) from exc
    if check and proc.returncode != 0:
        raise AppBundleError(
            f"{cmd[0]} failed ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc
