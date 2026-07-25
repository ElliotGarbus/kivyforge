"""Android platform backend (docs/design/platforms/android/01-08).

Produces a Gradle/AGP project from ``pyproject.toml`` + ``pylock.android.toml``
— the ABI-independent Python asset bundle, flattened extension ``.so``s in
``jniLibs/<abi>/``, the kivyforge-owned bootstrap (stock SDL Java glue +
``PythonActivity`` + the ``SDL_main`` native launcher), and a signed ``.apk`` /
``.aab``. Android is a cross-compiled target: no host OS maps to it as a
default, so it always needs explicit ``-p android`` (or ``KIVYFORGE_PLATFORM``).
Any desktop host can build: the backend consumes prebuilt wheels + the prebuilt
python.org runtime and drives Gradle/SDK/NDK, all cross-platform.

The load model this backend generates was proven on-device before any of this
code was written — see docs/design/dev/android-loadmodel-findings.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..base import Platform

if TYPE_CHECKING:
    from kivyforge.doctor.result import CheckResult


class AndroidBuildError(Exception):
    """An Android build/stage failure surfaced with an actionable message."""


class AndroidPlatform(Platform):
    name = "android"
    aliases = ()
    # Cross-compiled target: never a host default (resolution-chain step 3).
    host_system = None
    # apk = sideload/CI unit (default); aab = Play upload unit.
    package_formats = ("apk", "aab")

    def check_host_capability(self, *, host_system: str | None = None) -> None:
        # Windows, macOS, and Linux hosts can all build for Android: kivyforge
        # consumes prebuilt wheels + the prebuilt python.org runtime and drives
        # Gradle + the Android SDK/NDK, which are cross-platform (android/06
        # §host support). Host *adequacy* (JDK, SDK, NDK present) is doctor's
        # job, not a capability gate.
        return

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
        # `target` carries iOS-only selectors; Android uses --arch for the ABI
        # restriction and the shared --debug arrives via export_method slot? No:
        # build --debug is CLI-level; the base signature has no debug flag, so
        # the Android CLI maps `target == "debug"` from the shared verb once
        # Phase 5 wires `run`. For now: generate-only (android/06 `build`).
        self.reject_ios_only_target(target)
        from .cli import android_build

        android_build(
            project_root,
            debug=False,
            abi=arch,
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
        from .cli import android_run

        android_run(
            project_root,
            no_build=no_build,
            abi=arch,
            serial=destination,
        )

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
        from .cli import android_package

        android_package(
            project_root,
            fmt=fmt,
            arch=arch,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )

    def status(self, project_root: Path) -> None:
        from .cli import android_status

        android_status(project_root)

    def open_project(self, project_root: Path) -> None:
        from .cli import android_open

        android_open(project_root)

    def doctor(
        self, cwd: Path, *, kivyforge_version: str, offline: bool
    ) -> list[CheckResult]:
        from .doctor import android_doctor

        return android_doctor(cwd, kivyforge_version=kivyforge_version, offline=offline)
