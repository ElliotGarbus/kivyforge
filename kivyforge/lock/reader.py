"""Shared lockfile drift detection + the ``LockError`` type.

Every backend records the pyproject SHA-256 in its lockfile and compares it on
build to detect drift; those neutral helpers live here so iOS, macOS, and Linux
readers all reuse them. The iOS ``pylock.ios.toml`` parser lives in
``kivyforge.platforms.ios.lock.reader``; the wheel+runtime parser lives in
``kivyforge.lock.wheelruntime.serialize``.
"""

from __future__ import annotations

import hashlib
from typing import Protocol


class LockError(Exception):
    """A malformed or unreadable lockfile."""


class _HasPyprojectSha(Protocol):
    pyproject_sha256: str


def compute_pyproject_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_in_sync(lock: _HasPyprojectSha, pyproject_text: str) -> bool:
    """True if the lock's recorded pyproject hash matches the current pyproject."""
    return lock.pyproject_sha256 == compute_pyproject_sha256(pyproject_text)
