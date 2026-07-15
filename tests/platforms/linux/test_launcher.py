"""AppRun shell launcher generation."""

from __future__ import annotations

import os
import subprocess

import pytest

from kivyforge.platforms.linux import AppDirError, launcher


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

    def test_no_native_block_by_default(self):
        src = launcher.render_apprun(entry_point="main", app_id="a")
        assert "usr/bin" not in src
        assert "LD_LIBRARY_PATH" not in src

    def test_native_block_prepends_path_appends_ld_library_path(self):
        src = launcher.render_apprun(
            entry_point="main", app_id="a", has_native_binaries=True
        )
        assert 'export PATH="$HERE/usr/bin:$PATH"' in src
        assert (
            'export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}'
            '$HERE/usr/bin"' in src
        )


class TestBuildApprun:
    def test_writes_executable(self, tmp_path):
        dest = tmp_path / "AppRun"
        launcher.build_apprun(dest, entry_point="main", app_id="org.example.app")
        assert dest.read_text().startswith("#!/bin/sh")
        assert os.access(dest, os.X_OK)

    def test_native_binaries_flag_threads_through(self, tmp_path):
        dest = tmp_path / "AppRun"
        launcher.build_apprun(
            dest, entry_point="main", app_id="a", has_native_binaries=True
        )
        assert 'export PATH="$HERE/usr/bin:$PATH"' in dest.read_text()


@pytest.mark.requires_posix
class TestAppRunExecution:
    """Run a real AppRun tree with a fake python3 that echoes PATH/LD_LIBRARY_PATH."""

    def _tree(self, tmp_path, *, has_native_binaries):
        appdir = tmp_path / "App.AppDir"
        launcher.build_apprun(
            appdir / "AppRun",
            entry_point="main",
            app_id="org.example.app",
            has_native_binaries=has_native_binaries,
        )
        py = appdir / "usr" / "python" / "bin" / "python3"
        py.parent.mkdir(parents=True)
        # Stand-in interpreter: ignore the script arg, print the two search paths.
        py.write_text(
            '#!/bin/sh\nprintf "PATH=%s\\nLD=%s\\n" "$PATH" "$LD_LIBRARY_PATH"\n'
        )
        py.chmod(0o755)
        app = appdir / "usr" / "app"
        app.mkdir(parents=True)
        (app / "main.py").write_text("")
        (appdir / "usr" / "bin").mkdir(parents=True)
        return appdir

    def test_child_sees_usr_bin_first_on_path_last_on_ld_library_path(self, tmp_path):
        appdir = self._tree(tmp_path, has_native_binaries=True)
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = "/pre/existing/libs"
        out = subprocess.run(
            [str(appdir / "AppRun")],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout
        lines = dict(line.split("=", 1) for line in out.strip().splitlines())
        # usr/bin is first on PATH (declared helpers win by name) ...
        assert lines["PATH"].split(":", 1)[0].endswith("/usr/bin")
        # ... and last on LD_LIBRARY_PATH (the pre-existing entry stays ahead).
        ld_parts = lines["LD"].split(":")
        assert ld_parts[0] == "/pre/existing/libs"
        assert ld_parts[-1].endswith("/usr/bin")

    def test_child_has_no_native_env_when_absent(self, tmp_path):
        appdir = self._tree(tmp_path, has_native_binaries=False)
        env = dict(os.environ)
        env.pop("LD_LIBRARY_PATH", None)
        out = subprocess.run(
            [str(appdir / "AppRun")],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout
        lines = dict(line.split("=", 1) for line in out.strip().splitlines())
        # The AppDir's own usr/bin is never prepended (the host's /usr/bin may
        # still appear — that's the inherited host PATH, not ours).
        assert str(appdir / "usr" / "bin") not in lines["PATH"]
        assert lines["LD"] == ""
