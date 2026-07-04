"""macOS profile helpers (tag construction, arch extraction) + resolver factory."""

from __future__ import annotations

import pytest

from kivyforge.lock.macos import (
    MacosResolverError,
    get_macos_resolver,
    macos_platform_tag,
    wheel_arch,
)


class TestPlatformTag:
    def test_arm64(self):
        assert macos_platform_tag("11.0", "arm64") == "macosx_11_0_arm64"

    def test_x86_64(self):
        assert macos_platform_tag("10.15", "x86_64") == "macosx_10_15_x86_64"


class TestWheelArch:
    @pytest.mark.parametrize(
        "tag,expected",
        [
            ("macosx_11_0_arm64", "arm64"),
            ("macosx_11_0_x86_64", "x86_64"),
            ("macosx_11_0_universal2", "universal2"),
            ("macosx_11_0_intel", None),
            ("any", None),
            ("linux_x86_64", None),
        ],
    )
    def test_extraction(self, tag, expected):
        assert wheel_arch(tag) == expected


class TestFactory:
    def test_unknown_backend(self):
        with pytest.raises(MacosResolverError, match="unknown resolver backend"):
            get_macos_resolver("bogus")
