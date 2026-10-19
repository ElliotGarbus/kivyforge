"""The ``LockError`` type every lock reader raises.

Drift detection lives in ``kivyforge.lock.inputs``. The iOS ``pylock.ios.toml``
parser lives in ``kivyforge.platforms.ios.lock.reader``; the wheel+runtime
parser lives in ``kivyforge.lock.wheelruntime.serialize``.
"""

from __future__ import annotations


class LockError(Exception):
    """A malformed or unreadable lockfile."""
