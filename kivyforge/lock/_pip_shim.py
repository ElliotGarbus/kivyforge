"""Run pip with the *target's* PEP 508 marker environment.

kivyforge invokes this instead of ``-m pip`` when cross-resolving. It replaces
``packaging.markers.default_environment`` — the single function every
``Marker.evaluate()`` consults — with the target environment supplied as JSON in
``KIVYFORGE_TARGET_MARKER_ENV``, then hands control to pip unchanged.

pip still performs the whole resolution, including backtracking and platform
wheel-tag expansion; only its answer to "what platform am I resolving for?"
changes. kivyforge deliberately does not reimplement any of that.

Platform-neutral by design: each backend describes its own target
(``platforms/android/lock/markers.py``, ``platforms/ios/lock/markers.py``).

This is a documented dependency on a pip internal, so it fails loudly rather
than silently falling back to host markers: a quiet fallback would reintroduce
exactly the host-dependent lock this exists to prevent.
"""

from __future__ import annotations

import json
import os
import sys

MARKER_ENV_VAR = "KIVYFORGE_TARGET_MARKER_ENV"


def main(argv: list[str]) -> int:
    raw = os.environ.get(MARKER_ENV_VAR)
    if not raw:
        sys.stderr.write(
            f"{MARKER_ENV_VAR} is not set; refusing to resolve with the "
            "host's marker environment.\n"
        )
        return 2
    environment = json.loads(raw)

    try:
        from pip._vendor.packaging import markers
    except ImportError:
        sys.stderr.write(
            "this pip does not vendor packaging.markers where kivyforge "
            "expects it, so environment markers cannot be evaluated for the "
            "target platform. Please report the pip version.\n"
        )
        return 3
    if not hasattr(markers, "default_environment"):
        sys.stderr.write(
            "pip's vendored packaging has no default_environment(); kivyforge "
            "cannot retarget marker evaluation. Please report the pip version.\n"
        )
        return 3

    markers.default_environment = lambda: dict(environment)

    from pip._internal.cli.main import main as pip_main

    return pip_main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
