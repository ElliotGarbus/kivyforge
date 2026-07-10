"""Linux platform backend.

Produces a self-contained AppDir and, by default, an AppImage (linux-spec).
Linux is the host default on Linux, so a Linux box with ``[tool.kivy.linux]``
configured resolves to this backend without ``-p``. It requires a Linux host:
the bundled python-build-standalone runtime is a gnu/glibc ELF build.
"""

from __future__ import annotations

import platform as _platform

from ..base import HostCapabilityError, Platform


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
