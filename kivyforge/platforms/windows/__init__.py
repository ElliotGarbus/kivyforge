"""Windows platform backend (windows-spec).

Produces a run-from-folder ``onedir`` bundle: a prebuilt windowed-subsystem
launcher ``.exe`` beside a whole python-build-standalone prefix, the app source,
a generated bootstrap, and the declared native-binaries channel. Windows is the
host default on Windows, so a Windows box with ``[tool.kivy.windows]`` configured
resolves to this backend without ``-p``. It requires a Windows host: the bundled
runtime is an MSVC amd64 build and the resource/signing tools are Windows-only.
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import TYPE_CHECKING

from ..base import HostCapabilityError, Platform

if TYPE_CHECKING:
    from kivyforge.doctor.result import CheckResult


class WindowsBundleError(Exception):
    """A Windows onedir bundling failure surfaced with an actionable message."""


class WindowsPlatform(Platform):
    name = "windows"
    aliases = ("win",)
    # Windows is a desktop target built on its own OS, so Windows maps to it as
    # the host default (resolution-chain step 3).
    host_system = "Windows"
    # The onedir folder is both the dev-run target and the shipped distributable;
    # installers stay permanently external (windows-spec). Folder is the only
    # package format.
    package_formats = ("folder",)

    def check_host_capability(self, *, host_system: str | None = None) -> None:
        host = host_system if host_system is not None else _platform.system()
        if host != "Windows":
            raise HostCapabilityError(
                "building for Windows requires a Windows host; "
                f"this host is {host!r}.\n"
                "  The onedir bundle stages an MSVC amd64 python-build-standalone "
                "runtime and uses Windows-only tools (rcedit, signtool).\n"
                "  Run `kivyforge doctor -p windows` on a Windows box to check "
                "the setup."
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
        from .cli import windows_build

        windows_build(
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
        from .cli import windows_run

        windows_run(project_root, arch=arch, no_build=no_build)

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
        from .cli import windows_package

        windows_package(
            project_root,
            fmt=fmt,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )

    def status(self, project_root: Path) -> None:
        from .cli import windows_status

        windows_status(project_root)

    def doctor(
        self, cwd: Path, *, kivyforge_version: str, offline: bool
    ) -> list[CheckResult]:
        from .doctor import windows_doctor

        return windows_doctor(cwd, kivyforge_version=kivyforge_version, offline=offline)
