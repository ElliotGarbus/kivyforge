"""Generic ``wheel + bundled-runtime`` lockfile model.

Shared by every platform whose lock is "platform-tagged wheels plus a bundled
CPython runtime": macOS today, and Linux/Windows/Android in later phases. Each
such platform differs only in a small *profile* (tag construction, the arch/ABI
variant set, and the runtime provider); the lockfile *shape* is identical, so it
lives here once. iOS is deliberately not part of this family — its per-slice
framework conversion, ``Python.xcframework`` runtime, and SPM extension give it a
genuinely different lock shape.

PEP 751 ``[[packages]]`` (the generic ``LockedPackage``/``LockedWheel`` from
``kivyforge.lock.model``) plus a ``[tool.kivyforge]`` extension recording the
arch set and the runtime pin (provider + one archive per arch).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model import LOCK_VERSION, LockedPackage

# The wheel-runtime [tool.kivyforge] extension schema version.
TOOL_SCHEMA_VERSION = 1
CREATED_BY = "kivyforge"
DEFAULT_REQUIRES_PYTHON = ">=3.15"


@dataclass(frozen=True)
class RuntimeArtifact:
    """One per-arch bundled Python runtime archive (pinned by URL + SHA-256).

    ``arch`` is the variant identifier: a CPU architecture on desktops
    (``arm64``/``x86_64``) or an ABI on Android (``arm64-v8a``/…).
    """

    arch: str
    url: str
    sha256: str
    archive_format: str = "tar.gz"


@dataclass(frozen=True)
class PythonRuntime:
    """The bundled CPython runtime pin (provider-agnostic)."""

    provider: str  # e.g. "python-build-standalone"
    version: str  # CPython version, e.g. "3.15.0"
    artifacts: tuple[RuntimeArtifact, ...]  # one per arch in the lock
    floor: str | None = None  # runtime's own OS floor, if the provider reports it

    def artifact_for(self, arch: str) -> RuntimeArtifact | None:
        for art in self.artifacts:
            if art.arch == arch:
                return art
        return None


@dataclass(frozen=True)
class LockedNativeBinary:
    """One pinned ``[tool.kivy.<platform>.native.binaries]`` entry.

    A non-wheel native binary (vendor SDK dylib/so/DLL or a helper executable)
    pinned by SHA-256. Exactly one of ``url`` (remote source) or ``path``
    (repo-relative vendored source) is set — the ``LockedXcframework``
    convention.
    """

    name: str
    version: str
    sha256: str
    url: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class WheelRuntimeLock:
    """A ``pylock.<platform>.toml`` for the wheel + bundled-runtime family."""

    platform: str  # "macos" | "linux" | "windows" | "android"
    requires_python: str
    packages: tuple[LockedPackage, ...]
    python_runtime: PythonRuntime
    archs: tuple[str, ...]
    kivyforge_version: str
    generated_at: str
    pyproject_sha256: str
    tool_kivyforge_schema_version: int
    schema_version: int = TOOL_SCHEMA_VERSION
    lock_version: str = LOCK_VERSION
    created_by: str = CREATED_BY
    extras: tuple[str, ...] = ()
    dependency_groups: tuple[str, ...] = ()
    default_groups: tuple[str, ...] = ()
    native_binaries: tuple[LockedNativeBinary, ...] = ()
