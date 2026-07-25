"""The PEP 508 marker environment of the *target*, not the lock host (android/02).

pip's ``--platform`` / ``--abi`` / ``--python-version`` decide which wheel
*tags* are acceptable. They do **not** change how environment markers are
evaluated: pip evaluates every ``; sys_platform == "win32"``-style marker
against the interpreter running pip. Cross-resolving therefore inherits the
host's identity, and the same ``kivyforge lock -p android`` produces different
locks — or fails outright — depending on the machine that ran it.

The concrete failure that motivated this: Kivy declares

    kivy-deps.angle~=0.4.0; sys_platform == "win32"

so locking for Android **on Windows** kept that requirement, looked for an
``android_24_arm64_v8a`` wheel of a Windows-only ANGLE build, and failed. The
same lock succeeded on Linux. A lock file that depends on who ran it is not a
lock file, so kivyforge supplies the environment explicitly instead.

Values follow CPython's own Android build: ``sys.platform`` is ``"android"``
(CPython 3.13+, PEP 738) and ``platform.system()`` is ``"Android"``.
``platform_release`` / ``platform_version`` are left empty on purpose — they
describe the device kernel, which is unknowable at lock time and which no
sane wheel should gate on.
"""

from __future__ import annotations

# Android ABI -> the machine name CPython reports there (``platform.machine()``).
ANDROID_ABI_MACHINE = {
    "arm64_v8a": "aarch64",
    "armeabi_v7a": "armv7l",
    "x86_64": "x86_64",
    "x86": "i686",
}


class MarkerEnvironmentError(Exception):
    """The target marker environment could not be described."""


def android_marker_environment(*, python_version: str, abi: str) -> dict[str, str]:
    """The PEP 508 environment a wheel would see on ``abi`` running Android.

    ``python_version`` is the full runtime version (e.g. ``3.14.6``).
    """
    machine = ANDROID_ABI_MACHINE.get(abi)
    if machine is None:
        raise MarkerEnvironmentError(
            f"unknown Android ABI {abi!r}; cannot describe its marker "
            f"environment (known: {', '.join(sorted(ANDROID_ABI_MACHINE))})."
        )
    parts = python_version.split(".")
    if len(parts) < 2:
        raise MarkerEnvironmentError(
            f"python version {python_version!r} is not a full X.Y.Z version; "
            "cannot describe the target marker environment."
        )
    short = ".".join(parts[:2])
    return {
        "implementation_name": "cpython",
        "implementation_version": python_version,
        "os_name": "posix",
        "platform_machine": machine,
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Android",
        "platform_version": "",
        "python_full_version": python_version,
        "python_version": short,
        "sys_platform": "android",
    }
