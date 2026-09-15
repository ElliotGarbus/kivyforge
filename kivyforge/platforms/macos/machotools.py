"""Thin wrappers over the macOS binary tools the bundler needs.

``lipo -archs`` (read a Mach-O's architectures), ``codesign`` (ad-hoc signing —
the mandatory Apple-Silicon floor), and Mach-O detection (so we only ever sign
actual binaries, not text/data files). Kept isolated + injectable-friendly so
the higher-level bundler logic stays testable and these are the only lines that
shell out to Apple tools.

There is no ``lipo -create`` wrapper: macOS builds are arm64-only, so nothing
is ever merged into a universal binary.
"""

from __future__ import annotations

import struct
import subprocess
import time
from pathlib import Path

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
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AppBundleError(
            f"required macOS tool {cmd[0]!r} not found.\n"
            "  Install the Xcode command-line tools: xcode-select --install"
        ) from exc
    if check and proc.returncode != 0:
        raise AppBundleError(
            f"{cmd[0]} failed ({proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc
