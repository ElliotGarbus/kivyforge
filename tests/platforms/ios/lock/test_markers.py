"""Marker evaluation targets iOS, not the macOS host running pip (spec 02).

The iOS variant of the Android bug, but quieter: iOS is always cross-resolved
from macOS, and ``darwin`` resembles ``ios`` closely enough that most markers
coincidentally agree. Nothing errors — a ``sys_platform == "ios"`` dependency
is simply dropped, and the app is missing it at runtime. Restricting the
workflow to macOS does not fix this; describing the target does.
"""

from __future__ import annotations

import pytest
from packaging.requirements import Requirement

from kivyforge.lock.resolver import dep_names_for_environment
from kivyforge.platforms.ios.lock.markers import (
    MarkerEnvironmentError,
    ios_marker_environment,
    machine_for_slice,
)
from kivyforge.platforms.ios.lock.resolver import slice_suffixes


def _env(slice_suffix: str = "arm64_iphoneos", python_version: str = "3.15.0"):
    return ios_marker_environment(
        python_version=python_version, slice_suffix=slice_suffix
    )


class TestMarkerEnvironment:
    def test_identifies_as_ios_not_macos(self):
        env = _env()
        # PEP 730: CPython on iOS reports these on device *and* simulator.
        assert env["sys_platform"] == "ios"
        assert env["platform_system"] == "iOS"
        assert env["os_name"] == "posix"

    @pytest.mark.parametrize(
        ("slice_suffix", "machine"),
        [
            ("arm64_iphoneos", "arm64"),
            ("arm64_iphonesimulator", "arm64"),
            ("x86_64_iphonesimulator", "x86_64"),
        ],
    )
    def test_machine_per_slice(self, slice_suffix, machine):
        assert _env(slice_suffix)["platform_machine"] == machine

    def test_every_real_slice_is_describable(self):
        """Whatever slice_suffixes() produces must be a slice markers.py can
        describe, or resolution dies partway through."""
        for suffix in slice_suffixes():
            assert machine_for_slice(suffix)

    def test_python_version_split(self):
        env = _env(python_version="3.15.0")
        assert env["python_version"] == "3.15"
        assert env["python_full_version"] == "3.15.0"

    def test_covers_every_pep508_marker_name(self):
        required = {
            "implementation_name",
            "implementation_version",
            "os_name",
            "platform_machine",
            "platform_python_implementation",
            "platform_release",
            "platform_system",
            "platform_version",
            "python_full_version",
            "python_version",
            "sys_platform",
        }
        assert required <= set(_env())

    def test_unrecognised_slice_is_an_error(self):
        with pytest.raises(MarkerEnvironmentError, match="unrecognised iOS slice"):
            machine_for_slice("arm64_watchos")

    def test_partial_python_version_is_an_error(self):
        with pytest.raises(MarkerEnvironmentError, match="full X.Y.Z"):
            ios_marker_environment(python_version="3", slice_suffix="arm64_iphoneos")


class TestDarwinIsNotIos:
    """The specific confusions a macOS host would introduce."""

    def test_macos_only_dependency_is_excluded(self):
        requirement = Requirement('pyobjc-core; sys_platform == "darwin"')
        assert not requirement.marker.evaluate(_env())

    def test_ios_only_dependency_is_included(self):
        """The silent case: on a macOS host this marker is False, so the
        dependency vanishes from the lock with no error at all."""
        requirement = Requirement('rubicon-objc; sys_platform == "ios"')
        assert requirement.marker.evaluate(_env())

    def test_platform_system_gate(self):
        assert Requirement('x; platform_system == "iOS"').marker.evaluate(_env())
        assert not Requirement('x; platform_system == "Darwin"').marker.evaluate(_env())

    def test_recorded_edges_are_filtered_for_ios(self):
        requires_dist = [
            "kivy",
            'pyobjc-core; sys_platform == "darwin"',
            'rubicon-objc; sys_platform == "ios"',
            'pytest; extra == "dev"',
        ]
        assert dep_names_for_environment(requires_dist, _env()) == [
            "kivy",
            "rubicon-objc",
        ]
