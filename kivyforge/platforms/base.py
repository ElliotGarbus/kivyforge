"""The ``Platform`` backend interface (common design doc 05).

A platform backend describes one build target (``ios``, ``macos``, ...). This
phase keeps the interface deliberately small — metadata, host mapping,
host-capability, and the ``package`` format set — because iOS is the only
implementation and over-abstracting against a single case is how plugin
interfaces get the wrong shape. The heavier verb dispatch (build/run/open logic
moving *into* the backend) lands when macOS becomes the second consumer and can
co-design the exact seam; see ``docs/design/common/05-platform-architecture.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class HostCapabilityError(Exception):
    """The current host cannot build for this target (e.g. iOS off macOS)."""


class Platform(ABC):
    """Describes a single build target and its host requirements."""

    #: Canonical platform name, e.g. ``"ios"``. Also the ``pylock.<name>.toml``
    #: infix and the ``[tool.kivy.<name>]`` overlay key.
    name: str

    #: Accepted CLI/env aliases in addition to ``name``.
    aliases: tuple[str, ...] = ()

    #: The ``platform.system()`` value for which this platform is the *host
    #: default* (resolution-chain step 3). Desktop targets set their own OS
    #: (macOS -> ``"Darwin"``); cross-compiled targets (iOS, Android) set
    #: ``None`` because no host maps to them — they always need explicit
    #: selection.
    host_system: str | None = None

    #: Distributable artifact shapes for ``package -f`` (first = default).
    package_formats: tuple[str, ...] = ()

    @property
    def default_package_format(self) -> str | None:
        return self.package_formats[0] if self.package_formats else None

    @property
    def selectors(self) -> tuple[str, ...]:
        """All names that select this platform (``name`` + ``aliases``)."""
        return (self.name, *self.aliases)

    @abstractmethod
    def check_host_capability(self, *, host_system: str | None = None) -> None:
        """Raise :class:`HostCapabilityError` if this host cannot build the target.

        ``host_system`` defaults to the real host (``platform.system()``); it is
        injectable so the check is unit-testable off the target host.
        """
        raise NotImplementedError
