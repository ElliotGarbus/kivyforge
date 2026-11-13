"""doctor's kivyforge-version nudge, with versions setuptools-scm builds (#219)."""

from __future__ import annotations

from importlib.metadata import version

import pytest

import kivyforge
from kivyforge.doctor.checks_common import check_kivyforge_version, is_newer_release
from kivyforge.doctor.result import Status
from kivyforge.platforms.android.doctor import _check_kivyforge_version
from tests.doctor.probe_fakes import FakeProbe

DEV = "0.1.1.dev1+g813022a22"


def test_version_is_the_installed_distributions():
    # Not a constant in the tree: a tag decides it, and --version, the
    # User-Agent, JSON reports and lockfile stamps all read this.
    assert kivyforge.__version__ == version("kivyforge")


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("0.1.1", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.1.1", False),
        ("0.2.0", "0.1.10", True),
        # Between tags: newer than the last release, older than the next one.
        ("0.1.0", DEV, False),
        ("0.1.1", DEV, True),
        ("0.1.0", "0.1.dev1+g813022a22", True),
        ("not a version", "0.1.0", False),
    ],
)
def test_is_newer_release(latest, current, newer):
    assert is_newer_release(latest, current) is newer


def test_dev_install_ahead_of_pypi_is_not_told_to_upgrade():
    result = check_kivyforge_version(FakeProbe(latest="0.1.0"), DEV, offline=False)
    assert (result.status, result.detail) == (Status.PASS, DEV)


def test_dev_install_behind_the_release_it_leads_to_is_told():
    result = check_kivyforge_version(FakeProbe(latest="0.1.1"), DEV, offline=False)
    assert result.status is Status.WARN


class _AndroidProbe:
    def __init__(self, latest: str) -> None:
        self._latest = latest

    def latest_kivyforge_version(self) -> str:
        return self._latest


def test_android_check_compares_the_same_way():
    ahead = _check_kivyforge_version(_AndroidProbe("0.1.0"), DEV, offline=False)  # type: ignore[arg-type]
    behind = _check_kivyforge_version(_AndroidProbe("0.1.1"), DEV, offline=False)  # type: ignore[arg-type]
    assert (ahead.status, behind.status) == (Status.PASS, Status.WARN)
