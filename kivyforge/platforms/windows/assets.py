"""Access + integrity-check the vendored Windows binaries (windows-spec).

The onedir bundler consumes two prebuilt binaries shipped inside the package:
the launcher (``launcher-amd64.exe``) and the resource-patch tool
(``rcedit-x64.exe``). This module locates them and verifies each against the
SHA-256 pinned in ``vendor/SHA256SUMS`` before use, so a corrupted or
tampered-with vendored asset fails loudly instead of ending up in a shipped app.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import WindowsBundleError

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
MANIFEST = VENDOR_DIR / "SHA256SUMS"
LAUNCHER_NAME = "launcher-amd64.exe"
RCEDIT_NAME = "rcedit-x64.exe"


def read_manifest() -> dict[str, str]:
    """Parse ``vendor/SHA256SUMS`` into ``{filename: sha256}``."""
    if not MANIFEST.is_file():
        raise WindowsBundleError(
            f"vendored-binary manifest missing: {MANIFEST}. The kivyforge "
            "install is incomplete."
        )
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if digest and name:
            entries[name.strip()] = digest.strip()
    return entries


def _verified_asset(name: str, *, human: str) -> Path:
    path = VENDOR_DIR / name
    if not path.is_file():
        raise WindowsBundleError(
            f"the vendored {human} ({name}) is missing from the kivyforge "
            f"install at {path}.\n"
            "  It is built/fetched in CI; a source checkout may need "
            "`python -m kivyforge.platforms.windows.launcher.build_launcher build` "
            "(launcher) or "
            "`python -m kivyforge.platforms.windows.vendor.fetch_rcedit` (rcedit)."
        )
    expected = read_manifest().get(name)
    if not expected:
        raise WindowsBundleError(
            f"the vendored {human} ({name}) has no pinned SHA-256 in {MANIFEST}."
        )
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise WindowsBundleError(
            f"the vendored {human} ({name}) failed its integrity check:\n"
            f"  expected sha256 {expected}\n  actual   sha256 {actual}\n"
            "  Refuse to ship a tampered/corrupted binary; re-vendor it."
        )
    return path


def vendored_launcher() -> Path:
    """The verified prebuilt launcher (``launcher-amd64.exe``)."""
    # arm64: take a target-arch argument and select launcher-<arch>.exe (rcedit
    # stays x64 — it is emulated and only edits resources). See arm64-windows.md §5.
    return _verified_asset(LAUNCHER_NAME, human="launcher")


def vendored_rcedit() -> Path:
    """The verified prebuilt resource editor (``rcedit-x64.exe``)."""
    return _verified_asset(RCEDIT_NAME, human="rcedit resource editor")
