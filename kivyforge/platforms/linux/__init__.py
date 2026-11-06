"""Linux platform backend.

Produces a self-contained AppDir and, by default, an AppImage (linux-spec).
Linux is the host default on Linux, so a Linux box with ``[tool.kivy.linux]``
configured resolves to this backend without ``-p``. It requires an x86_64 Linux
host: the bundled python-build-standalone runtime is a gnu/glibc ELF build, and
aarch64 is cross-built from x86_64 rather than built on the Pi.
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import TYPE_CHECKING

from kivyforge.config.model import VALID_LINUX_ARCHS
from kivyforge.report.failures import ClassifiedError

from ..base import HostCapabilityError, Platform

if TYPE_CHECKING:
    from kivyforge.build_outcome import BuildEvents, BuildOutcome
    from kivyforge.config.model import ResolvedVersion
    from kivyforge.doctor.result import CheckResult
    from kivyforge.status import StatusReport


class AppDirError(ClassifiedError):
    """A Linux AppDir bundling failure surfaced with an actionable message."""


class LinuxPlatform(Platform):
    name = "linux"
    # Linux is a desktop target built on its own OS, so Linux maps to it as the
    # host default (resolution-chain step 3).
    host_system = "Linux"
    # AppImage is the primary distributable; the AppDir folder is the substrate.
    package_formats = ("appimage", "folder")

    archs = tuple(sorted(VALID_LINUX_ARCHS))
    # aarch64 (Raspberry Pi 4/5) is a target only, cross-built from x86_64.
    # This is a testing constraint, not a technical one: an aarch64 build host
    # is not in the test matrix, so it is refused rather than shipped
    # unexercised. Widen this tuple if there is demand and a host to test on.
    host_machines = ("x86_64",)

    def host_machine_error(self, machine: str) -> str:
        return (
            "building for Linux requires an x86_64 Linux host; "
            f"this host is {machine!r}.\n"
            '  A Raspberry Pi is a target, not a build host: add "aarch64" to '
            "[tool.kivy.linux].archs on an x86_64 Linux box, then copy the "
            "aarch64 AppImage to the Pi."
        )

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
        events: BuildEvents,
        version: ResolvedVersion,
        target: str | None,
        arch: str | None,
        no_verify_lock: bool,
        no_cache: bool,
        team_id: str | None,
        signing_identity: str | None,
        export_method: str,
        debug: bool = False,
        fmt: str | None = None,
        abi: str | None = None,
    ) -> BuildOutcome:
        self.reject_ios_only_target(target)
        from .cli import linux_build

        return linux_build(
            project_root,
            version=version,
            events=events,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )

    def run(
        self,
        project_root: Path,
        *,
        version: ResolvedVersion | None,
        target: str,
        arch: str | None,
        destination: str | None,
        no_build: bool,
        release: bool = False,
    ) -> None:
        from .cli import linux_run

        linux_run(
            project_root, version=version, arch=arch, no_build=no_build, release=release
        )

    def package(
        self,
        project_root: Path,
        *,
        events: BuildEvents,
        version: ResolvedVersion,
        fmt: str,
        arch: str | None,
        team_id: str | None,
        signing_identity: str | None,
        export_method: str,
        notarize: bool | None,
        notary_profile: str | None,
        no_verify_lock: bool,
        no_cache: bool,
        abi: str | None = None,
        keystore: str | None = None,
        key_alias: str | None = None,
        debug: bool = False,
    ) -> BuildOutcome:
        from .cli import linux_package

        return linux_package(
            project_root,
            version=version,
            events=events,
            fmt=fmt,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )

    def status(self, project_root: Path) -> StatusReport:
        from .cli import linux_status

        return linux_status(project_root)

    def doctor(
        self, cwd: Path, *, kivyforge_version: str, offline: bool
    ) -> list[CheckResult]:
        from .doctor import linux_doctor

        return linux_doctor(cwd, kivyforge_version=kivyforge_version, offline=offline)
