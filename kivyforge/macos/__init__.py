"""macOS ``.app`` bundle backend.

Turns a ``pylock.macos.toml`` + project sources into a self-contained,
double-clickable ``.app``: a bundled relocatable CPython (python-build-standalone
today), the app's resolved wheels, the user's code, an ``Info.plist``, a
launcher, and ad-hoc code signing. This is the macOS analog of the iOS
``kivyforge.project`` + ``kivyforge.xcode`` stack, but far simpler — macOS loads
``.dylib``/``.so`` extensions directly, so there is no per-slice framework
conversion.
"""

from __future__ import annotations


class AppBundleError(Exception):
    """A macOS ``.app`` bundling failure surfaced with an actionable message."""
