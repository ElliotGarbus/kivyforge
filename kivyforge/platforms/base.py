"""The ``Platform`` backend interface (common design doc 05).

A platform backend describes one build target (``ios``, ``macos``, ...) and owns
its verb behavior: metadata, host mapping, host-capability, package formats, and
the ``build``/``run``/``package``/``doctor`` implementations. The ``cli`` verbs
resolve the target and dispatch to these methods, so adding a platform is a
matter of registering one ``Platform`` subclass — the verbs stay backend-agnostic
(see ``docs/design/common/05-platform-architecture.md``).

Each verb method lazily imports its backend's implementation module
(``platforms/<os>/cli.py`` / ``doctor.py``) so importing the backend class stays
cheap and cycle-free (registry -> backend -> bundler/lock/cli is only paid when a
verb actually runs).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from kivyforge.doctor.result import CheckResult


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

    # -- verb dispatch ----------------------------------------------------- #
    #
    # Default implementations raise so an unimplemented verb surfaces clearly.
    # Every registered backend overrides the verbs it supports; the ``cli`` verbs
    # pass the full option superset and each backend takes what it needs.

    def build(
        self,
        project_root: Path,
        *,
        target: str | None,
        arch: str | None,
        no_verify_lock: bool,
        no_cache: bool,
        team_id: str | None,
        signing_identity: str | None,
        export_method: str,
    ) -> None:
        raise NotImplementedError(f"build is not supported for {self.name!r}.")

    def run(
        self,
        project_root: Path,
        *,
        target: str,
        arch: str | None,
        destination: str | None,
        no_build: bool,
    ) -> None:
        raise NotImplementedError(f"run is not supported for {self.name!r}.")

    def package(
        self,
        project_root: Path,
        *,
        fmt: str,
        arch: str | None,
        team_id: str | None,
        signing_identity: str | None,
        export_method: str,
        notarize: bool | None,
        notary_profile: str | None,
        no_verify_lock: bool,
        no_cache: bool,
    ) -> None:
        raise NotImplementedError(f"package is not supported for {self.name!r}.")

    def open_project(self, project_root: Path) -> None:
        from kivyforge.cli._common import ToolchainError

        raise ToolchainError(
            f"`open` is an iOS/Xcode command; {self.name} has no project to open."
        )

    def status(self, project_root: Path) -> None:
        raise NotImplementedError(f"status is not supported for {self.name!r}.")

    def doctor(
        self, cwd: Path, *, kivyforge_version: str, offline: bool
    ) -> list[CheckResult]:
        raise NotImplementedError(f"doctor is not supported for {self.name!r}.")

    def reject_ios_only_target(self, target: str | None) -> None:
        """Desktop backends reject the iOS-only ``--simulator/--device/--release``."""
        if target is None:
            return
        from kivyforge.cli._common import ToolchainError

        artifact = {"macos": ".app", "linux": "AppDir", "windows": "onedir folder"}.get(
            self.name, "bundle"
        )
        raise ToolchainError(
            f"--{target} is an iOS target; {self.name} has no simulator/device/"
            "release targets.\n"
            f"  Use `kivyforge build -p {self.name}` (optionally --arch) to build "
            f"the {artifact}, or `kivyforge package -p {self.name}` for the "
            "distributable."
        )
