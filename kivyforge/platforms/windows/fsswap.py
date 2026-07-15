"""Windows-safe in-place tree publishing (windows-spec).

Windows cannot reliably rename a freshly-written directory: the antivirus
real-time scanner holds new executables/DLLs open (without share-delete), and a
cold *first-sight* scan (cloud lookup) can exceed any sane retry window — the
whole extracted CPython + wheels tree is thousands of new files. So we never
rename a freshly written tree. Instead callers write it **directly into its
final location** and only ever rename the *previous* (long-since-scanned) tree
aside, which renames instantly, restoring it if the write fails so a broken
operation never destroys a working artifact.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


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


def reserve_previous(target: Path, *, timeout: float = 30.0) -> Path | None:
    """Move an existing *target* aside so a fresh one can be written in place.

    Returns the trash path (to restore on failure / delete on success), or
    ``None`` when there was no previous tree. Renaming the old tree is fast — it
    was scanned long ago — but we still retry briefly in case a just-built tree's
    files are momentarily held.
    """
    if not target.exists():
        return None
    trash = target.with_name(f".{target.name}.old-{os.getpid()}")
    rename_with_retry(target, trash, timeout=timeout)
    return trash


def restore_previous(trash: Path | None, target: Path) -> None:
    """Move a reserved previous tree back into place after a failed write."""
    if trash is None:
        return
    shutil.rmtree(target, ignore_errors=True)
    try:
        rename_with_retry(trash, target)
    except OSError:
        # Best-effort restore: leave the trash for manual recovery rather than
        # masking the original failure with a rename error.
        pass


def discard_reserved(trash: Path | None) -> None:
    """Delete a reserved previous tree after a successful write (no-op if None)."""
    if trash is not None:
        shutil.rmtree(trash, ignore_errors=True)
