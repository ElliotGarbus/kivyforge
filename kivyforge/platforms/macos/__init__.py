"""macOS platform backend.

Produces a self-contained ``.app`` bundle (macos-spec). macOS is the host
default on Darwin, so a Mac with ``[tool.kivy.macos]`` configured resolves to
this backend without ``-p``. It requires a macOS host (``codesign``/``lipo``
from the Xcode command-line tools); the full Xcode IDE is not needed.
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import TYPE_CHECKING

from ..base import HostCapabilityError, Platform

if TYPE_CHECKING:
    from kivyforge.doctor.result import CheckResult


class AppBundleError(Exception):
    """A macOS ``.app`` bundling failure surfaced with an actionable message."""


class MacosPlatform(Platform):
    name = "macos"
    # macOS is a desktop target built on its own OS, so Darwin maps to it as the
    # host default (resolution-chain step 3).
    host_system = "Darwin"
    # The distributable is the .app bundle; .dmg/installer is external.
    package_formats = ("app",)

    def check_host_capability(self, *, host_system: str | None = None) -> None:
        host = host_system if host_system is not None else _platform.system()
        if host != "Darwin":
            raise HostCapabilityError(
                "building for macOS requires a macOS host; "
                f"this host is {host!r}.\n"
                "  The .app bundler signs Mach-O binaries with codesign and "
                "merges per-arch runtimes with lipo — both are macOS-only.\n"
                "  Run `kivyforge doctor -p macos` on a Mac to check the setup."
            )

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
        self.reject_ios_only_target(target)
        from .cli import macos_build

        macos_build(
            project_root,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )

    def run(
        self,
        project_root: Path,
        *,
        target: str,
        arch: str | None,
        destination: str | None,
        no_build: bool,
    ) -> None:
        from .cli import macos_run

        macos_run(project_root, arch=arch, no_build=no_build)

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
        from .cli import macos_package

        macos_package(
            project_root,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
            signing_identity=signing_identity,
            notarize=notarize,
            notary_profile=notary_profile,
        )

    def status(self, project_root: Path) -> None:
        from .cli import macos_status

        macos_status(project_root)

    def doctor(
        self, cwd: Path, *, kivyforge_version: str, offline: bool
    ) -> list[CheckResult]:
        from .doctor import macos_doctor

        return macos_doctor(cwd, kivyforge_version=kivyforge_version, offline=offline)
