"""kivyforge shared lock core (spec 02).

Platform-neutral lock building blocks shared by every backend: the PEP 751
``[[packages]]`` model, the drift check, the neutral pip helpers, and the
generic wheel+runtime engine (``kivyforge.lock.wheelruntime``). The iOS lock
surface lives in ``kivyforge.platforms.ios.lock``; the macOS/Linux surfaces in
``kivyforge.platforms.<os>.lock``.
"""

from __future__ import annotations

from .inputs import LOCK_INPUTS, is_in_sync, lock_inputs_sha256
from .model import (
    LOCK_VERSION,
    LockedPackage,
    LockedWheel,
    PackageDep,
    canonical_name,
)
from .reader import LockError
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
    "LOCK_INPUTS",
    "LockError",
    "is_in_sync",
    "lock_inputs_sha256",
    "MIN_PIP_VERSION",
    "abi_tags",
    "pip_python_version",
    "pip_version",
    "version_str",
]
