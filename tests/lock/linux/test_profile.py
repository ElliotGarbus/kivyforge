"""Linux profile helpers: manylinux tag ladder, coverage, effective floor."""

from __future__ import annotations

import pytest

from kivyforge.lock.linux import (
    LinuxResolverError,
    get_linux_resolver,
    linux_wheel_arch,
    manylinux_platform_tags,
    wheel_glibc_level,
)
from kivyforge.lock.linux.profile import LinuxProfile


class TestManylinuxTags:
    def test_floor_2_17_ladder(self):
        tags = manylinux_platform_tags("2.17", "x86_64")
        # Floor tag is first (identity), then descending perennial, then legacy.
        assert tags[0] == "manylinux_2_17_x86_64"
        assert "manylinux_2_5_x86_64" in tags
        assert "manylinux1_x86_64" in tags
        assert "manylinux2010_x86_64" in tags
        assert "manylinux2014_x86_64" in tags
        # No tag above the floor.
        assert "manylinux_2_28_x86_64" not in tags

    def test_higher_floor_admits_more(self):
        tags = manylinux_platform_tags("2.28", "x86_64")
        assert tags[0] == "manylinux_2_28_x86_64"
        assert "manylinux_2_17_x86_64" in tags
        assert "manylinux2014_x86_64" in tags


class TestWheelArch:
    @pytest.mark.parametrize(
        "tag,expected",
        [
            ("manylinux2014_x86_64", "x86_64"),
            ("manylinux2010_x86_64", "x86_64"),
            ("manylinux1_x86_64", "x86_64"),
            ("manylinux_2_17_x86_64", "x86_64"),
            ("manylinux_2_28_x86_64", "x86_64"),
            ("linux_x86_64", "x86_64"),
            ("musllinux_1_1_x86_64", None),
            ("macosx_11_0_x86_64", None),
            ("any", None),
        ],
    )
    def test_extraction(self, tag, expected):
        assert linux_wheel_arch(tag) == expected


class TestWheelCovers:
    def test_compound_tag_covers_x86_64(self):
        profile = LinuxProfile()
        covered = profile.wheel_covers(
            "manylinux_2_17_x86_64.manylinux2014_x86_64", ("x86_64",)
        )
        assert covered == {"x86_64"}

    def test_musllinux_never_covers(self):
        profile = LinuxProfile()
        assert profile.wheel_covers("musllinux_1_1_x86_64", ("x86_64",)) == set()


class TestGlibcLevel:
    def test_compound_takes_lowest(self):
        # A wheel valid under both manylinux1 and manylinux2014 runs on 2.5.
        assert wheel_glibc_level("manylinux1_x86_64.manylinux2014_x86_64") == (2, 5)

    def test_single_perennial(self):
        assert wheel_glibc_level("manylinux_2_28_x86_64") == (2, 28)

    def test_plain_linux_no_promise(self):
        assert wheel_glibc_level("linux_x86_64") is None


class TestFactory:
    def test_unknown_backend(self):
        with pytest.raises(LinuxResolverError, match="unknown resolver backend"):
            get_linux_resolver("bogus")
