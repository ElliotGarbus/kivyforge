"""macOS lock stack (``pylock.macos.toml``).

Parallel to the iOS lock: it reuses the platform-neutral PEP 751 ``[[packages]]``
machinery (``kivyforge.lock.pep751``) and the generic ``LockedPackage`` model,
and adds a macOS-specific ``[tool.kivyforge]`` extension recording the bundled
Python runtime (provider + per-arch artifacts) and the arch set. macOS loads
``.dylib``/``.so`` extensions directly, so there is no per-slice framework
conversion — the lock is simpler than iOS.
"""

from __future__ import annotations

from .builder import MacosBuildError, build_macos_lockfile
from .model import MacosLockfile, MacosPythonRuntime, RuntimeArtifact
from .resolver import MacosResolver, MacosResolverError, get_macos_resolver
from .runtime import (
    PythonBuildStandaloneProvider,
    RuntimeProvider,
    RuntimeProviderError,
)
from .serialize import dumps, load, loads

__all__ = [
    "MacosBuildError",
    "MacosLockfile",
    "MacosPythonRuntime",
    "MacosResolver",
    "MacosResolverError",
    "PythonBuildStandaloneProvider",
    "RuntimeArtifact",
    "RuntimeProvider",
    "RuntimeProviderError",
    "build_macos_lockfile",
    "dumps",
    "get_macos_resolver",
    "load",
    "loads",
]
