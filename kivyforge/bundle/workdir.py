"""The temporary tree a desktop bundle is assembled in before it is swapped in.

``tempfile.mkdtemp`` always creates its directory ``0700``, which is right for
a scratch directory and wrong for a product: the macOS ``.app`` and the Linux
AppDir are that directory, renamed. Left alone, the bundle opens only for the
user who built it, and ``cp -R`` carries the mode into a DMG or ``/Applications``.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import tempfile
from pathlib import Path


def make_work_dir(parent: Path, prefix: str) -> Path:
    """A fresh directory under *parent* with the mode ``mkdir`` would give it."""
    work = Path(tempfile.mkdtemp(dir=parent, prefix=prefix))
    work.chmod(0o777 & ~_current_umask())
    return work


def swap_in(work: Path, dest: Path) -> None:
    """Move the finished tree *work* to *dest*, keeping the previous one on failure.

    Deleting the previous tree first is not failure-safe: an ``rmtree`` that
    fails partway (a file held open, a folder it may not write) leaves *dest*
    half deleted. So the previous tree is renamed aside whole, *work* is renamed
    into place, and only then is the previous tree deleted. Both renames stay in
    one folder, so each is atomic. If *work* cannot take the name, the previous
    tree is renamed back. On any failure *work* is removed and the original
    error propagates unchanged.
    """
    previous: Path | None = None
    try:
        if os.path.lexists(dest):
            aside = dest.with_name(f".{dest.name}.old-{secrets.token_hex(4)}")
            dest.replace(aside)
            previous = aside
        work.replace(dest)
    except BaseException:
        if previous is not None:
            # A second refusal in a row leaves the previous tree beside *dest*
            # for manual recovery rather than masking the first error.
            with contextlib.suppress(OSError):
                previous.replace(dest)
        _discard(work)
        raise
    if previous is not None:
        # The new tree is in place; a leftover of the old one is clutter, not a
        # failed build.
        _discard(previous)


def _discard(path: Path) -> None:
    """Remove *path* on the way out, never raising over the outcome it follows."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _current_umask() -> int:
    # The only way to read the umask is to set it; restore it immediately.
    mask = os.umask(0o022)
    os.umask(mask)
    return mask
