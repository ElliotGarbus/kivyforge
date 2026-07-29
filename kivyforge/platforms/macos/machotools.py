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
