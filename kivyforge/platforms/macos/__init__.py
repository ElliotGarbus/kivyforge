"""macOS platform backend.

Produces a self-contained ``.app`` bundle (macos-spec). macOS is the host
default on Darwin, so a Mac with ``[tool.kivy.macos]`` configured resolves to
this backend without ``-p``. It requires a macOS host (``codesign``/``lipo``
from the Xcode command-line tools); the full Xcode IDE is not needed.
"""

from __future__ import annotations

import platform as _platform

from ..base import HostCapabilityError, Platform


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
