"""Generic ``wheel + bundled-runtime`` lock engine.

The reusable core for every platform whose lock is "platform-tagged wheels plus
a bundled CPython runtime": macOS now; Linux, Windows, Android later. Each such
platform is a thin :class:`PlatformLockProfile` over this engine — no new
builder, resolver, model, or serializer. iOS is intentionally *not* in this
family (its per-slice framework/xcframework/SPM lock is a different shape).
"""

from __future__ import annotations

from .builder import (
    WheelRuntimeBuildError,
    build_wheel_runtime_lock,
    diff_summary,
    semantic_equal,
)
from .model import PythonRuntime, RuntimeArtifact, WheelRuntimeLock
from .profile import PlatformLockProfile
from .resolver import (
    PipWheelResolver,
    ResolvedPackage,
    ResolvedWheel,
    Variant,
    WheelResolver,
    WheelResolverError,
    get_wheel_resolver,
)
from .runtime import (
    PbsProvider,
    ReleaseAsset,
    RuntimeProvider,
    RuntimeProviderError,
    pbs_asset_glob,
)
from .serialize import dumps, load, loads

__all__ = [
    "PbsProvider",
    "PipWheelResolver",
    "PlatformLockProfile",
    "PythonRuntime",
    "ReleaseAsset",
    "ResolvedPackage",
    "ResolvedWheel",
    "RuntimeArtifact",
    "RuntimeProvider",
    "RuntimeProviderError",
    "Variant",
    "WheelResolver",
    "WheelResolverError",
    "WheelRuntimeBuildError",
    "WheelRuntimeLock",
    "build_wheel_runtime_lock",
    "diff_summary",
    "dumps",
    "get_wheel_resolver",
    "load",
    "loads",
    "pbs_asset_glob",
    "semantic_equal",
]
