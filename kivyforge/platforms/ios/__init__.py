"""iOS platform backend.

Seam-first: this backend currently carries iOS metadata + host capability. The
iOS build/run/open/package *logic* still lives in ``kivyforge.cli`` and the
iOS-specific ``project``/``xcode`` modules; it moves behind this backend when
macOS becomes the second consumer (extract-by-need).
"""

from __future__ import annotations

import platform as _platform

from ..base import HostCapabilityError, Platform


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
