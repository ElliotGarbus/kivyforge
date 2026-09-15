"""Check result types for doctor."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


# Severity ordering for computing the overall worst status.
_ORDER = {Status.PASS: 0, Status.SKIP: 0, Status.WARN: 1, Status.FAIL: 2}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str = ""
    hint: str = ""
    #: Stable diagnostic code from ``kivyforge.report.diagnostics``, for checks
    #: whose meaning is worth an agent branching on. Optional because assigning
    #: one to every check at once would be churn for no gain: an uncoded check
    #: still reaches ``--json`` in ``data.checks`` with its name, status, detail
    #: and hint, and only its ``diagnostics`` entry is generic. Add a code when
    #: a check turns out to be one callers actually react to.
    code: str = ""

    def render(self) -> str:
        line = f"[{self.status.value}] {self.name}"
        if self.detail:
            line += f": {self.detail}"
        if self.hint and self.status in (Status.WARN, Status.FAIL):
            line += f"\n       hint: {self.hint}"
        return line

    def as_dict(self) -> dict[str, object]:
        """The check as ``--json`` reports it under ``data.checks``.

        ``name``, ``status`` and ``detail`` are always present so a consumer can
        index by name without shape checks; ``hint`` and ``code`` are omitted
        when empty rather than emitted as ``""``.

        Note ``hint`` is included here regardless of status, unlike
        :meth:`render`, which shows it only for WARN and FAIL. Hiding it is a
        presentation choice that keeps a passing human report terse; a machine
        consumer has no such problem and may well want it.
        """
        payload: dict[str, object] = {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }
        if self.hint:
            payload["hint"] = self.hint
        if self.code:
            payload["code"] = self.code
        return payload


def worst_status(results: list[CheckResult]) -> Status:
    worst = Status.PASS
    for r in results:
        if _ORDER[r.status] > _ORDER[worst]:
            worst = r.status
    return worst
