"""Linux platform backend.

Produces a self-contained AppDir and, by default, an AppImage (linux-spec).
Linux is the host default on Linux, so a Linux box with ``[tool.kivy.linux]``
configured resolves to this backend without ``-p``. It requires a Linux host:
the bundled python-build-standalone runtime is a gnu/glibc ELF build.
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import TYPE_CHECKING

from ..base import HostCapabilityError, Platform

if TYPE_CHECKING:
    from kivyforge.doctor.result import CheckResult


class AppDirError(Exception):
    """A Linux AppDir bundling failure surfaced with an actionable message."""


class LinuxPlatform(Platform):
    name = "linux"
    # Linux is a desktop target built on its own OS, so Linux maps to it as the
    # host default (resolution-chain step 3).
    host_system = "Linux"
    # AppImage is the primary distributable; the AppDir folder is the substrate.
    package_formats = ("appimage", "folder")

    def check_host_capability(self, *, host_system: str | None = None) -> None:
        host = host_system if host_system is not None else _platform.system()
        if host != "Linux":
            raise HostCapabilityError(
                "building for Linux requires a Linux host; "
                f"this host is {host!r}.\n"
                "  The AppDir bundles a python-build-standalone gnu/glibc runtime "
                "and runs the app against the host's libGL/X11/Wayland.\n"
                "  Run `kivyforge doctor -p linux` on a Linux box to check the "
                "setup."
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
        from .cli import linux_build

        linux_build(
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
        from .cli import linux_run

        linux_run(project_root, arch=arch, no_build=no_build)

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
        from .cli import linux_package

        linux_package(
            project_root,
            fmt=fmt,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )

    def doctor(
        self, cwd: Path, *, kivyforge_version: str, offline: bool
    ) -> list[CheckResult]:
        from .doctor import linux_doctor

        return linux_doctor(cwd, kivyforge_version=kivyforge_version, offline=offline)
