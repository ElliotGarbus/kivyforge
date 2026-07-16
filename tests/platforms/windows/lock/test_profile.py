"""Windows profile helpers: single win_amd64 tag, coverage, factory."""

from __future__ import annotations

import pytest

from kivyforge.platforms.windows.lock import (
    WindowsResolverError,
    get_windows_resolver,
    wheel_arch,
    windows_platform_tag,
)
from kivyforge.platforms.windows.lock.profile import VALID_WHEEL_ARCHS, WindowsProfile


class TestPlatformTag:
    def test_amd64_maps_to_win_amd64(self):
        assert windows_platform_tag("amd64") == "win_amd64"

    def test_valid_archs(self):
        assert VALID_WHEEL_ARCHS == frozenset({"amd64"})


class TestWheelArch:
    @pytest.mark.parametrize(
        "tag,expected",
        [
            ("win_amd64", "amd64"),
            ("win32", None),
            ("win_arm64", None),
            ("manylinux2014_x86_64", None),
            ("macosx_11_0_arm64", None),
            ("any", None),
        ],
    )
    def test_extraction(self, tag, expected):
        assert wheel_arch(tag) == expected


class TestWheelCovers:
    def test_win_amd64_covers_amd64(self):
        profile = WindowsProfile()
        assert profile.wheel_covers("win_amd64", ("amd64",)) == {"amd64"}

    def test_unrelated_tag_covers_nothing(self):
        profile = WindowsProfile()
        assert profile.wheel_covers("win32", ("amd64",)) == set()
        assert profile.wheel_covers("manylinux2014_x86_64", ("amd64",)) == set()


class TestVariants:
    def test_single_amd64_variant(self):
        from kivyforge.config.loader import load_config_from_text

        text = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.windows]\nschema_version=1\napp_id='Example.A'\n"
            "[tool.kivy.windows.python]\nversion='3.13.14'\n"
        )
        cfg = load_config_from_text(text, require_ios=False, require_windows=True)
        variants = WindowsProfile().variants(cfg)
        assert len(variants) == 1
        assert variants[0].arch == "amd64"
        assert variants[0].platform_tag == "win_amd64"
        assert variants[0].extra_platform_tags == ()


class TestPythonVersion:
    def test_returns_configured_version(self):
        from types import SimpleNamespace

        cfg = SimpleNamespace(
            windows_required=SimpleNamespace(python_version="3.13.14")
        )
        assert WindowsProfile().python_version(cfg) == "3.13.14"

    def test_missing_version_raises_not_silent_default(self):
        # No hidden 3.15.0 fallback: an unset version surfaces as a clear error
        # rather than silently pinning an unexpected (possibly unreleased) Python.
        from types import SimpleNamespace

        from kivyforge.config.errors import ConfigError

        cfg = SimpleNamespace(windows_required=SimpleNamespace(python_version=None))
        with pytest.raises(ConfigError, match="python.*version"):
            WindowsProfile().python_version(cfg)


class TestFactory:
    def test_get_default(self):
        assert get_windows_resolver() is not None

    def test_unknown_backend(self):
        with pytest.raises(WindowsResolverError, match="unknown resolver backend"):
            get_windows_resolver("bogus")
