"""In-memory model of ``pylock.android.toml`` (android/02).

PEP 751-shaped ``[[packages]]`` (shared ``LockedPackage``/``LockedWheel``) plus
the Android ``[tool.kivyforge]`` extension: the per-ABI python.org runtime,
``.aar``/``.jar`` pins, the Gradle/Maven resolved graph, and the
``include_files`` drift pins.
"""

from __future__ import annotations

from dataclasses import dataclass

from kivyforge.lock.model import LOCK_VERSION, LockedPackage

CREATED_BY = "kivyforge"
TOOL_SCHEMA_VERSION = 1
# Android's CPython floor (Tier 3; android/02 requires-python fallback).
DEFAULT_REQUIRES_PYTHON = ">=3.14"


@dataclass(frozen=True)
class PythonAndroidRuntime:
    """One ``[[tool.kivyforge.python_android]]`` entry (per ABI)."""

    version: str
    abi: str
    sha256: str
    min_api: int
    url: str | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.path):
            raise ValueError(
                f"python_android {self.abi!r} must have exactly one of url/path"
            )


@dataclass(frozen=True)
class LockedAndroidLib:
    """One ``[[tool.kivyforge.android_libs]]`` entry (.aar/.jar, channel 3)."""

    name: str
    kind: str  # "aar" | "jar"
    version: str
    sha256: str
    url: str | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.path):
            raise ValueError(
                f"android lib {self.name!r} must have exactly one of url/path"
            )


@dataclass(frozen=True)
class GradleArtifact:
    """One downloaded artifact of a resolved Maven module."""

    name: str
    sha256: str


@dataclass(frozen=True)
class GradleResolvedModule:
    """One ``[[tool.kivyforge.gradle.resolved]]`` entry."""

    coordinate: str
    artifacts: tuple[GradleArtifact, ...]


@dataclass(frozen=True)
class GradlePins:
    """``[tool.kivyforge.gradle]`` — declared coordinates + resolved graph."""

    dependencies: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()
    resolved: tuple[GradleResolvedModule, ...] = ()

    @property
    def declared(self) -> bool:
        return bool(self.dependencies)


@dataclass(frozen=True)
class LockedIncludeFile:
    """One ``[[tool.kivyforge.include_files]]`` drift pin."""

    source: str
    dest: str
    sha256: str


@dataclass(frozen=True)
class AndroidLockfile:
    requires_python: str
    packages: tuple[LockedPackage, ...]
    python_android: tuple[PythonAndroidRuntime, ...]
    kivyforge_version: str
    generated_at: str
    pyproject_sha256: str
    tool_kivy_android_schema_version: int
    sdl: int
    android_libs: tuple[LockedAndroidLib, ...] = ()
    gradle: GradlePins = GradlePins()
    include_files: tuple[LockedIncludeFile, ...] = ()
    schema_version: int = TOOL_SCHEMA_VERSION
    lock_version: str = LOCK_VERSION
    created_by: str = CREATED_BY
    extras: tuple[str, ...] = ()
    dependency_groups: tuple[str, ...] = ()
    default_groups: tuple[str, ...] = ()
