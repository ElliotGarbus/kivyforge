"""In-memory model of ``pylock.ios.toml`` (spec 02).

PEP 751-shaped ``[[packages]]`` plus the iOS ``[tool.kivyforge]`` extension
(``python_xcframework``, xcframeworks, swift_packages). These dataclasses are
produced by the builder/resolver and serialized by ``writer``. The shared
``[[packages]]`` model (``LockedPackage``/``LockedWheel``) lives in
``kivyforge.lock.model``.
"""

from __future__ import annotations

from dataclasses import dataclass

from kivyforge.lock.model import LOCK_VERSION, LockedPackage

CREATED_BY = "kivyforge"
TOOL_SCHEMA_VERSION = 1
DEFAULT_REQUIRES_PYTHON = ">=3.15"


@dataclass(frozen=True)
class PythonXcframework:
    version: str
    url: str
    sha256: str


@dataclass(frozen=True)
class LockedXcframework:
    """One ``[[tool.kivyforge.xcframeworks]]`` entry."""

    name: str
    version: str
    sha256: str
    slices: tuple[str, ...]
    url: str | None = None
    path: str | None = None
    archive_format: str = "zip"
    archive_member: str | None = None
    privacy_manifest_path: str | None = None
    link: bool = True
    embed: bool = True
    source: str | None = None

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.path):
            raise ValueError(
                f"xcframework {self.name!r} must have exactly one of url/path"
            )


@dataclass(frozen=True)
class LockedSwiftPackage:
    """One ``[[tool.kivyforge.swift_packages]]`` entry (spec 07).

    Unlike xcframeworks, kivyforge computes no output hash here: Xcode owns the
    SPM lifecycle, so reproducibility is the pinned ``revision`` (+ the generated
    ``Package.resolved``). Exactly one of ``url`` (remote) or ``path`` (local) is
    set; ``requirement``/``revision``/``version`` are remote-only.
    """

    name: str
    products: tuple[str, ...]
    url: str | None = None
    path: str | None = None
    requirement: dict[str, object] | None = None
    revision: str | None = None
    version: str | None = None
    link: bool = True
    embed: bool = True

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.path):
            raise ValueError(
                f"swift package {self.name!r} must have exactly one of url/path"
            )


@dataclass(frozen=True)
class Lockfile:
    requires_python: str
    packages: tuple[LockedPackage, ...]
    python_xcframework: PythonXcframework
    kivyforge_version: str
    generated_at: str
    pyproject_sha256: str
    tool_kivyforge_schema_version: int
    xcframeworks: tuple[LockedXcframework, ...] = ()
    swift_packages: tuple[LockedSwiftPackage, ...] = ()
    schema_version: int = TOOL_SCHEMA_VERSION
    lock_version: str = LOCK_VERSION
    created_by: str = CREATED_BY
    extras: tuple[str, ...] = ()
    dependency_groups: tuple[str, ...] = ()
    default_groups: tuple[str, ...] = ()
