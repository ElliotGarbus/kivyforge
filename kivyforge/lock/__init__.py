"""kivyforge shared lock core (spec 02).

Platform-neutral lock building blocks shared by every backend: the PEP 751
``[[packages]]`` model, the drift check, the neutral pip helpers, and the
generic wheel+runtime engine (``kivyforge.lock.wheelruntime``). The iOS lock
surface lives in ``kivyforge.platforms.ios.lock``; the macOS/Linux surfaces in
``kivyforge.platforms.<os>.lock``.
"""

from __future__ import annotations

from .model import (
    LOCK_VERSION,
    LockedPackage,
    LockedWheel,
    PackageDep,
    canonical_name,
)
from .reader import LockError, compute_pyproject_sha256, is_in_sync
from .resolver import (
    MIN_PIP_VERSION,
    abi_tags,
    pip_python_version,
    pip_version,
    version_str,
)

__all__ = [
    "LOCK_VERSION",
    "LockedPackage",
    "LockedWheel",
    "PackageDep",
    "canonical_name",
    "LockError",
    "compute_pyproject_sha256",
    "is_in_sync",
    "MIN_PIP_VERSION",
    "abi_tags",
    "pip_python_version",
    "pip_version",
    "version_str",
]
