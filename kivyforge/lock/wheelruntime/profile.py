"""The per-platform lock *profile* for the wheel+runtime family.

A profile is the small, platform-specific seam the generic builder/resolver
depend on. It reads the platform's ``[tool.kivy.<platform>]`` overlay off the
shared ``Config`` and answers: which variants to resolve, how a wheel tag maps to
variants (the coverage rule), which runtime provider to use, and the
platform-appropriate error/hint wording. Adding Linux/Windows/Android is writing
one of these — no new builder, resolver, model, or serializer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...config.model import Config
from .resolver import Variant, WheelResolver, get_wheel_resolver
from .runtime import RuntimeProvider


class PlatformLockProfile(ABC):
    """Platform-specific inputs to the generic wheel+runtime lock engine."""

    #: Platform name; the ``pylock.<platform>.toml`` infix + overlay key.
    platform: str

    @abstractmethod
    def overlay(self, config: Config):
        """The platform overlay object (e.g. ``config.macos``), or ``None``."""

    @abstractmethod
    def missing_overlay_error(self) -> str:
        """Message when the overlay is absent (nothing to lock)."""

    @abstractmethod
    def python_version(self, config: Config) -> str:
        """The bundled CPython version to pin."""

    @abstractmethod
    def variants(self, config: Config) -> tuple[Variant, ...]:
        """The build variants to resolve (arch/ABI + pip ``--platform`` tag)."""

    @abstractmethod
    def wheel_covers(self, platform_tag: str, archs: tuple[str, ...]) -> set[str]:
        """The subset of ``archs`` a wheel's platform tag satisfies.

        A fat wheel (e.g. macOS ``universal2``) returns every arch; a per-arch
        wheel returns its own; an unrelated tag returns the empty set.
        """

    def wheel_coverage(
        self, wheel, archs: tuple[str, ...]
    ) -> tuple[set[str], str | None]:
        """Archs a resolved *wheel* covers, plus an optional non-fatal warning.

        Default: the pure tag→arch rule (:meth:`wheel_covers`) with no warning.
        A platform may override to gate coverage on the wheel's *source* — e.g.
        Linux accepts a plain ``linux_*`` (no-glibc-promise) wheel only when it
        was vendored via ``find_links``, and warns when it does.
        """
        return self.wheel_covers(wheel.platform_tag, archs), None

    @abstractmethod
    def runtime_provider(self, config: Config) -> RuntimeProvider:
        """The default runtime provider for this platform."""

    @abstractmethod
    def coverage_error(self, name: str, missing: list[str]) -> str:
        """Message when a compiled package is missing a required variant."""

    @abstractmethod
    def wheel_scope_hint(self) -> str:
        """The vendored-wheel scope hint (platform-appropriate example path)."""

    # --- fields with cross-platform defaults (overlay-name agnostic accessors) ---

    def wheel_resolver(self) -> WheelResolver:
        return get_wheel_resolver("pip")

    def extra_index_urls(self, config: Config) -> tuple[str, ...]:
        return tuple(getattr(self.overlay(config), "extra_index_urls", ()) or ())

    def find_links(self, config: Config) -> tuple[str, ...]:
        return tuple(getattr(self.overlay(config), "find_links", ()) or ())

    def exclude(self, config: Config) -> tuple[str, ...]:
        return tuple(getattr(self.overlay(config), "exclude", ()) or ())

    def archs(self, config: Config) -> tuple[str, ...]:
        return tuple(v.arch for v in self.variants(config))

    def schema_version(self, config: Config) -> int:
        return int(getattr(self.overlay(config), "schema_version", 1))

    def declared_floor(self, config: Config) -> str | None:
        """The user-declared OS floor to validate against the runtime floor."""
        return None

    def floor_error(
        self, declared: str, runtime_floor: str, version: str
    ) -> str:  # pragma: no cover - overridden where a floor exists
        return (
            f"the declared OS floor {declared} is below the {runtime_floor} floor "
            f"required by the Python {version} runtime."
        )
