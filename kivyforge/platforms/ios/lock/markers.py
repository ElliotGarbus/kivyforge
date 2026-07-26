"""The PEP 508 marker environment of the *target*, not the lock host (spec 02).

pip's ``--platform`` decides which wheel *tags* are acceptable. It does **not**
change how environment markers are evaluated: pip evaluates every
``; sys_platform == "darwin"``-style marker against the interpreter running
pip. Because iOS is always cross-resolved from macOS, that silently answers
every marker as **macOS** — so a dependency gated on ``sys_platform ==
"darwin"`` is wrongly pulled into an iOS lock, and one gated on
``sys_platform == "ios"`` is wrongly dropped.

That second case is the dangerous one: nothing fails at lock time, and the app
is simply missing a dependency at runtime. Unlike the Android equivalent (where
a Windows host produced a loud "no matching distribution" error), this failure
is silent on the only supported host, so restricting the workflow to macOS does
not fix it — the environment has to be described explicitly.

Values follow CPython's own iOS build (PEP 730): ``sys.platform`` is ``"ios"``
and ``platform.system()`` is ``"iOS"`` on both device and simulator. Markers
carry no device/simulator distinction — that lives in
``sys.implementation._multiarch``, which is not a marker name — so the two are
told apart here only by ``platform_machine``.
"""

from __future__ import annotations


class MarkerEnvironmentError(Exception):
    """The target marker environment could not be described."""


def machine_for_slice(slice_suffix: str) -> str:
    """``arm64_iphoneos`` -> ``arm64``; ``x86_64_iphonesimulator`` -> ``x86_64``."""
    if slice_suffix.endswith("_iphoneos"):
        return slice_suffix[: -len("_iphoneos")]
    if slice_suffix.endswith("_iphonesimulator"):
        return slice_suffix[: -len("_iphonesimulator")]
    raise MarkerEnvironmentError(
        f"unrecognised iOS slice {slice_suffix!r}; expected an "
        "``<arch>_iphoneos`` or ``<arch>_iphonesimulator`` suffix."
    )


def ios_marker_environment(*, python_version: str, slice_suffix: str) -> dict[str, str]:
    """The PEP 508 environment a wheel would see on the given iOS slice.

    ``python_version`` is the full runtime version (e.g. ``3.14.6``).
    """
    machine = machine_for_slice(slice_suffix)
    parts = python_version.split(".")
    if len(parts) < 2:
        raise MarkerEnvironmentError(
            f"python version {python_version!r} is not a full X.Y.Z version; "
            "cannot describe the target marker environment."
        )
    return {
        "implementation_name": "cpython",
        "implementation_version": python_version,
        "os_name": "posix",
        "platform_machine": machine,
        "platform_python_implementation": "CPython",
        # Device kernel details are unknowable at lock time, and no sane wheel
        # gates on them.
        "platform_release": "",
        "platform_system": "iOS",
        "platform_version": "",
        "python_full_version": python_version,
        "python_version": ".".join(parts[:2]),
        "sys_platform": "ios",
    }
