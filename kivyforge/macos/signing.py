"""Ad-hoc code signing of the assembled ``.app`` (macos-spec).

Ad-hoc signing (``codesign --sign -``) is the mandatory Apple-Silicon floor: the
kernel refuses to run unsigned arm64 Mach-O. Signing is **inside-out** — every
nested Mach-O (the runtime's ``python3``/``libpython``/``.dylib`` and the wheels'
``.so`` extensions) is signed first, deepest first, then the ``.app`` bundle last
— because signing the bundle seals a hash of its already-signed contents.

Developer ID signing + notarization is a later workstream (see macos-spec); this
phase ships only the integrity floor.
"""

from __future__ import annotations

from pathlib import Path

from .machotools import codesign_adhoc, is_macho


def sign_bundle_adhoc(app: Path) -> int:
    """Ad-hoc sign every Mach-O in *app*, then *app* itself; return the count.

    Returns the number of ``codesign`` invocations (nested binaries + the bundle),
    which callers use for a one-line progress message.
    """
    machos = [p for p in app.rglob("*") if is_macho(p)]
    # Deepest paths first so containers are signed after their contents.
    machos.sort(key=lambda p: len(p.parts), reverse=True)
    for macho in machos:
        codesign_adhoc(macho)
    codesign_adhoc(app)
    return len(machos) + 1
