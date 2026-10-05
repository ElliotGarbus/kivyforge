"""Install the pinned NDK and CMake before Gradle would, visibly (issue #74).

AGP downloads a missing NDK or CMake itself, during the build, and says nothing
while it does: the NDK is a download of several hundred MB. So before Gradle
runs, kivyforge checks for the versions it pins and, when one is missing,
installs it with the SDK's own ``sdkmanager`` and shows the progress.

This is a convenience, never a gate. Without ``sdkmanager``, or when it does not
install the package (an unaccepted license makes it print the license and exit
0), the build says so and carries on: Gradle then installs it the old way.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .streaming import elapsed, run_streaming
from .toolchain import CMAKE_VERSION, NDK_VERSION

_BAT = ".bat" if os.name == "nt" else ""
# sdkmanager redraws "[=====     ] 42% Downloading android-ndk-....zip" with \r.
_BAR = re.compile(r"^\[[= ]*\]\s*(\d+)%")


@dataclass(frozen=True)
class SdkPackage:
    label: str
    package_id: str  # sdkmanager's id
    installed_dir: str  # relative to the SDK root


PINNED = (
    SdkPackage(f"NDK {NDK_VERSION}", f"ndk;{NDK_VERSION}", f"ndk/{NDK_VERSION}"),
    SdkPackage(
        f"CMake {CMAKE_VERSION}", f"cmake;{CMAKE_VERSION}", f"cmake/{CMAKE_VERSION}"
    ),
)


def sdkmanager_path(sdk: Path) -> Path | None:
    path = sdk / "cmdline-tools" / "latest" / "bin" / f"sdkmanager{_BAT}"
    return path if path.is_file() else None


def ensure_sdk_packages(
    sdk: Path | None,
    *,
    on_progress: Callable[[str], None],
    on_transfer: Callable[[str, int, int, str], None] | None = None,
) -> None:
    """Install whichever pinned SDK packages are missing, reporting progress."""
    if sdk is None:
        return  # doctor reports a missing SDK; Gradle will fail with its own error
    missing = [p for p in PINNED if not (sdk / p.installed_dir).is_dir()]
    if not missing:
        return
    tool = sdkmanager_path(sdk)
    for package in missing:
        if tool is None:
            on_progress(
                f"[sdk] {package.label} is not installed; Gradle will download "
                "and install it during this build. That is a large download and "
                "Gradle shows no progress for it. (Installing the Android SDK "
                "command-line tools lets kivyforge show it.)"
            )
            continue
        _install(tool, sdk, package, on_progress=on_progress, on_transfer=on_transfer)


def _install(
    tool: Path,
    sdk: Path,
    package: SdkPackage,
    *,
    on_progress: Callable[[str], None],
    on_transfer: Callable[[str, int, int, str], None] | None,
) -> None:
    label = f"[sdk] {package.label}"
    on_progress(f"{label}: not installed; installing it with sdkmanager")

    def on_segment(segment: str) -> bool:
        bar = _BAR.match(segment.strip())
        if bar is None or on_transfer is None:
            return False
        on_transfer(label, int(bar.group(1)), 100, "percent")
        return True

    def on_quiet(seconds: float) -> None:
        on_progress(f"{label}: still installing ({elapsed(seconds)})")

    try:
        returncode, transcript = run_streaming(
            [str(tool), f"--sdk_root={sdk}", package.package_id],
            on_segment=on_segment,
            on_quiet=on_quiet,
        )
    except OSError as exc:
        on_progress(
            f"{label}: could not run sdkmanager ({exc}); Gradle will install it."
        )
        return
    if (sdk / package.installed_dir).is_dir():
        on_progress(f"{label}: installed")
        return
    # Exit status is no help: an unaccepted license prints the license text and
    # exits 0 without installing anything.
    reason = (
        "its license has not been accepted (run `sdkmanager --licenses`)"
        if "License" in transcript
        else f"sdkmanager exited {returncode}"
    )
    on_progress(f"{label}: not installed, {reason}; Gradle will try instead.")
