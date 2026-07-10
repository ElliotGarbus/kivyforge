"""Code signing of the assembled ``.app`` (macos-spec).

Two tiers, both **inside-out** — every nested Mach-O (the runtime's
``python3``/``libpython``/``.dylib`` and the wheels' ``.so`` extensions) is
signed first, deepest first, then the ``.app`` bundle last — because signing
the bundle seals a hash of its already-signed contents:

- **Ad-hoc** (``codesign --sign -``): the mandatory Apple-Silicon floor (the
  kernel refuses to run unsigned arm64 Mach-O). Integrity only, no trust.
- **Developer ID** (``--sign <identity> --options runtime --timestamp``): the
  distribution tier. Hardened Runtime + a secure timestamp are notarization
  requirements; the main executable additionally carries entitlements that a
  hardened Python bundle needs (see ``DEFAULT_HARDENED_ENTITLEMENTS``).
"""

from __future__ import annotations

import plistlib
import tempfile
from pathlib import Path

from .machotools import codesign_adhoc, codesign_identity, is_macho

# Hardened-Runtime entitlements a bundled CPython app needs by default:
# - allow-unsigned-executable-memory: ctypes/cffi trampolines allocate W+X
#   pages, which the Hardened Runtime otherwise forbids.
# - disable-library-validation: the app loads wheel `.so`/`.dylib` binaries
#   signed by other teams (or re-signed here); library validation would
#   require every image to share the app's team ID.
# Users may override either (or add more) via [tool.kivy.macos.entitlements].
DEFAULT_HARDENED_ENTITLEMENTS: dict[str, object] = {
    "com.apple.security.cs.allow-unsigned-executable-memory": True,
    "com.apple.security.cs.disable-library-validation": True,
}


def sign_bundle_adhoc(app: Path) -> int:
    """Ad-hoc sign every Mach-O in *app*, then *app* itself; return the count.

    Returns the number of ``codesign`` invocations (nested binaries + the bundle),
    which callers use for a one-line progress message.
    """
    machos = _machos_inside_out(app)
    for macho in machos:
        codesign_adhoc(macho)
    codesign_adhoc(app)
    return len(machos) + 1


def sign_bundle_developer_id(
    app: Path,
    identity: str,
    *,
    extra_entitlements: dict[str, object] | None = None,
) -> int:
    """Developer ID deep-sign *app* for distribution; return the codesign count.

    Nested Mach-O binaries get Hardened Runtime + timestamp; the ``.app`` seal
    (which signs the main executable) additionally carries the merged
    entitlements (defaults + ``[tool.kivy.macos.entitlements]``, user wins).
    """
    entitlements = {**DEFAULT_HARDENED_ENTITLEMENTS, **(extra_entitlements or {})}
    machos = _machos_inside_out(app)
    with tempfile.TemporaryDirectory(prefix="kivyforge-ent-") as tmp:
        ent_file = Path(tmp) / "entitlements.plist"
        with ent_file.open("wb") as fh:
            plistlib.dump(entitlements, fh)
        for macho in machos:
            codesign_identity(macho, identity)
        codesign_identity(app, identity, entitlements=ent_file)
    return len(machos) + 1


def _machos_inside_out(app: Path) -> list[Path]:
    """Every Mach-O under *app*, deepest paths first (containers sign last)."""
    machos = [p for p in app.rglob("*") if is_macho(p)]
    machos.sort(key=lambda p: len(p.parts), reverse=True)
    return machos
