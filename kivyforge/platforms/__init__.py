"""Platform backend registry + target resolution (common design docs 02, 05).

The registry is a plain, static dict of in-repo backends — no entry-point plugin
discovery yet (it can be added later without changing callers). ``resolve_target``
implements the documented resolution chain:

    --platform / -p  >  KIVYFORGE_PLATFORM  >  host OS  >  actionable error
"""

from __future__ import annotations

import platform as _platform
from collections.abc import Collection, Mapping

from .base import HostCapabilityError, Platform
from .ios import IosPlatform

__all__ = [
    "HostCapabilityError",
    "Platform",
    "PlatformResolutionError",
    "PLATFORM_ENV_VAR",
    "available_platform_names",
    "get_platform",
    "resolve_target",
]

PLATFORM_ENV_VAR = "KIVYFORGE_PLATFORM"

# Registered backends, in display order. Add new platforms here.
_REGISTRY: tuple[Platform, ...] = (IosPlatform(),)

# name/alias -> backend
_BY_SELECTOR: dict[str, Platform] = {
    selector: backend for backend in _REGISTRY for selector in backend.selectors
}


class PlatformResolutionError(Exception):
    """No target platform could be resolved from CLI/env/host."""


def available_platform_names() -> list[str]:
    """Canonical names of registered platforms (for ``click.Choice``)."""
    return [backend.name for backend in _REGISTRY]


def get_platform(name: str) -> Platform:
    """Return the backend registered under ``name`` or an alias."""
    try:
        return _BY_SELECTOR[name]
    except KeyError:
        raise PlatformResolutionError(
            f"unknown platform {name!r}; "
            f"registered: {', '.join(available_platform_names())}"
        ) from None


def resolve_target(
    cli_platform: str | None,
    *,
    configured: Collection[str],
    env: Mapping[str, str] | None = None,
    host_system: str | None = None,
) -> Platform:
    """Resolve the target platform per the documented chain.

    ``configured`` is the set of platform names whose overlay this project's
    ``pyproject.toml`` actually declares (e.g. ``{"ios"}`` for ``[tool.kivy.ios]``).
    ``env``/``host_system`` are injectable for testing.
    """
    env = env if env is not None else {}

    # 1. explicit --platform / -p
    if cli_platform:
        return get_platform(cli_platform)

    # 2. KIVYFORGE_PLATFORM session/CI default
    env_platform = env.get(PLATFORM_ENV_VAR)
    if env_platform:
        return get_platform(env_platform)

    # 3. host OS -> its own platform, only if registered *and* configured
    host = host_system if host_system is not None else _platform.system()
    for backend in _REGISTRY:
        if backend.host_system == host and backend.name in configured:
            return backend

    # 4. actionable error
    raise PlatformResolutionError(_resolution_help(configured))


def _resolution_help(configured: Collection[str]) -> str:
    configured_list = ", ".join(sorted(configured)) or "none"
    example = sorted(configured)[0] if configured else "macos"
    return (
        "no target platform resolved.\n"
        f"  Pass one explicitly:      kivyforge build --platform {example}\n"
        f"  Or set a session default: export {PLATFORM_ENV_VAR}={example}\n"
        f"  (Configured platforms in this pyproject.toml: {configured_list})"
    )
