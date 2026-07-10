"""iOS lock stack (``pylock.ios.toml``, spec 02).

The iOS public lock surface: resolve dependencies + native artifacts into a
``Lockfile``, serialize/parse ``pylock.ios.toml``, and compare locks. The
platform-neutral pieces (the ``[[packages]]`` model, PEP 751 helpers, the
drift check, and the neutral pip helpers) live in ``kivyforge.lock``.
"""

from __future__ import annotations

from kivyforge.lock.model import LockedPackage, LockedWheel

from .builder import BuildError, build_lockfile, diff_summary, semantic_equal
from .model import (
    LockedSwiftPackage,
    LockedXcframework,
    Lockfile,
    PythonXcframework,
)
from .reader import LockError, compute_pyproject_sha256, is_in_sync, load, loads
from .resolver import (
    PipResolver,
    ResolvedPackage,
    ResolvedWheel,
    Resolver,
    ResolverError,
    get_resolver,
    slice_tags,
)
from .spm import (
    ResolvedSwiftPackage,
    SpmResolver,
    SpmResolverError,
    XcodeSpmResolver,
    get_spm_resolver,
)
from .writer import dumps
from .xcframework import XcframeworkResolverError, resolve_xcframeworks

__all__ = [
    "BuildError",
    "build_lockfile",
    "diff_summary",
    "semantic_equal",
    "Lockfile",
    "LockedPackage",
    "LockedSwiftPackage",
    "LockedWheel",
    "LockedXcframework",
    "PythonXcframework",
    "LockError",
    "compute_pyproject_sha256",
    "is_in_sync",
    "load",
    "loads",
    "dumps",
    "PipResolver",
    "Resolver",
    "ResolvedPackage",
    "ResolvedWheel",
    "ResolverError",
    "get_resolver",
    "slice_tags",
    "ResolvedSwiftPackage",
    "SpmResolver",
    "SpmResolverError",
    "XcodeSpmResolver",
    "get_spm_resolver",
    "XcframeworkResolverError",
    "resolve_xcframeworks",
]
