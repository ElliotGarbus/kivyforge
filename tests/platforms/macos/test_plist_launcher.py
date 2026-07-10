"""Info.plist + launcher generation."""

from __future__ import annotations

import os
import platform
import shutil
import stat
import sys

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.macos import AppBundleError
from kivyforge.platforms.macos.launcher import build_launcher, render_launcher_source
from kivyforge.platforms.macos.machotools import is_macho, macho_arches
from kivyforge.platforms.macos.plist import (
    DEFAULT_MINIMUM_SYSTEM_VERSION,
    build_info_plist,
)

_BASE = (
    "[project]\nname='myapp'\nversion='2.5.0'\nrequires-python='>=3.14'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\nbuild=7\n"
    "{extra}"
    "[tool.kivy.macos.python]\nversion='3.14.5'\n"
)


def _config(extra: str = ""):
    return load_config_from_text(
        _BASE.format(extra=extra), require_ios=False, require_macos=True
    )


class TestInfoPlist:
    def test_core_keys(self):
        plist = build_info_plist(_config(), executable="myapp", icon_file=None)
        assert plist["CFBundleIdentifier"] == "org.example.myapp"
        assert plist["CFBundleName"] == "My App"
        assert plist["CFBundleExecutable"] == "myapp"
        assert plist["CFBundleShortVersionString"] == "2.5.0"
        assert plist["CFBundleVersion"] == "7"
        assert plist["CFBundlePackageType"] == "APPL"
        assert "CFBundleIconFile" not in plist

    def test_default_minimum_system_version(self):
        plist = build_info_plist(_config(), executable="x", icon_file=None)
        assert plist["LSMinimumSystemVersion"] == DEFAULT_MINIMUM_SYSTEM_VERSION

    def test_explicit_minimum_and_icon(self):
        plist = build_info_plist(
            _config('minimum_system_version="13.0"\n'),
            executable="x",
            icon_file="x.icns",
        )
        assert plist["LSMinimumSystemVersion"] == "13.0"
        assert plist["CFBundleIconFile"] == "x.icns"


class TestLauncherSource:
    def test_embeds_entry_and_layout(self):
        src = render_launcher_source("main")
        assert 'static const char *ENTRY = "main";' in src
        assert "Resources/python" in src
        assert "Resources/app" in src
        assert "Resources/lib" in src
        assert "execv(py, child)" in src

    def test_rejects_non_identifier_entry(self):
        with pytest.raises(AppBundleError, match="not a valid module name"):
            render_launcher_source("main.py")


# The launcher is a Mach-O stub built with `clang -arch ...`; that is a macOS-only
# operation (Linux clang rejects `-arch`/can't emit Mach-O), matching the fact
# that the whole `.app` build only runs on macOS hosts. The macOS integration CI
# job exercises these; skip them elsewhere.
_CAN_BUILD_MACHO = sys.platform == "darwin" and shutil.which("clang") is not None


@pytest.mark.skipif(
    not _CAN_BUILD_MACHO,
    reason="Mach-O launcher build requires macOS + clang (Xcode CLT)",
)
class TestLauncherCompile:
    def test_builds_thin_macho(self, tmp_path):
        host = "arm64" if platform.machine() == "arm64" else "x86_64"
        path = tmp_path / "MacOS" / "myapp"
        build_launcher(path, entry_point="main", archs=(host,))
        assert is_macho(path)
        assert macho_arches(path) == (host,)
        assert os.stat(path).st_mode & stat.S_IXUSR

    def test_builds_universal2_macho(self, tmp_path):
        path = tmp_path / "MacOS" / "myapp"
        build_launcher(path, entry_point="main", archs=("arm64", "x86_64"))
        assert is_macho(path)
        assert set(macho_arches(path)) == {"arm64", "x86_64"}

    def test_requires_at_least_one_arch(self, tmp_path):
        with pytest.raises(AppBundleError, match="at least one arch"):
            build_launcher(tmp_path / "x", entry_point="main", archs=())
