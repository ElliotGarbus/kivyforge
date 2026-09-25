"""The temporary tree a desktop bundle is assembled in before it is swapped in.

``tempfile.mkdtemp`` always creates its directory ``0700``, which is right for
a scratch directory and wrong for a product: the macOS ``.app`` and the Linux
AppDir are that directory, renamed. Left alone, the bundle opens only for the
user who built it, and ``cp -R`` carries the mode into a DMG or ``/Applications``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def make_work_dir(parent: Path, prefix: str) -> Path:
    """A fresh directory under *parent* with the mode ``mkdir`` would give it."""
    work = Path(tempfile.mkdtemp(dir=parent, prefix=prefix))
    work.chmod(0o777 & ~_current_umask())
    return work


def _current_umask() -> int:
    # The only way to read the umask is to set it; restore it immediately.
    mask = os.umask(0o022)
    os.umask(mask)
    return mask
