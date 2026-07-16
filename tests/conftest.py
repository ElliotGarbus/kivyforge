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
        "requires_windows: needs a Windows host (skipped elsewhere); some also "
        "need the MSVC toolset and self-skip when it is absent.",
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


@pytest.fixture(autouse=True)
def _default_target_platform(monkeypatch):
    monkeypatch.setenv("KIVYFORGE_PLATFORM", "ios")
