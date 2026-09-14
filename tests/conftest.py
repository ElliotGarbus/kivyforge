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

# Device tests drive real hardware, so they are opt-in rather than self-skipping:
# there is no device in CI and never will be, and a marker that skips silently
# everywhere is one nobody notices has stopped running.
DEVICE_TESTS_ENABLED = bool(os.environ.get("KIVYFORGE_DEVICE_TESTS"))

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
    # The three below name the tiers in docs/design/dev/test-matrix.md, so that
    # "which tier does CI actually run" is a `-m` expression rather than a
    # question about which job happens to invoke which paths.
    config.addinivalue_line(
        "markers",
        "integration: not hermetic — needs a real toolchain, device, or network. "
        'Implied by requires_toolchain and requires_device; `-m "not '
        'integration"` is the hermetic suite.',
    )
    config.addinivalue_line(
        "markers",
        "requires_toolchain: shells out to a real external toolchain, and "
        "self-skips when it is absent — set KIVYFORGE_REQUIRE_TOOLCHAIN to make "
        "that a failure instead (see skip_missing_toolchain).",
    )
    config.addinivalue_line(
        "markers",
        "requires_device: drives real hardware; opt-in via KIVYFORGE_DEVICE_TESTS "
        "because no CI runner has a device attached.",
    )


def pytest_collection_modifyitems(config, items):
    skip_symlinks = pytest.mark.skip(
        reason="requires symlink-creation privilege (Windows Developer Mode/admin)"
    )
    skip_posix = pytest.mark.skip(reason="requires a POSIX host/shell")
    skip_windows = pytest.mark.skip(reason="requires a Windows host")
    skip_device = pytest.mark.skip(reason="needs a device; set KIVYFORGE_DEVICE_TESTS")
    for item in items:
        if "requires_symlinks" in item.keywords and not SYMLINKS_SUPPORTED:
            item.add_marker(skip_symlinks)
        if "requires_posix" in item.keywords and sys.platform == "win32":
            item.add_marker(skip_posix)
        if "requires_windows" in item.keywords and sys.platform != "win32":
            item.add_marker(skip_windows)
        if "requires_device" in item.keywords:
            item.add_marker(pytest.mark.integration)
            if not DEVICE_TESTS_ENABLED:
                item.add_marker(skip_device)
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
