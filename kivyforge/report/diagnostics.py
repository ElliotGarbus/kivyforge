"""Structured diagnostics with stable codes (roadmap item 3, points 3 and 5).

Failures are prose today, and prose is the one thing an agent cannot branch on:
rewording a message for clarity silently breaks every caller that matched it.
A code is a promise that the *meaning* is addressable even when the wording
improves.

Two conventions worth keeping:

* **The code is the contract, the message is not.** Reword freely; changing or
  reusing a code is a breaking change.
* **Remediation is a field, not a sentence.** The backends already end
  user-facing failures with an explicit ``Fix:`` line (established in roadmap
  item 1). That convention is good and it should not have to be recovered by
  string-splitting, so it is carried as :attr:`Diagnostic.remediation`.

The scheme deliberately mirrors ``native_integration``'s (``ni.req.N``,
``ni.decl.*``, ``ni.adv.S*``) in spirit, so adopting the discipline now
pre-pays roadmap item 8 rather than inventing a second vocabulary later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Severities ------------------------------------------------------------
# Deliberately three, matching what doctor already distinguishes. SKIP/PASS
# produce no diagnostic at all: a diagnostics list that includes successes is
# one every consumer has to filter.
ERROR = "error"
WARNING = "warning"
INFO = "info"

# --- Codes -----------------------------------------------------------------
# Named here so they cannot drift between raise sites, and so the full
# vocabulary is greppable in one place.

#: A committed lock no longer matches ``pyproject.toml``.
LOCK_DRIFT = "KF-LOCK-DRIFT"

#: No ``pylock.<platform>.toml`` at all.
LOCK_MISSING = "KF-LOCK-MISSING"

#: A lock exists but could not be parsed. Same remediation as the two above,
#: kept distinct because a corrupt lock is worth noticing rather than quietly
#: treating as stale -- it usually means a bad merge or a truncated write.
LOCK_UNREADABLE = "KF-LOCK-UNREADABLE"

#: Resolution succeeded but made a judgement call worth surfacing (e.g. the
#: macOS/Linux backends accepting a vendored plain ``linux_*`` wheel). Always
#: WARNING: the lock written is usable, and the run is ``ok``.
LOCK_WARNING = "KF-LOCK-WARNING"

#: ``byte_compile`` is on but no compatible host interpreter was found. The bug
#: roadmap item 1 fixed; the check that now catches it lives in
#: ``doctor/checks_common.py``.
BYTECOMPILE_NO_INTERP = "KF-BYTECOMPILE-NO-INTERP"

#: A package shipped unsigned or ad-hoc signed where real signing is
#: configurable. WARNING: the artifact is usable, just not trusted.
SIGNING_UNCONFIGURED = "KF-SIGNING-UNCONFIGURED"

#: The Android release-manifest policy passed with an informational finding.
MANIFEST_POLICY = "KF-MANIFEST-POLICY"

#: iOS auto-signing: the pinned profile does not grant entitlements the app
#: declares. WARNING, because Xcode may register them during the build.
ENTITLEMENTS_UNGRANTED = "KF-ENTITLEMENTS-UNGRANTED"

#: This host cannot build this target at all (e.g. iOS from Windows).
HOST_INCAPABLE = "KF-HOST-INCAPABLE"

#: An expected failure (``ToolchainError``) with no specific code assigned yet.
#: Branchable rather than null: it tells a consumer "this is a clean, expected
#: failure -- read ``message`` and ``remediation``", as distinct from a crash.
#: Narrowing a raise site to a real code is additive and never breaks anyone.
UNSPECIFIED = "KF-ERROR"

#: A doctor check reported WARN or FAIL and has not been assigned a specific
#: code yet. Branchable on purpose -- it tells a consumer "the detail is in
#: ``data.checks``, keyed by name" rather than leaving a null in the payload.
#: Every check that gains a real code makes this appear less often; it is not
#: expected to reach zero, since one-off checks do not all deserve vocabulary.
DOCTOR_CHECK = "KF-DOCTOR-CHECK"


@dataclass(frozen=True)
class Diagnostic:
    """One machine-addressable thing that went wrong, or nearly did."""

    code: str
    severity: str
    message: str
    remediation: str = ""
    #: Free-form, code-specific context. Kept separate from the top-level
    #: fields so adding context is never a schema change.
    context: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        # Omitted rather than emitted empty: an absent key reads as "nothing to
        # say", where "" invites a consumer to print a blank remediation.
        if self.remediation:
            payload["remediation"] = self.remediation
        if self.context:
            payload["context"] = dict(self.context)
        return payload
