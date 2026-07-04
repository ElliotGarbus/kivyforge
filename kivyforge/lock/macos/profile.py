"""macOS lock profile — the platform-specific inputs to the wheel+runtime core.

macOS variants are CPU architectures (``arm64``/``x86_64``); a ``universal2``
wheel covers both. The bundled runtime comes from python-build-standalone (darwin
triples). Everything else — resolve/serialize/build orchestration — is the shared
core.
"""

from __future__ import annotations

import re

from ...config.model import Config
from ..wheelruntime.profile import PlatformLockProfile
from ..wheelruntime.resolver import Variant
from ..wheelruntime.runtime import RuntimeProvider
from .runtime import PythonBuildStandaloneProvider

# Default macOS deployment floor for the pip ``--platform`` request when the
# project sets no ``minimum_system_version``. pip matches wheels tagged at or
# below this floor (plus universal2), maximizing compatible wheels.
DEFAULT_MACOS_FLOOR = "11.0"

VALID_WHEEL_ARCHS = frozenset({"arm64", "x86_64", "universal2"})


def macos_platform_tag(floor: str, arch: str) -> str:
    """The pip ``--platform`` tag for a macOS deployment floor + arch."""
    return f"macosx_{floor.replace('.', '_')}_{arch}"


def wheel_arch(platform_tag: str) -> str | None:
    """The architecture a macOS wheel platform tag targets, or ``None``.

    ``macosx_11_0_arm64`` -> ``arm64``; ``macosx_11_0_x86_64`` -> ``x86_64``;
    ``..._universal2`` -> ``universal2``. The arch is what follows the
    ``macosx_<major>_<minor>_`` prefix (``x86_64`` itself has an underscore, so a
    naive rsplit is wrong).
    """
    match = re.fullmatch(r"macosx_\d+_\d+_(.+)", platform_tag)
    if match is None:
        return None
    arch = match.group(1)
    return arch if arch in VALID_WHEEL_ARCHS else None


class MacosProfile(PlatformLockProfile):
    platform = "macos"

    def overlay(self, config: Config):
        return config.macos

    def missing_overlay_error(self) -> str:
        return "pyproject.toml has no [tool.kivy.macos] table; nothing to lock."

    def python_version(self, config: Config) -> str:
        return config.macos_required.python_version or "3.15.0"

    def _floor(self, config: Config) -> str:
        return config.macos_required.minimum_system_version or DEFAULT_MACOS_FLOOR

    def variants(self, config: Config) -> tuple[Variant, ...]:
        floor = self._floor(config)
        return tuple(
            Variant(arch=arch, platform_tag=macos_platform_tag(floor, arch))
            for arch in config.macos_required.archs
        )

    def wheel_covers(self, platform_tag: str, archs: tuple[str, ...]) -> set[str]:
        arch = wheel_arch(platform_tag)
        if arch == "universal2":
            return set(archs)
        if arch in archs:
            return {arch}
        return set()

    def runtime_provider(self, config: Config) -> RuntimeProvider:
        return PythonBuildStandaloneProvider()

    def declared_floor(self, config: Config) -> str | None:
        return config.macos_required.minimum_system_version

    def coverage_error(self, name: str, missing: list[str]) -> str:
        return (
            f"{name} is missing macOS wheel(s) for arch(es): {', '.join(missing)}.\n"
            f"  A compiled package must publish a per-arch or universal2 wheel for "
            f"every targeted arch to be locked reproducibly.\n"
            f"  If this dependency has no Intel wheels, set "
            f'[tool.kivy.macos].archs = ["arm64"] and re-lock.'
        )

    def floor_error(self, declared: str, runtime_floor: str, version: str) -> str:
        return (
            f"minimum_system_version {declared} is below the macOS {runtime_floor} "
            f"floor required by the Python {version} runtime.\n"
            f"  Raise [tool.kivy.macos].minimum_system_version to at least "
            f"{runtime_floor}."
        )

    def wheel_scope_hint(self) -> str:
        return (
            "Vendored wheels must live under the project directory, a sibling "
            "directory, or the enclosing repository (e.g. examples/wheels/macos/)."
        )
