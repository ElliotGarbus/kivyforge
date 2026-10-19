"""The ``lock_inputs_sha256`` a lock records for a ``pyproject.toml`` text.

For tests that write a lock by hand instead of resolving one, and need it to
read as in sync with their project (``kivyforge.lock.inputs``).
"""

from __future__ import annotations

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.inputs import lock_inputs_sha256

#: A hash no projection produces: a lock that is out of date.
STALE = "0" * 64


def inputs_sha(text: str, platform: str) -> str:
    config = load_config_from_text(
        text,
        require_ios=platform == "ios",
        require_macos=platform == "macos",
        require_linux=platform == "linux",
        require_windows=platform == "windows",
        require_android=platform == "android",
    )
    return lock_inputs_sha256(config, platform)
