"""Shared, platform-neutral ``[[packages]]`` model (PEP 751).

The per-slice wheel + package dataclasses here are consumed by every backend
(iOS, macOS, Linux) and the generic wheel+runtime engine. Platform-specific
lockfile models (the iOS ``Lockfile`` + xcframework/swift-package entries, the
macOS/Linux ``WheelRuntimeLock``) build on top of these.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LOCK_VERSION = "1.0"


@dataclass(frozen=True)
class LockedWheel:
    """One ``[[packages.wheels]]`` entry (a single platform slice)."""

    name: str  # wheel filename; platform tag is parsed back out of this
    sha256: str
    url: str | None = None
    path: str | None = None
    upload_time: str | None = None
    size: int | None = None

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.path):
            raise ValueError(f"wheel {self.name!r} must have exactly one of url/path")

    @property
    def platform_tag(self) -> str:
        """The platform tag parsed from the wheel filename (last tag segment)."""
        stem = self.name[:-4] if self.name.endswith(".whl") else self.name
        return stem.rsplit("-", 1)[-1]

    @property
    def is_pure_python(self) -> bool:
        return "none-any" in self.name


@dataclass(frozen=True)
class PackageDep:
    name: str
    marker: str | None = None


@dataclass(frozen=True)
class LockedPackage:
    """One ``[[packages]]`` entry."""

    name: str
    version: str
    wheels: tuple[LockedWheel, ...]
    requires_python: str | None = None
    dependencies: tuple[PackageDep, ...] = ()
    marker: str | None = None
    direct_requirement: bool = False
    source_index: str | None = None

    @property
    def sort_key(self) -> tuple[str, str]:
        return (canonical_name(self.name), self.version)


def canonical_name(name: str) -> str:
    """PEP 503 normalization for package-name comparison."""
    return re.sub(r"[-_.]+", "-", name).lower()
