"""macOS lock stack (``pylock.macos.toml``).

A thin macOS *profile* (:class:`MacosProfile`) over the generic wheel+runtime
lock engine (``kivyforge.lock.wheelruntime``). This module is the stable macOS
public surface: it binds the profile into the core and re-exports the engine's
types under macOS-friendly names so callers (the CLI, tests) never reach into the
generic package directly.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ...config.model import Config
from ..wheelruntime import (
    PythonRuntime as MacosPythonRuntime,
)
from ..wheelruntime import (
    ResolvedPackage,
    ResolvedWheel,
    RuntimeArtifact,
    RuntimeProvider,
    RuntimeProviderError,
    Variant,
    WheelResolver,
    WheelResolverError,
    WheelRuntimeBuildError,
    WheelRuntimeLock,
    build_wheel_runtime_lock,
    diff_summary,
    get_wheel_resolver,
    semantic_equal,
)
from ..wheelruntime import serialize as _ser
from .profile import MacosProfile, macos_platform_tag, wheel_arch
from .runtime import PythonBuildStandaloneProvider

# macOS-friendly aliases for the generic engine types.
MacosLockfile = WheelRuntimeLock
MacosBuildError = WheelRuntimeBuildError
MacosResolverError = WheelResolverError

_PROFILE = MacosProfile()

__all__ = [
    "MacosBuildError",
    "MacosLockfile",
    "MacosProfile",
    "MacosPythonRuntime",
    "MacosResolverError",
    "PythonBuildStandaloneProvider",
    "ResolvedPackage",
    "ResolvedWheel",
    "RuntimeArtifact",
    "RuntimeProvider",
    "RuntimeProviderError",
    "Variant",
    "WheelResolver",
    "build_macos_lockfile",
    "diff_summary",
    "dumps",
    "get_macos_resolver",
    "load",
    "loads",
    "macos_platform_tag",
    "semantic_equal",
    "wheel_arch",
]


def build_macos_lockfile(
    config: Config,
    pyproject_text: str,
    *,
    project_root: Path | None = None,
    resolver: WheelResolver | None = None,
    runtime_provider: RuntimeProvider | None = None,
    offline: bool = False,
    now: datetime | None = None,
) -> MacosLockfile:
    return build_wheel_runtime_lock(
        _PROFILE,
        config,
        pyproject_text,
        project_root=project_root,
        resolver=resolver,
        runtime_provider=runtime_provider,
        offline=offline,
        now=now,
    )


def dumps(lock: MacosLockfile) -> str:
    return _ser.dumps(lock)


def loads(text: str) -> MacosLockfile:
    return _ser.loads(text, platform="macos")


def load(path: str | Path) -> MacosLockfile:
    return _ser.load(path, platform="macos")


def get_macos_resolver(backend: str = "pip", **kwargs) -> WheelResolver:
    return get_wheel_resolver(backend, **kwargs)
