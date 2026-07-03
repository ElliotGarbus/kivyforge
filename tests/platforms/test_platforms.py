"""Platform registry, resolution chain, and iOS backend metadata/capability."""

from __future__ import annotations

import pytest

from kivyforge.platforms import (
    PlatformResolutionError,
    available_platform_names,
    get_platform,
    resolve_target,
)
from kivyforge.platforms.base import HostCapabilityError
from kivyforge.platforms.ios import IosPlatform
from kivyforge.platforms.macos import MacosPlatform


class TestRegistry:
    def test_available_names(self):
        assert available_platform_names() == ["ios", "macos"]

    def test_get_platform(self):
        assert isinstance(get_platform("ios"), IosPlatform)

    def test_get_unknown_raises(self):
        with pytest.raises(PlatformResolutionError, match="unknown platform"):
            get_platform("bogus")


class TestResolveTarget:
    def test_cli_wins(self):
        p = resolve_target("ios", configured=set(), env={}, host_system="Linux")
        assert p.name == "ios"

    def test_cli_beats_env(self):
        p = resolve_target("ios", configured=set(), env={"KIVYFORGE_PLATFORM": "bogus"})
        assert p.name == "ios"

    def test_env_used(self):
        p = resolve_target(
            None,
            configured=set(),
            env={"KIVYFORGE_PLATFORM": "ios"},
            host_system="Linux",
        )
        assert p.name == "ios"

    def test_env_unknown_raises(self):
        with pytest.raises(PlatformResolutionError, match="unknown platform"):
            resolve_target(None, configured=set(), env={"KIVYFORGE_PLATFORM": "bogus"})

    def test_ios_is_never_a_host_default(self):
        # iOS is cross-compiled: a macOS host must not auto-select it.
        with pytest.raises(PlatformResolutionError, match="no target platform"):
            resolve_target(None, configured={"ios"}, env={}, host_system="Darwin")

    def test_macos_is_host_default_on_darwin(self):
        # A Mac with [tool.kivy.macos] configured resolves to macos without -p.
        p = resolve_target(None, configured={"macos"}, env={}, host_system="Darwin")
        assert p.name == "macos"

    def test_macos_not_host_default_off_darwin(self):
        with pytest.raises(PlatformResolutionError, match="no target platform"):
            resolve_target(None, configured={"macos"}, env={}, host_system="Linux")

    def test_macos_host_default_requires_configured(self):
        # Darwin host but macos overlay not declared -> no host fallback.
        with pytest.raises(PlatformResolutionError, match="no target platform"):
            resolve_target(None, configured={"ios"}, env={}, host_system="Darwin")

    def test_error_lists_configured_platforms(self):
        with pytest.raises(PlatformResolutionError) as exc:
            resolve_target(None, configured={"ios"}, env={}, host_system="Linux")
        assert "ios" in str(exc.value)


class TestIosPlatform:
    def test_metadata(self):
        p = IosPlatform()
        assert p.name == "ios"
        assert p.host_system is None
        assert p.default_package_format == "ipa"
        assert p.selectors == ("ios",)

    def test_capability_ok_on_macos(self):
        IosPlatform().check_host_capability(host_system="Darwin")

    def test_capability_fails_off_macos(self):
        with pytest.raises(HostCapabilityError, match="requires macOS"):
            IosPlatform().check_host_capability(host_system="Linux")


class TestMacosPlatform:
    def test_metadata(self):
        p = MacosPlatform()
        assert p.name == "macos"
        assert p.host_system == "Darwin"
        assert p.default_package_format == "app"
        assert p.selectors == ("macos",)

    def test_capability_ok_on_macos(self):
        MacosPlatform().check_host_capability(host_system="Darwin")

    def test_capability_fails_off_macos(self):
        with pytest.raises(HostCapabilityError, match="requires a macOS host"):
            MacosPlatform().check_host_capability(host_system="Linux")
