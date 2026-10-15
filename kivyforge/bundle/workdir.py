"""Putting a finished output in place without losing the previous one.

``make_work_dir`` and ``swap_in`` serve the desktop bundles, which are assembled
in a temporary tree and renamed into place. ``tempfile.mkdtemp`` always creates
its directory ``0700``, which is right for a scratch directory and wrong for a
product: the macOS ``.app`` and the Linux AppDir are that directory, renamed.
Left alone, the bundle opens only for the user who built it, and ``cp -R``
carries the mode into a DMG or ``/Applications``.

``copy_in`` serves the single-file mobile packages copied into ``dist/``. It
never renames the freshly written file, because Android packages on Windows,
where the antivirus scanner can hold a new file open (see
:mod:`kivyforge.platforms.windows.fsswap`).
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import tempfile
import time
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


def copy_in(src: Path, dest: Path, *, timeout: float = 30.0) -> None:
    """Copy the file *src* to *dest*, keeping a previous *dest* until it succeeds.

    The copy is written straight to *dest*: a freshly written file cannot be
    reliably renamed on Windows, so it never is. A previous file at *dest* is
    renamed aside first (it was written earlier, so the rename is safe, though a
    scanner may still hold one written seconds ago, hence the retry) and
    deleted only once the copy is complete. If the copy fails or is
    interrupted, the partial file is removed and the previous one renamed back.
    The original error propagates unchanged; the caller reports it.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    previous: Path | None = None
    if os.path.lexists(dest):
        aside = dest.with_name(f".{dest.name}.old-{secrets.token_hex(4)}")
        rename_with_retry(dest, aside, timeout=timeout)
        previous = aside
    try:
        shutil.copy2(src, dest)
    except BaseException:
        _discard(dest)
        if previous is not None:
            # As in swap_in: a refused restore leaves the previous file beside
            # *dest* for recovery rather than masking the first error.
            with contextlib.suppress(OSError):
                previous.replace(dest)
        raise
    if previous is not None:
        _discard(previous)


def rename_with_retry(
    src: Path, dst: Path, *, timeout: float = 30.0, initial_delay: float = 0.1
) -> None:
    """``os.replace(src, dst)`` retrying transient Windows sharing locks.

    Retries until *timeout* seconds elapse, backing off from *initial_delay* up
    to a 1s cap. Re-raises the last ``PermissionError`` if the lock never clears.
    """
    deadline = time.monotonic() + timeout
    delay = initial_delay
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 1.0)


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
