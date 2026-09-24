"""Shared test fixtures.

iOS is a cross-compiled target with no host default, so every platform-aware
verb needs an explicit target (``-p ios`` or ``KIVYFORGE_PLATFORM``). The iOS
test suite predates the resolution chain and invokes verbs without a flag, so we
default the session platform to ``ios`` for all tests. Tests that exercise the
resolution chain itself override or clear this explicitly.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest


def _detect_symlink_support() -> bool:
    """Whether this host can create symlinks without elevated privilege.

    True on POSIX; on Windows only when Developer Mode or admin rights grant the
    symlink privilege. Tests that create symlinks (or exercise code that does,
    e.g. the iOS ``<app>-ios/app`` staging symlink) are skipped when this is
    False so the suite stays green on a stock Windows host.
    """
    try:
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "target")
            open(target, "w").close()
            os.symlink(target, os.path.join(d, "link"))
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


SYMLINKS_SUPPORTED = _detect_symlink_support()

TOOLCHAIN_REQUIRED = bool(os.environ.get("KIVYFORGE_REQUIRE_TOOLCHAIN"))


def skip_missing_toolchain(tool: str, detail: str = "") -> None:
    """Skip because *tool* is absent — or fail, when the job promised to have it.

    Same reasoning as ``KIVYFORGE_REQUIRE_SYMLINKS`` above: a toolchain test that
    self-skips is indistinguishable from one that passed, so the CI job that
    exists to run it sets ``KIVYFORGE_REQUIRE_TOOLCHAIN`` and gets a failure
    instead of a green run that tested nothing.

    Availability is detected at the call site, not here, because there is no
    uniform way to ask: ``clang`` is a ``which`` lookup, MSVC is "try to compile
    something and see".
    """
    message = f"{tool} is not available" + (f": {detail}" if detail else "")
    if TOOLCHAIN_REQUIRED:
        pytest.fail(f"{message} — but KIVYFORGE_REQUIRE_TOOLCHAIN is set")
    pytest.skip(message)


def pytest_addoption(parser):
    # T3 artifact assertions run against a build that already happened, so the
    # artifact arrives by path rather than being produced by the suite. Absent
    # these, the tests skip: only a CI job that just built something can supply
    # them (docs/design/dev/test-matrix.md §3).
    group = parser.getgroup("kivyforge artifacts")
    group.addoption(
        "--android-apk",
        default=None,
        help="Path to a built APK to run the T3 artifact assertions against.",
    )
    group.addoption(
        "--android-abi",
        default="x86_64",
        help="Dashed Android ABI the APK was built for (default: x86_64).",
    )
    group.addoption(
        "--android-stripped",
        action="store_true",
        help="Assert the payload is bytecode-only (strip_source applied).",
    )
    group.addoption(
        "--android-merged-manifest",
        default=None,
        help="Path to AGP's merged release manifest (the copy the generated "
        "exportKivyforgeReleaseManifest task makes) to check against config.",
    )
    group.addoption(
        "--android-project",
        default=None,
        help="Path to the project directory whose pyproject.toml the merged "
        "manifest must agree with. Required by --android-merged-manifest: "
        "the check is a comparison, so it needs both sides.",
    )
    group.addoption(
        "--macos-app",
        default=None,
        help="Path to a built .app to run the T3 artifact assertions against.",
    )
    group.addoption(
        "--macos-arch",
        default="arm64",
        help="Mach-O arch the .app was built for (default: arm64).",
    )
    group.addoption(
        "--macos-stripped",
        action="store_true",
        help="Assert app+lib are bytecode-only (strip_source applied).",
    )
    group.addoption(
        "--macos-project",
        default=None,
        help="Path to the project directory whose pyproject.toml the .app was "
        "built from; supplies the Info.plist keys config decides.",
    )
    group.addoption(
        "--ios-app",
        default=None,
        help="Path to a built .app (simulator or device) to run the T3 "
        "artifact assertions against.",
    )
    group.addoption(
        "--ios-arch",
        default="arm64",
        help="Mach-O arch the .app was built for (default: arm64).",
    )
    group.addoption(
        "--ios-project",
        default=None,
        help="Path to the project directory whose pyproject.toml the .app was "
        "built from; supplies the Info.plist keys config decides. No "
        "--ios-stripped option exists: iOS strip_source cannot be exercised "
        "honestly yet (see tests/artifact_checks.py's iOS module note).",
    )
    group.addoption(
        "--linux-appimage",
        default=None,
        help="Path to a built .AppImage to run the T3 artifact assertions against.",
    )
    group.addoption(
        "--linux-appdir",
        default=None,
        help="Path to a built AppDir directory (as `kivyforge package -f folder` "
        "emits) to check instead of extracting an .AppImage.",
    )
    group.addoption(
        "--linux-arch",
        default="x86_64",
        help="kivyforge arch the Linux artifact was built for (default: x86_64).",
    )
    group.addoption(
        "--linux-stripped",
        action="store_true",
        help="Assert the Linux payload is bytecode-only (strip_source applied).",
    )
    group.addoption(
        "--windows-onedir",
        default=None,
        help="Path to a built Windows onedir bundle (dist copy) to run the T3 "
        "artifact assertions against.",
    )
    group.addoption(
        "--windows-arch",
        default="amd64",
        help="kivyforge arch the Windows bundle was built for (default: amd64).",
    )
    group.addoption(
        "--windows-stripped",
        action="store_true",
        help="Assert the Windows payload is bytecode-only (strip_source applied).",
    )
    group.addoption(
        "--windows-project",
        default=None,
        help="Path to the project directory whose pyproject.toml the Windows "
        "bundle was built from; supplies the launcher's filename and the "
        "signing config.",
    )
    group.addoption(
        "--windows-signed-exe",
        default=None,
        help="Path to any Authenticode-signed PE to verify. The windows_signing "
        "job points this at the launcher copy it just signed.",
    )
    # Not an artifact: a *host* to interrogate. find_interpreter's Windows
    # candidate search only runs when kivyforge is not already running under
    # the minor being shipped, so a CI job sets these up deliberately
    # (test-matrix.md §5.2).
    resolver = parser.getgroup("kivyforge interpreter resolver (live)")
    resolver.addoption(
        "--resolver-found-minor",
        default=None,
        help="A CPython minor (e.g. 3.14) that must be found by searching — "
        "via the py launcher on Windows — rather than by the running-interpreter "
        "fast path.",
    )
    group.addoption(
        "--windows-long-paths-off-bundle",
        default=None,
        help="Path to a built onedir bundle to measure against MAX_PATH. Only "
        "meaningful on a Windows host where LongPathsEnabled has been set to 0; "
        "the test fails if it has not.",
    )
    resolver.addoption(
        "--resolver-prerelease-minor",
        default=None,
        help="A CPython minor whose only installed interpreter is a pre-release; "
        "the resolver must reject it (roadmap item 1's trap).",
    )


def pytest_configure(config):
    # CI sets KIVYFORGE_REQUIRE_SYMLINKS to assert the requires_symlinks tests
    # actually run (they self-skip on a host without the privilege, which would
    # otherwise silently hide a regression). Fail loudly instead of skipping.
    if os.environ.get("KIVYFORGE_REQUIRE_SYMLINKS") and not SYMLINKS_SUPPORTED:
        raise pytest.UsageError(
            "KIVYFORGE_REQUIRE_SYMLINKS is set but this host cannot create "
            "symlinks, so `requires_symlinks` tests would skip. Enable the "
            "OS symlink-creation privilege (Windows Developer Mode / admin) "
            "before running with this flag."
        )
    config.addinivalue_line(
        "markers",
        "requires_symlinks: needs OS symlink-creation privilege (skipped on a "
        "stock Windows host without Developer Mode/admin).",
    )
    config.addinivalue_line(
        "markers",
        "requires_posix: needs a POSIX host/shell (skipped on Windows).",
    )
    config.addinivalue_line(
        "markers",
        "requires_windows: needs a Windows host (skipped elsewhere). Needing the "
        "MSVC toolset on top of that is requires_toolchain, below.",
    )
    # The two below name the tiers in docs/design/dev/test-matrix.md, so that
    # "which tier does CI actually run" is a `-m` expression rather than a
    # question about which job happens to invoke which paths.
    #
    # There was a third, `requires_device`, removed 2026-09-23 (test-matrix.md
    # §5.7): no test ever carried it, so `KIVYFORGE_DEVICE_TESTS=1` enabled
    # nothing while implying device coverage existed behind a flag. Real
    # device runs are manual and logged in §7. If ADB-driven tests are ever
    # written, reintroduce the marker *with* them rather than ahead of them.
    config.addinivalue_line(
        "markers",
        "integration: not hermetic — needs a real toolchain, artifact, or "
        'network. Implied by requires_toolchain; `-m "not integration"` is the '
        "hermetic suite.",
    )
    config.addinivalue_line(
        "markers",
        "requires_toolchain: shells out to a real external toolchain, and "
        "self-skips when it is absent — set KIVYFORGE_REQUIRE_TOOLCHAIN to make "
        "that a failure instead (see skip_missing_toolchain).",
    )


def pytest_collection_modifyitems(config, items):
    skip_symlinks = pytest.mark.skip(
        reason="requires symlink-creation privilege (Windows Developer Mode/admin)"
    )
    skip_posix = pytest.mark.skip(reason="requires a POSIX host/shell")
    skip_windows = pytest.mark.skip(reason="requires a Windows host")
    for item in items:
        if "requires_symlinks" in item.keywords and not SYMLINKS_SUPPORTED:
            item.add_marker(skip_symlinks)
        if "requires_posix" in item.keywords and sys.platform == "win32":
            item.add_marker(skip_posix)
        if "requires_windows" in item.keywords and sys.platform != "win32":
            item.add_marker(skip_windows)
        if "requires_toolchain" in item.keywords:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(autouse=True)
def _default_target_platform(monkeypatch):
    monkeypatch.setenv("KIVYFORGE_PLATFORM", "ios")


@pytest.fixture(autouse=True)
def _allow_ios_verbs_off_macos(monkeypatch):
    """Neutralize the iOS macOS-host gate for the suite.

    The whole iOS workflow — ``lock`` included, because resolving Swift
    packages shells out to ``swift package resolve`` — is macOS-only, but the
    tests must still run on Linux and Windows CI. Same approach the macOS and
    Linux suites use: no-op the module-level ``_require_*`` helper.

    The gate's own behaviour is covered directly in
    ``tests/platforms/test_host_gating.py``, which calls the real helpers.
    """
    from kivyforge.cli import lock as lock_cli
    from kivyforge.platforms.ios import cli as ios_cli

    monkeypatch.setattr(ios_cli, "_require_macos_host", lambda: None)
    monkeypatch.setattr(lock_cli, "_require_host_toolchain", lambda backend: None)
