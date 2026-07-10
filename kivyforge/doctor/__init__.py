"""Health checks for ``kivyforge doctor`` (spec 05).

Checks are pure functions over an injectable :class:`Probe`, so every
PASS/WARN/FAIL/SKIP path is unit-testable without Xcode, a network, or a
keychain. ``cli/doctor.py`` wires the real probe and renders the report.
"""

from __future__ import annotations

from .probe import Probe, RealProbe
from .result import CheckResult, Status, worst_status

__all__ = [
    "Probe",
    "RealProbe",
    "CheckResult",
    "Status",
    "worst_status",
]
