"""Windows lock profile — the platform-specific inputs to the wheel+runtime core.

The simplest of the desktop family: Windows has a single stable wheel platform
tag per arch (``win_amd64`` this phase — ``win32``/``win_arm64`` are out of
scope), so there is no tag ladder (Linux) and no fat-wheel arch (macOS
``universal2``). ``kivy_deps.*`` are ordinary wheels — Kivy's ``win_amd64`` wheel
declares them as conditional dependencies, so they flow through the shared
resolver with URL + SHA-256 pins with no special-casing. The bundled runtime
comes from python-build-standalone (``x86_64-pc-windows-msvc``). Everything else
— resolve/serialize/build orchestration — is the shared core.
"""

from __future__ import annotations

from kivyforge.config.errors import ConfigError
from kivyforge.config.model import Config
from kivyforge.lock.wheelruntime.profile import PlatformLockProfile
from kivyforge.lock.wheelruntime.resolver import Variant
from kivyforge.lock.wheelruntime.runtime import RuntimeProvider

from .runtime import PythonBuildStandaloneProvider

VALID_WHEEL_ARCHS = frozenset({"amd64"})

# kivyforge arch name -> the wheel platform tag pip requests / a wheel carries.
_ARCH_TO_TAG = {"amd64": "win_amd64"}
_TAG_TO_ARCH = {tag: arch for arch, tag in _ARCH_TO_TAG.items()}


def windows_platform_tag(arch: str) -> str:
    """The pip ``--platform`` tag for a Windows arch (``amd64`` -> ``win_amd64``)."""
    return _ARCH_TO_TAG[arch]


def wheel_arch(platform_tag: str) -> str | None:
    """The architecture a Windows wheel platform tag targets, or ``None``.

    ``win_amd64`` -> ``amd64``. ``win32`` (x86) and ``win_arm64`` are recognized
    as Windows tags but are unsupported this phase, so they resolve to their arch
    name only if that arch is a valid target (they are not), i.e. ``None`` here.
    A non-Windows tag (``any`` is handled by the shared core) also returns
    ``None``.
    """
    return _TAG_TO_ARCH.get(platform_tag)


class WindowsProfile(PlatformLockProfile):
    platform = "windows"

    def overlay(self, config: Config):
        return config.windows

    def missing_overlay_error(self) -> str:
        return "pyproject.toml has no [tool.kivy.windows] table; nothing to lock."

    def python_version(self, config: Config) -> str:
        # [tool.kivy.windows.python].version is required (the loader raises a
        # ConfigError when it is missing), so it is always set here. Never
        # silently substitute a hidden default — that would pin an unexpected
        # (and possibly unreleased) Python instead of surfacing the misconfig.
        version = config.windows_required.python_version
        if not version:
            raise ConfigError(
                "missing required [tool.kivy.windows.python].version",
                key_path="tool.kivy.windows.python.version",
            )
        return version

    def variants(self, config: Config) -> tuple[Variant, ...]:
        return tuple(
            Variant(arch=arch, platform_tag=windows_platform_tag(arch))
            for arch in config.windows_required.archs
        )

    def wheel_covers(self, platform_tag: str, archs: tuple[str, ...]) -> set[str]:
        arch = wheel_arch(platform_tag)
        if arch in archs:
            return {arch}
        return set()

    def runtime_provider(self, config: Config) -> RuntimeProvider:
        return PythonBuildStandaloneProvider()

    def coverage_error(self, name: str, missing: list[str]) -> str:
        return (
            f"{name} has no win_amd64 wheel for arch(es): {', '.join(missing)}.\n"
            f"  A compiled package must publish a win_amd64 wheel to be locked "
            f"reproducibly.\n"
            f"  Supply the wheel via extra_index_urls/find_links, or drop the "
            f"dependency on Windows."
        )

    def wheel_scope_hint(self) -> str:
        return (
            "Vendored wheels must live under the project directory, a sibling "
            "directory, or the enclosing repository (e.g. a wheels/ directory "
            "beside pyproject.toml)."
        )
