"""Release manifest-policy preflight (android/04 §release policy, android/06).

Raw XML + attribute passthrough make it possible to ship a footgun (an
accidentally-exported component, a debuggable/cleartext release, the
``org.example.*`` placeholder). ``kivyforge package`` lints the *generated*
manifest and **fails before signing** on a violation.

Scope note (android/06): a full release lint delegates the well-covered checks
to a curated Android ``lintRelease`` subset. This module hand-rolls the checks
Lint misses or that are kivyforge-specific, run against the manifest kivyforge
itself generated (a superset preflight; Gradle's own lint still runs in the
release build). Findings are (severity, message); any FAIL aborts.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

ANDROID_NS = "http://schemas.android.com/apk/res/android"
_NS = f"{{{ANDROID_NS}}}"
BOOTSTRAP_EXPORTED = {"org.kivy.android.PythonActivity"}


@dataclass(frozen=True)
class PolicyFinding:
    severity: str  # "FAIL" | "INFO"
    message: str


class ManifestPolicyError(Exception):
    def __init__(self, fails: list[PolicyFinding]):
        self.fails = fails
        joined = "\n".join(f"    • {f.message}" for f in fails)
        super().__init__(
            "release manifest policy check failed (blocked before signing):\n"
            f"{joined}\n"
            "  Fix these through the manifest escape hatches "
            "(passthrough / raw XML), never by editing the generated file "
            "(android/04 §release policy)."
        )


# Dangerous runtime permissions worth an INFO reminder (need a runtime request).
_DANGEROUS = {
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.READ_CONTACTS",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.READ_PHONE_STATE",
}


def check_release_manifest(manifest_xml: str, *, package: str) -> list[PolicyFinding]:
    """Return all findings; the caller raises on any FAIL. INFO is advisory."""
    findings: list[PolicyFinding] = []
    root = ET.fromstring(manifest_xml)
    app = root.find("application")

    # 1. applicationId must not be the init placeholder.
    if package.startswith("org.example."):
        findings.append(
            PolicyFinding(
                "FAIL",
                f"applicationId {package!r} is the init placeholder "
                "(org.example.*); set a real package before release.",
            )
        )

    # 2. debuggable must not be forced true.
    if app is not None and app.get(f"{_NS}debuggable") == "true":
        findings.append(
            PolicyFinding(
                "FAIL", "android:debuggable is forced true in a release build."
            )
        )

    # 3. Exactly one LAUNCHER activity, and it is the bootstrap's.
    launchers = []
    for activity in root.iter("activity"):
        for category in activity.iter("category"):
            if category.get(f"{_NS}name") == "android.intent.category.LAUNCHER":
                launchers.append(activity.get(f"{_NS}name"))
    if len(launchers) != 1:
        findings.append(
            PolicyFinding(
                "FAIL",
                f"expected exactly one LAUNCHER activity, found {len(launchers)}: "
                f"{launchers}.",
            )
        )

    # 4. Every intent-filtered component sets exported explicitly, and only the
    #    bootstrap components are exported.
    for kind in ("activity", "service", "receiver", "provider"):
        for comp in root.iter(kind):
            name = comp.get(f"{_NS}name")
            has_filter = comp.find("intent-filter") is not None
            exported = comp.get(f"{_NS}exported")
            if has_filter and exported is None:
                findings.append(
                    PolicyFinding(
                        "FAIL",
                        f"{kind} {name!r} has an intent-filter but no explicit "
                        "android:exported.",
                    )
                )
            if exported == "true" and name not in BOOTSTRAP_EXPORTED:
                findings.append(
                    PolicyFinding(
                        "FAIL",
                        f"{kind} {name!r} is exported; only the bootstrap "
                        f"components {sorted(BOOTSTRAP_EXPORTED)} may be "
                        "exported.",
                    )
                )

    # 5. No conflicting deep-link <data> (same scheme+host on two filters).
    seen_data: set[tuple[str, str]] = set()
    for data in root.iter("data"):
        key = (data.get(f"{_NS}scheme", ""), data.get(f"{_NS}host", ""))
        if key != ("", "") and key in seen_data:
            findings.append(
                PolicyFinding(
                    "FAIL",
                    f"conflicting deep-link <data> scheme/host {key} appears on "
                    "more than one intent-filter.",
                )
            )
        seen_data.add(key)

    # 6. Cleartext posture (INFO if explicitly enabled).
    if app is not None and app.get(f"{_NS}usesCleartextTraffic") == "true":
        findings.append(
            PolicyFinding(
                "INFO",
                "android:usesCleartextTraffic is true — the release permits "
                "cleartext HTTP.",
            )
        )

    # 7. Dangerous runtime permissions (INFO reminder).
    for perm in root.iter("uses-permission"):
        name = perm.get(f"{_NS}name")
        if name in _DANGEROUS:
            findings.append(
                PolicyFinding(
                    "INFO",
                    f"{name} is a dangerous runtime permission; it needs a "
                    "runtime request (not just the manifest entry).",
                )
            )

    return findings


def enforce_release_manifest(manifest_xml: str, *, package: str) -> list[PolicyFinding]:
    """Raise ``ManifestPolicyError`` on any FAIL; return the INFO findings."""
    findings = check_release_manifest(manifest_xml, package=package)
    fails = [f for f in findings if f.severity == "FAIL"]
    if fails:
        raise ManifestPolicyError(fails)
    return [f for f in findings if f.severity == "INFO"]
