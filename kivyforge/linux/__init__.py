"""Linux AppDir bundle backend.

Turns a ``pylock.linux.toml`` + project sources into a self-contained AppDir: a
bundled relocatable CPython (python-build-standalone), the app's resolved
manylinux wheels, the user's code, a generated ``.desktop`` entry + hicolor
icons, and an ``AppRun`` POSIX-shell launcher. The AppDir is both the
``package -f folder`` artifact and the tree the AppImage stage (spec: Step 5)
wraps. Unlike macOS there is no per-slice work and no code signing — Linux loads
``.so`` extensions directly and ships one arch per AppImage.
"""

from __future__ import annotations


class AppDirError(Exception):
    """A Linux AppDir bundling failure surfaced with an actionable message."""
