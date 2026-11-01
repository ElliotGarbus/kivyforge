"""macOS lock stack (``pylock.macos.toml``).

A thin macOS *profile* (:class:`MacosProfile`) over the generic wheel+runtime
lock engine (``kivyforge.lock.wheelruntime``). This module is the stable macOS
public surface: it binds the profile into the core and re-exports the engine's
types under macOS-friendly names so callers (the CLI, tests) never reach into the
generic package directly.

Swift packages (#201) are pinned here, not in the engine: the resolver is the
iOS one (``platforms/ios/lock/spm.py``), and SPM is no other wheel+runtime
platform's concern.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from kivyforge.config.model import Config
from kivyforge.lock.model import LockedPackage
from kivyforge.lock.wheelruntime import (
    PythonRuntime as MacosPythonRuntime,
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
    get_wheel_resolver,
    semantic_equal,
)
from kivyforge.lock.wheelruntime import diff_summary as _engine_diff_summary
from kivyforge.lock.wheelruntime import serialize as _ser
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime as WheelRuntimePython,
)

from ...ios.lock.spm import (
    SpmResolver,
    SpmResolverError,
    get_spm_resolver,
    lock_swift_packages,
    swift_package_changes,
)
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
    *,
    project_root: Path | None = None,
    resolver: WheelResolver | None = None,
    runtime_provider: RuntimeProvider | None = None,
    prefer: Iterable[LockedPackage] = (),
    prefer_runtime: WheelRuntimePython | None = None,
    offline: bool = False,
    now: datetime | None = None,
    on_warning: Callable[[str], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    on_transfer: Callable[[str, int, int, str], None] | None = None,
    spm_resolver: SpmResolver | None = None,
) -> MacosLockfile:
    root = (project_root or Path.cwd()).resolve()
    try:
        swift_packages = lock_swift_packages(
            config.macos.swift_packages if config.macos else (),
            lambda: spm_resolver or get_spm_resolver(on_progress=on_progress),
            project_root=root,
            offline=offline,
        )
    except SpmResolverError as exc:
        raise MacosBuildError(str(exc)) from exc
    return build_wheel_runtime_lock(
        _PROFILE,
        config,
        project_root=project_root,
        resolver=resolver,
        runtime_provider=runtime_provider,
        native_binaries=config.macos.binaries if config.macos else (),
        include_files=config.macos.include_files if config.macos else (),
        swift_packages=tuple(swift_packages),
        prefer=prefer,
        prefer_runtime=prefer_runtime,
        offline=offline,
        now=now,
        on_warning=on_warning,
        on_progress=on_progress,
        on_transfer=on_transfer,
    )


def diff_summary(old: MacosLockfile, new: MacosLockfile) -> list[str]:
    return _engine_diff_summary(old, new) + swift_package_changes(
        old.swift_packages, new.swift_packages
    )


def dumps(lock: MacosLockfile) -> str:
    return _ser.dumps(lock)


def loads(text: str) -> MacosLockfile:
    return _ser.loads(text, platform="macos")


def load(path: str | Path) -> MacosLockfile:
    return _ser.load(path, platform="macos")


def get_macos_resolver(backend: str = "pip", **kwargs) -> WheelResolver:
    return get_wheel_resolver(backend, **kwargs)
