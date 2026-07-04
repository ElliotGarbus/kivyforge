"""Info.plist + launcher generation."""

from __future__ import annotations

import os
import stat

from kivyforge.config.loader import load_config_from_text
from kivyforge.macos.launcher import write_launcher
from kivyforge.macos.plist import DEFAULT_MINIMUM_SYSTEM_VERSION, build_info_plist

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


class TestLauncher:
    def test_writes_executable_script(self, tmp_path):
        path = tmp_path / "MacOS" / "myapp"
        write_launcher(path, entry_point="main")
        text = path.read_text()
        assert text.startswith("#!/bin/sh")
        assert 'exec "$home/bin/python3" "$app/main.py"' in text
        assert "Resources/python" in text
        mode = os.stat(path).st_mode
        assert mode & stat.S_IXUSR
