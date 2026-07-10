"""AppRun shell launcher generation."""

from __future__ import annotations

import os

import pytest

from kivyforge.linux import AppDirError, launcher


class TestRenderApprun:
    def test_contains_env_and_exec(self):
        src = launcher.render_apprun(entry_point="main", app_id="org.example.app")
        assert src.startswith("#!/bin/sh")
        assert 'PYTHONHOME="$HERE/usr/python"' in src
        assert 'PYTHONPATH="$HERE/usr/app:$HERE/usr/lib"' in src
        assert "PYTHONNOUSERSITE=1" in src
        assert 'SDL_VIDEO_X11_WMCLASS="org.example.app"' in src
        assert 'SDL_VIDEO_WAYLAND_WMCLASS="org.example.app"' in src
        assert 'exec "$HERE/usr/python/bin/python3" "$HERE/usr/app/main.py" "$@"' in src

    def test_dotted_entry_point_maps_to_nested_path(self):
        src = launcher.render_apprun(entry_point="pkg.start", app_id="a")
        assert '"$HERE/usr/app/pkg/start.py"' in src

    def test_rejects_bad_entry_point(self):
        with pytest.raises(AppDirError, match="not a valid module name"):
            launcher.render_apprun(entry_point="not-an-ident", app_id="a")

    def test_rejects_dotted_entry_point_with_bad_segment(self):
        with pytest.raises(AppDirError, match="not a valid module name"):
            launcher.render_apprun(entry_point="pkg.import", app_id="a")


class TestBuildApprun:
    def test_writes_executable(self, tmp_path):
        dest = tmp_path / "AppRun"
        launcher.build_apprun(dest, entry_point="main", app_id="org.example.app")
        assert dest.read_text().startswith("#!/bin/sh")
        assert os.access(dest, os.X_OK)
