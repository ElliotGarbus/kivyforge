"""iOS platform backend: metadata, host capability, and verb dispatch.

The iOS build/run/package/open/status/doctor logic lives in ``.cli`` and
``.doctor``; the verb methods here lazily import them so importing the backend
class stays cheap and cycle-free.
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path
from typing import TYPE_CHECKING

from ..base import HostCapabilityError, Platform

if TYPE_CHECKING:
    from kivyforge.build_outcome import BuildEvents, BuildOutcome
    from kivyforge.doctor.result import CheckResult
    from kivyforge.status import StatusReport


class IosPlatform(Platform):
    name = "ios"
    # iOS is cross-compiled from macOS: no host maps to it, so it is never a
    # host default and must be selected explicitly (-p ios / KIVYFORGE_PLATFORM).
    host_system = None
    # The distributable is the Xcode-built app / .ipa (App Store submission is
    # external). Only one shape today, so `-f` defaults to it.
    package_formats = ("ipa",)

    def check_host_capability(self, *, host_system: str | None = None) -> None:
        host = host_system if host_system is not None else _platform.system()
        if host != "Darwin":
            raise HostCapabilityError(
                "building for iOS requires macOS with Xcode; "
                f"this host is {host!r}.\n"
                "  iOS wheels and the Python.xcframework are cross-built on a "
                "macOS host — there is no on-device or off-macOS build path.\n"
                "  Run `kivyforge doctor -p ios` on a Mac to check Xcode setup."
            )

    def build(
        self,
        project_root: Path,
        *,
        events: BuildEvents,
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
        from .cli import ios_build

        return ios_build(
            project_root,
            events=events,
            target=target,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
            team_id=team_id,
            signing_identity=signing_identity,
            export_method=export_method,
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
        from .cli import ios_run

        ios_run(
            project_root,
            target=target,
            destination=destination,
            no_build=no_build,
        )

    def package(
        self,
        project_root: Path,
        *,
        events: BuildEvents,
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
    ) -> BuildOutcome:
        from .cli import ios_package

        return ios_package(
            project_root,
            events=events,
            team_id=team_id,
            signing_identity=signing_identity,
            export_method=export_method,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )

    def open_project(self, project_root: Path, *, events: BuildEvents) -> Path:
        from .cli import ios_open

        return ios_open(project_root, events=events)

    def status(self, project_root: Path) -> StatusReport:
        from .cli import ios_status

        return ios_status(project_root)

    def doctor(
        self, cwd: Path, *, kivyforge_version: str, offline: bool
    ) -> list[CheckResult]:
        from .doctor import ios_doctor

        return ios_doctor(cwd, kivyforge_version=kivyforge_version, offline=offline)
