"""In-memory model of ``pylock.macos.toml``.

PEP 751 ``[[packages]]`` (the generic ``LockedPackage``/``LockedWheel`` from
``kivyforge.lock.model``) plus a macOS ``[tool.kivyforge]`` extension recording
the bundled Python runtime and the target arch set. The runtime is captured as
a provider name + one pinned archive per architecture (PBS ships per-arch
builds), mirroring the URL+SHA-256 discipline used for the iOS
``python_xcframework`` pin.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model import LOCK_VERSION, LockedPackage

# The macOS [tool.kivyforge] extension schema version (independent of iOS).
MACOS_TOOL_SCHEMA_VERSION = 1
CREATED_BY = "kivyforge"
DEFAULT_REQUIRES_PYTHON = ">=3.15"


@dataclass(frozen=True)
class RuntimeArtifact:
    """One per-arch bundled Python runtime archive (pinned by URL + SHA-256)."""

    arch: str  # "arm64" | "x86_64"
    url: str
    sha256: str
    archive_format: str = "tar.gz"


@dataclass(frozen=True)
class MacosPythonRuntime:
    """The bundled CPython runtime pin (provider-agnostic)."""

    provider: str  # e.g. "python-build-standalone"
    version: str  # CPython version, e.g. "3.15.0"
    artifacts: tuple[RuntimeArtifact, ...]  # one per arch in the lock
    floor: str | None = None  # runtime's own macOS floor, if the provider reports it

    def artifact_for(self, arch: str) -> RuntimeArtifact | None:
        for art in self.artifacts:
            if art.arch == arch:
                return art
        return None


@dataclass(frozen=True)
class MacosLockfile:
    requires_python: str
    packages: tuple[LockedPackage, ...]
    python_runtime: MacosPythonRuntime
    archs: tuple[str, ...]
    kivyforge_version: str
    generated_at: str
    pyproject_sha256: str
    tool_kivyforge_schema_version: int
    schema_version: int = MACOS_TOOL_SCHEMA_VERSION
    lock_version: str = LOCK_VERSION
    created_by: str = CREATED_BY
    extras: tuple[str, ...] = ()
    dependency_groups: tuple[str, ...] = ()
    default_groups: tuple[str, ...] = ()
