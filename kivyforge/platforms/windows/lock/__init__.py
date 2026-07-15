"""Windows lock stack (``pylock.windows.toml``).

A thin Windows *profile* (:class:`WindowsProfile`) over the generic
wheel+runtime lock engine (``kivyforge.lock.wheelruntime``). This module is the
stable Windows public surface: it binds the profile into the core and re-exports
the engine's types under Windows-friendly names so callers (the CLI, tests)
never reach into the generic package directly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from kivyforge.config.model import Config
from kivyforge.lock.wheelruntime import (
    PythonRuntime as WindowsPythonRuntime,
)
from kivyforge.lock.wheelruntime import (
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
from kivyforge.lock.wheelruntime import serialize as _ser

from .profile import WindowsProfile, wheel_arch, windows_platform_tag
from .runtime import PythonBuildStandaloneProvider

# Windows-friendly aliases for the generic engine types.
WindowsLockfile = WheelRuntimeLock
WindowsBuildError = WheelRuntimeBuildError
WindowsResolverError = WheelResolverError

_PROFILE = WindowsProfile()

__all__ = [
    "PythonBuildStandaloneProvider",
    "ResolvedPackage",
    "ResolvedWheel",
    "RuntimeArtifact",
    "RuntimeProvider",
    "RuntimeProviderError",
    "Variant",
    "WheelResolver",
    "WindowsBuildError",
    "WindowsLockfile",
    "WindowsProfile",
    "WindowsPythonRuntime",
    "WindowsResolverError",
    "build_windows_lockfile",
    "diff_summary",
    "dumps",
    "get_windows_resolver",
    "load",
    "loads",
    "semantic_equal",
    "wheel_arch",
    "windows_platform_tag",
]


def build_windows_lockfile(
    config: Config,
    pyproject_text: str,
    *,
    project_root: Path | None = None,
    resolver: WheelResolver | None = None,
    runtime_provider: RuntimeProvider | None = None,
    offline: bool = False,
    now: datetime | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> WindowsLockfile:
    return build_wheel_runtime_lock(
        _PROFILE,
        config,
        pyproject_text,
        project_root=project_root,
        resolver=resolver,
        runtime_provider=runtime_provider,
        native_binaries=config.windows.binaries if config.windows else (),
        offline=offline,
        now=now,
        on_warning=on_warning,
    )


def dumps(lock: WindowsLockfile) -> str:
    return _ser.dumps(lock)


def loads(text: str) -> WindowsLockfile:
    return _ser.loads(text, platform="windows")


def load(path: str | Path) -> WindowsLockfile:
    return _ser.load(path, platform="windows")


def get_windows_resolver(backend: str = "pip", **kwargs) -> WheelResolver:
    return get_wheel_resolver(backend, **kwargs)
