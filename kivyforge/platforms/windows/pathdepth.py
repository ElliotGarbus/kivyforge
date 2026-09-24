"""How deep a onedir bundle goes, and how long a folder it can live in.

Windows caps a path at ``MAX_PATH`` (260, so 259 characters plus the NUL)
unless a process is *both* manifest-declared long-path-aware and running on a
machine with ``LongPathsEnabled`` set. The bundled ``python.exe`` declares
itself long-path-aware, but ``LongPathsEnabled`` is **off** on a default
Windows install, so on most users' machines every file in the bundle has to
fit in 259 characters *including the folder the user put it in*.

So a bundle's deepest relative path decides how long that folder may be. The
2026-09-24 measurement (test-matrix.md §5.6): a Kivy onedir bundle's deepest
entry is 105 characters, all of it pip's ``__pycache__`` inside the shipped
runtime, which leaves 153 characters for the folder.

Adding ``longPathAware`` to the launcher would not move this limit. Windows
refuses to *start* an executable whose own path exceeds ``MAX_PATH`` even
with long paths enabled (``WinError 206``, measured the same day), and within
that limit the file I/O is done by ``python.exe``, which already opts in.
"""

from __future__ import annotations

import os
from pathlib import Path

#: ``MAX_PATH`` less the terminating NUL: the longest usable path.
MAX_PATH_CHARS = 259

#: Warn when a bundle leaves less room than this for its folder. Comfortably
#: covers a per-user install such as
#: ``C:\\Users\\<name>\\AppData\\Local\\Programs\\<App>-1.0.0-amd64`` (~85).
MIN_FOLDER_HEADROOM = 100


def deepest_relative_path(root: Path) -> str:
    """The longest path under *root*, relative to it, Windows-spelled.

    Directories count as well as files, which only matters for an empty one:
    a non-empty directory is always shorter than something inside it. Ties go
    to the first in sorted order so the answer is stable. ``""`` for an empty
    tree.
    """
    deepest = ""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            rel = rel.replace("/", "\\")
            if len(rel) > len(deepest):
                deepest = rel
    return deepest


def folder_headroom(deepest: str) -> int:
    """The longest folder path the bundle can sit in, with long paths off.

    ``len(folder) + 1 (the separator) + len(deepest)`` must fit in
    :data:`MAX_PATH_CHARS`.
    """
    return MAX_PATH_CHARS - 1 - len(deepest)
