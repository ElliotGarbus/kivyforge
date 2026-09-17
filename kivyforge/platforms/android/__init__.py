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

from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.failures import ClassifiedError

from ..base import Platform

if TYPE_CHECKING:
    from kivyforge.build_outcome import BuildEvents, BuildOutcome
    from kivyforge.doctor.result import CheckResult
    from kivyforge.status import StatusReport


class AndroidBuildError(ClassifiedError):
    """An Android build/stage failure surfaced with an actionable message.

    The base is the unclassified case (``KF-ERROR``, exit 1). Each failure family
    below is a subclass that fixes its own code and exit status, so a raise site
    classifies a failure by choosing the class -- and one that picks the base
    degrades to the old behaviour rather than to a wrong code.
    """


class GradleFailed(AndroidBuildError):
    """Gradle ran and exited non-zero; its output is already on stderr."""

    code = diagnostics.BUILD_TOOL_FAILED
    exit_code = exit_codes.BUILD_FAILURE


class ArtifactMissing(AndroidBuildError):
    """Gradle reported success but did not leave the file we expected."""

    code = diagnostics.ARTIFACT_MISSING
    exit_code = exit_codes.BUILD_FAILURE


class LockMissing(AndroidBuildError):
    code = diagnostics.LOCK_MISSING
    exit_code = exit_codes.LOCK_DRIFT


class LockUnreadable(AndroidBuildError):
    code = diagnostics.LOCK_UNREADABLE
    exit_code = exit_codes.LOCK_DRIFT


class LockDrift(AndroidBuildError):
    """``pyproject.toml`` or a pinned ``include_files`` entry moved since locking."""

    code = diagnostics.LOCK_DRIFT
    exit_code = exit_codes.LOCK_DRIFT


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
        # `target` carries the iOS-only selectors. Without --debug, build stops
        # after generating the project; with it, Gradle assembles the debug
        # artifact (android/06 step 8). `--abi` is the Android spelling of the
        # ABI restriction; `--arch` is accepted for it too.
        self.reject_ios_only_target(target)
        from .cli import android_build

        return android_build(
            project_root,
            events=events,
            debug=debug,
            fmt=fmt or "apk",
            abi=abi or arch,
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
        from .cli import android_package

        return android_package(
            project_root,
            events=events,
            fmt=fmt,
            abi=abi or arch,
            keystore=keystore,
            key_alias=key_alias,
            no_verify_lock=no_verify_lock,
            no_cache=no_cache,
        )

    def status(self, project_root: Path) -> StatusReport:
        from .cli import android_status

        return android_status(project_root)

    def open_project(self, project_root: Path, *, events: BuildEvents) -> Path:
        from .cli import android_open

        return android_open(project_root, events=events)

    def doctor(
        self, cwd: Path, *, kivyforge_version: str, offline: bool
    ) -> list[CheckResult]:
        from .doctor import android_doctor

        return android_doctor(cwd, kivyforge_version=kivyforge_version, offline=offline)
