"""AppImage packaging (hermetic: fetch + appimagetool subprocess faked)."""

from __future__ import annotations

import subprocess

import pytest

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.platforms.linux import AppDirError, appimage


class TestPins:
    def test_appimagetool_asset(self):
        url, sha = appimage.appimagetool_asset("x86_64")
        assert url.endswith("appimagetool-x86_64.AppImage")
        assert len(sha) == 64

    def test_runtime_asset(self):
        url, sha = appimage.type2_runtime_asset("x86_64")
        assert url.endswith("runtime-x86_64")
        assert len(sha) == 64

    def test_unknown_arch(self):
        with pytest.raises(AppDirError, match="no pinned appimagetool"):
            appimage.appimagetool_asset("aarch64")
        with pytest.raises(AppDirError, match="no pinned type2 runtime"):
            appimage.type2_runtime_asset("aarch64")


@pytest.fixture
def fake_tools(tmp_path, monkeypatch):
    """Return cache-backed dummy tool/runtime files instead of downloading."""
    tool = tmp_path / "dl" / "appimagetool"
    runtime = tmp_path / "dl" / "runtime"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!appimagetool")
    runtime.write_text("runtime")

    def fake_fetch(*, name, **k):
        return tool if name == "appimagetool" else runtime

    monkeypatch.setattr(appimage, "fetch_artifact", fake_fetch)
    return {"tool": tool, "runtime": runtime}


class TestBuildAppimage:
    def test_invokes_appimagetool(self, tmp_path, monkeypatch, fake_tools):
        recorded = {}

        def fake_run(cmd, *, capture_output, text, env):
            recorded["cmd"] = cmd
            recorded["env"] = env
            # appimagetool writes the output file.
            from pathlib import Path

            Path(cmd[-1]).write_text("APPIMAGE")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(appimage.subprocess, "run", fake_run)
        appdir = tmp_path / "My App.AppDir"
        appdir.mkdir()
        output = tmp_path / "dist" / "linux" / "myapp-1.0-x86_64.AppImage"
        cache = ArtifactCache(root=tmp_path / "cache" / "artifacts")
        result = appimage.build_appimage(
            appdir, output, "x86_64", project_root=tmp_path, cache=cache
        )
        assert result == output
        assert output.exists()
        assert recorded["env"]["ARCH"] == "x86_64"
        assert recorded["env"]["APPIMAGE_EXTRACT_AND_RUN"] == "1"
        assert "--runtime-file" in recorded["cmd"]
        assert str(appdir) in recorded["cmd"]

    def test_failure_raises(self, tmp_path, monkeypatch, fake_tools):
        def fake_run(cmd, **k):
            return subprocess.CompletedProcess(cmd, 1, "", "boom")

        monkeypatch.setattr(appimage.subprocess, "run", fake_run)
        appdir = tmp_path / "app.AppDir"
        appdir.mkdir()
        cache = ArtifactCache(root=tmp_path / "cache" / "artifacts")
        with pytest.raises(AppDirError, match="appimagetool failed"):
            appimage.build_appimage(
                appdir,
                tmp_path / "out.AppImage",
                "x86_64",
                project_root=tmp_path,
                cache=cache,
            )
