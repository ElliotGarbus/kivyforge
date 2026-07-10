"""Linux profile helpers: manylinux tag ladder, coverage, effective floor."""

from __future__ import annotations

import pytest

from kivyforge.lock.linux import (
    LinuxResolverError,
    get_linux_resolver,
    is_plain_linux_tag,
    linux_wheel_arch,
    linux_wheel_coverage,
    manylinux_platform_tags,
    wheel_glibc_level,
)
from kivyforge.lock.linux.profile import LinuxProfile
from kivyforge.lock.model import LockedWheel


def _wheel(tag: str, *, vendored: bool) -> LockedWheel:
    name = f"foo-1.0-cp312-cp312-{tag}.whl"
    if vendored:
        return LockedWheel(name=name, sha256="x", path=f"wheels/{name}")
    return LockedWheel(name=name, sha256="x", url=f"https://pypi.example/{name}")


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


class TestPlainLinuxTag:
    def test_plain_linux_is_plain(self):
        assert is_plain_linux_tag("linux_x86_64")

    def test_manylinux_is_not_plain(self):
        assert not is_plain_linux_tag("manylinux2014_x86_64")
        assert not is_plain_linux_tag("manylinux_2_17_x86_64")

    def test_musllinux_is_not_plain(self):
        assert not is_plain_linux_tag("musllinux_1_1_x86_64")


class TestWheelCoverageSourceGating:
    def test_manylinux_covers_regardless_of_source(self):
        covered, warning = linux_wheel_coverage(
            _wheel("manylinux2014_x86_64", vendored=False), ("x86_64",)
        )
        assert covered == {"x86_64"}
        assert warning is None

    def test_plain_linux_from_pypi_does_not_cover(self):
        covered, warning = linux_wheel_coverage(
            _wheel("linux_x86_64", vendored=False), ("x86_64",)
        )
        assert covered == set()
        assert warning is None

    def test_plain_linux_from_find_links_covers_with_warning(self):
        covered, warning = linux_wheel_coverage(
            _wheel("linux_x86_64", vendored=True), ("x86_64",)
        )
        assert covered == {"x86_64"}
        assert warning is not None
        assert "no glibc promise" in warning

    def test_profile_delegates_to_source_gated_coverage(self):
        profile = LinuxProfile()
        covered, warning = profile.wheel_coverage(
            _wheel("linux_x86_64", vendored=False), ("x86_64",)
        )
        assert covered == set()
        assert warning is None


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
