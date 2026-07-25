"""Marker evaluation targets Android, not the lock host (android/02).

pip's ``--platform``/``--abi`` constrain wheel *tags* only; markers are
evaluated against the interpreter running pip. That made ``kivyforge lock
-p android`` succeed on Linux and fail on Windows, because Kivy declares
``kivy-deps.angle; sys_platform == "win32"``. These tests pin the target
environment and the edge filtering built on it.
"""

from __future__ import annotations

import pytest
from packaging.requirements import Requirement

from kivyforge.lock._pip_shim import MARKER_ENV_VAR
from kivyforge.lock.resolver import dep_names_for_environment
from kivyforge.platforms.android.lock.markers import (
    MarkerEnvironmentError,
    android_marker_environment,
)


def _env(abi: str = "arm64_v8a", python_version: str = "3.14.6"):
    return android_marker_environment(python_version=python_version, abi=abi)


class TestMarkerEnvironment:
    def test_identifies_as_android(self):
        env = _env()
        # CPython 3.13+ reports these on Android (PEP 738).
        assert env["sys_platform"] == "android"
        assert env["platform_system"] == "Android"
        assert env["os_name"] == "posix"
        assert env["platform_python_implementation"] == "CPython"

    @pytest.mark.parametrize(
        ("abi", "machine"),
        [
            ("arm64_v8a", "aarch64"),
            ("x86_64", "x86_64"),
            ("armeabi_v7a", "armv7l"),
            ("x86", "i686"),
        ],
    )
    def test_machine_is_per_abi(self, abi, machine):
        assert _env(abi)["platform_machine"] == machine

    def test_python_version_split(self):
        env = _env(python_version="3.14.6")
        assert env["python_version"] == "3.14"
        assert env["python_full_version"] == "3.14.6"

    def test_covers_every_pep508_marker_name(self):
        """A missing key raises UndefinedEnvironmentName mid-resolve, so the
        environment must be complete rather than merely plausible."""
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

    def test_unknown_abi_is_an_error(self):
        with pytest.raises(MarkerEnvironmentError, match="unknown Android ABI"):
            android_marker_environment(python_version="3.14.6", abi="mips")

    def test_partial_python_version_is_an_error(self):
        with pytest.raises(MarkerEnvironmentError, match="full X.Y.Z"):
            android_marker_environment(python_version="3", abi="x86_64")

    def test_the_regression_marker_is_false_on_android(self):
        """The exact requirement that broke locking on a Windows host."""
        requirement = Requirement('kivy-deps.angle~=0.4.0; sys_platform == "win32"')
        assert requirement.marker is not None
        assert not requirement.marker.evaluate(_env())


class TestDepNamesForEnvironment:
    def test_drops_host_only_and_extra_gated_edges(self):
        """Kivy's raw Requires-Dist names pytest, sphinx and kivy-deps.angle
        beside its real runtime deps; the lock must record only what it
        installs."""
        requires_dist = [
            "requests",
            "filetype",
            'kivy-deps.angle~=0.4.0; sys_platform == "win32"',
            'pypiwin32; sys_platform == "win32"',
            'pytest; extra == "dev"',
            'sphinx; extra == "doc"',
        ]
        assert dep_names_for_environment(requires_dist, _env()) == ["requests", "filetype"]

    def test_keeps_edges_whose_marker_holds_on_android(self):
        requires_dist = ['oscpy; platform_system == "Android"']
        assert dep_names_for_environment(requires_dist, _env()) == ["oscpy"]

    def test_machine_gated_edge_follows_the_abi(self):
        requires_dist = ['fast-thing; platform_machine == "aarch64"']
        assert dep_names_for_environment(requires_dist, _env("arm64_v8a")) == ["fast-thing"]
        assert dep_names_for_environment(requires_dist, _env("x86_64")) == []

    def test_unparseable_metadata_does_not_fail_the_lock(self):
        # Upstream's problem, not a reason to refuse to lock: fall back to the
        # permissive name-only reading (everything up to the first separator).
        assert dep_names_for_environment(["not a valid requirement!!"], _env()) == ["not"]

    def test_empty(self):
        assert dep_names_for_environment([], _env()) == []


class TestShimContract:
    def test_shim_refuses_to_fall_back_to_host_markers(self, monkeypatch):
        """A silent fallback would reintroduce the host-dependent lock."""
        from kivyforge.lock import _pip_shim

        monkeypatch.delenv(MARKER_ENV_VAR, raising=False)
        assert _pip_shim.main(["install", "anything"]) != 0
