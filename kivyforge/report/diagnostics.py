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

#: A lock that matches ``pyproject.toml`` but lacks something the build needs,
#: because it predates kivyforge supplying it (for example the ``pyjnius`` an
#: Android lock now always carries). Not drift -- ``pyproject.toml`` did not
#: move -- but the same remedy: re-lock.
LOCK_INCOMPLETE = "KF-LOCK-INCOMPLETE"

#: ``lock`` re-resolved with the existing lock's versions as preferences, and
#: pip could not keep them with the changed inputs, though it can resolve
#: without them. Not drift: ``lock --update`` (newest of everything) is the fix,
#: and a plain re-lock would only fail the same way.
LOCK_PINS_CONFLICT = "KF-LOCK-PINS-CONFLICT"

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

#: A Windows onedir bundle nests so deep that it only works from a short
#: folder when long paths are off (the Windows default). WARNING: the
#: artifact is fine; where the user puts it is the constraint.
PATH_DEPTH = "KF-PATH-DEPTH"

#: The Android release-manifest policy passed with an informational finding.
MANIFEST_POLICY = "KF-MANIFEST-POLICY"

#: Retired: no longer emitted. It warned that a profile pinned under iOS
#: auto-signing lacked declared entitlements, but Xcode refuses any pin under
#: auto-signing, so the build now fails instead. Never reuse this code.
ENTITLEMENTS_UNGRANTED = "KF-ENTITLEMENTS-UNGRANTED"

#: A build tool (Gradle, xcodebuild, appimagetool) ran and exited non-zero.
#: One code for every tool; ``context`` names the ``tool`` and ``task``.
BUILD_TOOL_FAILED = "KF-BUILD-TOOL-FAILED"

#: A build tool reported success but the product is not where it should be.
ARTIFACT_MISSING = "KF-ARTIFACT-MISSING"

#: A required tool is not installed: spawning it raised ``FileNotFoundError``,
#: or a pre-flight found it absent (Android: no ``java``, or a JRE's missing
#: ``javac``). ``context`` names the ``tool``.
TOOLCHAIN_MISSING = "KF-TOOLCHAIN-MISSING"

#: A tool is present but could not be executed (``EACCES``, ``ENOEXEC``, ...).
#: Kept apart from MISSING because the fix is the file, not an install;
#: ``context`` carries ``tool`` and ``errno``.
TOOLCHAIN_UNUSABLE = "KF-TOOLCHAIN-UNUSABLE"

#: An installed dependency sits outside the specifier ``pyproject.toml``
#: declares. ``init`` reports it; nothing is modified, so the run stays ``ok``.
DEPENDENCY_DRIFT = "KF-DEPENDENCY-DRIFT"

#: ``open`` found no IDE launcher on PATH. The project exists and can be opened
#: by hand, so the run stays ``ok``; this is what says it was not launched.
IDE_NOT_FOUND = "KF-IDE-NOT-FOUND"

#: This host cannot build this target at all (e.g. iOS from Windows).
HOST_INCAPABLE = "KF-HOST-INCAPABLE"

#: iOS: the project would run Kivy 2.x there. kivyforge builds Kivy 3 only on
#: iOS; the mobile wheel index serves no Kivy 2.x iOS wheel, and kivy-ios is
#: the tool that serves Kivy 2.x. ``lock`` catches a ``kivy`` requirement that
#: admits no 3.x release before resolving, and a resolved ``kivy`` below
#: ``3.0.0.dev0`` after; ``build`` applies the second check to the lock it
#: reads. Exit 1. ``context`` names the ``requirement`` or the ``version``.
IOS_KIVY_UNSUPPORTED = "KF-IOS-KIVY-UNSUPPORTED"

#: iOS: a ``.py`` file under ``app_dir`` imports the kivy-ios ``ios`` module,
#: which kivyforge does not provide (Kivy 3 and the standard library replace
#: it). WARNING: the import may be guarded, so the build goes on and the run is
#: ``ok``. Quiet when ``app_dir`` has its own ``ios.py`` or ``ios/``.
#: ``build`` and ``doctor`` report it. ``context`` names the first ``file``, its
#: ``line``, and how many ``files`` import it.
IOS_LEGACY_IOS_MODULE = "KF-IOS-LEGACY-IOS-MODULE"

#: Android: a dependency provides a top-level ``android`` module, which would
#: be shadowed by the ``android`` package kivyforge bundles. ``lock`` catches a
#: distribution named ``android``; ``build`` catches any wheel that installs
#: one. ``context`` names the ``distribution``.
ANDROID_DEPENDENCY_CONFLICT = "KF-ANDROID-DEPENDENCY-CONFLICT"

#: Android: ``app_dir`` has its own ``android.py`` or ``android/``, which the
#: bundled package would shadow. ``context`` names the ``path``.
ANDROID_APP_CONFLICT = "KF-ANDROID-APP-CONFLICT"

#: Android: an ``include_files`` file replaced one kivyforge generates (a
#: resource such as ``res/values/styles.xml`` or the launcher icon). INFO: the
#: override is usually deliberate, and the build goes on. ``context`` names
#: the ``path`` in the generated project.
ANDROID_INCLUDE_OVERRIDE = "KF-ANDROID-INCLUDE-OVERRIDE"

#: Android: the APK or AAB Gradle built holds a native library with a loadable
#: segment whose file offset and address disagree modulo its alignment, so the
#: device cannot load it. Seen when AGP's strip damages a library patchelf
#: edited. ``context`` names the first ``library`` (its path in the archive).
ANDROID_NATIVE_LIB_MISALIGNED = "KF-ANDROID-NATIVE-LIB-MISALIGNED"

#: Android: a locked wheel ships its native libraries in a layout kivyforge
#: does not stage -- Chaquopy's separate library wheels (``opt/lib``), as
#: Flet's index serves them. ``context`` names the ``distributions``
#: (comma-separated) and the ``layout``.
ANDROID_WHEEL_LAYOUT = "KF-ANDROID-WHEEL-LAYOUT"

#: Android: a native library in a locked wheel (or the runtime) is built for
#: another architecture than the ABI the wheel's tag routed it to. ``context``
#: names the ``library``, its ``distribution`` and the ``abi``.
ANDROID_WHEEL_ARCH = "KF-ANDROID-WHEEL-ARCH"

#: Android: an extension module in a locked wheel is named with a suffix CPython
#: on Android does not import (a build host's, or another Python version's).
#: ``context`` names the ``library``, its ``distribution`` and the ``abi``.
ANDROID_WHEEL_SUFFIX = "KF-ANDROID-WHEEL-SUFFIX"

#: A dynamic ``[project].version`` could not be resolved: pip exited non-zero
#: preparing the project's metadata, or reported no version. One code for
#: "unreachable index" and "not a git checkout" alike, because only pip's
#: wording tells them apart and that is not a contract; the remediation names
#: both. Exit 1. ``context`` names the ``backend`` and whether the run was
#: ``isolated``.
VERSION_UNRESOLVED = "KF-VERSION-UNRESOLVED"

#: The version is not one to three dot-separated integers, which App Store
#: Connect refuses at upload (ITMS-90060). An error, before any build tool
#: runs, for an iOS ``app-store`` export; a warning for other iOS exports and
#: macOS ``package``. ``context`` names the ``version`` and ``export_method``.
VERSION_APPLE_FORMAT = "KF-VERSION-APPLE-FORMAT"

#: ``[tool.setuptools_scm].version_file`` is configured but the version came
#: from ``--app-version`` or a static declaration, so the build backend did not
#: rewrite the file and an app reading it may report another version. WARNING.
#: ``context`` names the ``path``.
VERSION_FILE_NOT_REFRESHED = "KF-VERSION-FILE-NOT-REFRESHED"

#: ``--no-build-isolation`` had no effect: the version is static, so pip was
#: not run. INFO.
VERSION_ISOLATION_UNUSED = "KF-VERSION-ISOLATION-UNUSED"

#: A setuptools project declares entry points in ``setup.cfg`` or ``setup.py``
#: and none in ``[project]``. kivyforge writes the app's package metadata from
#: ``[project]``, so the app would start without them; the spec lets no backend
#: add them either, and setuptools has deprecated doing so. Exit 1. ``context``
#: names the ``path`` (``setup.cfg`` or ``setup.py``).
METADATA_ENTRY_POINTS_OUTSIDE_PROJECT = "KF-METADATA-ENTRY-POINTS-OUTSIDE-PROJECT"

#: ``[project].dynamic`` lists ``entry-points``, ``scripts`` or
#: ``gui-scripts``, so only the build backend knows the app's entry points and
#: kivyforge generates no package metadata for it. WARNING. ``context``:
#: ``reason`` is ``dynamic`` or ``static-and-dynamic``; ``fallback`` is the
#: development egg-info that ships instead, or ``none``.
METADATA_NOT_GENERATED = "KF-METADATA-NOT-GENERATED"

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
