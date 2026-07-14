"""Linux lock stack (``pylock.linux.toml``).

A thin Linux *profile* (:class:`LinuxProfile`) over the generic wheel+runtime
lock engine (``kivyforge.lock.wheelruntime``). This module is the stable Linux
public surface: it binds the profile into the core and re-exports the engine's
types under Linux-friendly names so callers (the CLI, tests) never reach into
the generic package directly.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from kivyforge.config.model import Config
from kivyforge.lock.wheelruntime import (
    PythonRuntime as LinuxPythonRuntime,
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

from .profile import (
    LinuxProfile,
    effective_glibc_floor,
    is_plain_linux_tag,
    linux_wheel_arch,
    linux_wheel_coverage,
    manylinux_platform_tags,
    plain_linux_wheel_warning,
    wheel_glibc_level,
)
from .runtime import PythonBuildStandaloneProvider

# Linux-friendly aliases for the generic engine types.
LinuxLockfile = WheelRuntimeLock
LinuxBuildError = WheelRuntimeBuildError
LinuxResolverError = WheelResolverError

_PROFILE = LinuxProfile()

__all__ = [
    "LinuxBuildError",
    "LinuxLockfile",
    "LinuxProfile",
    "LinuxPythonRuntime",
    "LinuxResolverError",
    "PythonBuildStandaloneProvider",
    "ResolvedPackage",
    "ResolvedWheel",
    "RuntimeArtifact",
    "RuntimeProvider",
    "RuntimeProviderError",
    "Variant",
    "WheelResolver",
    "build_linux_lockfile",
    "diff_summary",
    "dumps",
    "effective_glibc_floor",
    "get_linux_resolver",
    "is_plain_linux_tag",
    "linux_wheel_arch",
    "linux_wheel_coverage",
    "load",
    "loads",
    "manylinux_platform_tags",
    "plain_linux_wheel_warning",
    "semantic_equal",
    "wheel_glibc_level",
]


def build_linux_lockfile(
    config: Config,
    pyproject_text: str,
    *,
    project_root: Path | None = None,
    resolver: WheelResolver | None = None,
    runtime_provider: RuntimeProvider | None = None,
    offline: bool = False,
    now: datetime | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> LinuxLockfile:
    return build_wheel_runtime_lock(
        _PROFILE,
        config,
        pyproject_text,
        project_root=project_root,
        resolver=resolver,
        runtime_provider=runtime_provider,
        native_binaries=config.linux.binaries if config.linux else (),
        offline=offline,
        now=now,
        on_warning=on_warning,
    )


def dumps(lock: LinuxLockfile) -> str:
    return _ser.dumps(lock)


def loads(text: str) -> LinuxLockfile:
    return _ser.loads(text, platform="linux")


def load(path: str | Path) -> LinuxLockfile:
    return _ser.load(path, platform="linux")


def get_linux_resolver(backend: str = "pip", **kwargs) -> WheelResolver:
    return get_wheel_resolver(backend, **kwargs)
