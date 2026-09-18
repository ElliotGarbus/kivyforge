"""AppImage packaging (hermetic: fetch + appimagetool subprocess faked)."""

from __future__ import annotations

import subprocess
from pathlib import Path

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

    def test_appimagetool_asset_aarch64(self):
        url, sha = appimage.appimagetool_asset("aarch64")
        assert url.endswith("appimagetool-aarch64.AppImage")
        assert sha == "f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158"

    def test_runtime_asset_aarch64(self):
        url, sha = appimage.type2_runtime_asset("aarch64")
        assert url.endswith("runtime-aarch64")
        assert sha == "00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444"

    def test_unknown_arch(self):
        with pytest.raises(AppDirError, match="no pinned appimagetool"):
            appimage.appimagetool_asset("riscv64")
        with pytest.raises(AppDirError, match="no pinned type2 runtime"):
            appimage.type2_runtime_asset("riscv64")


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

        def fake_run(cmd, *, capture_output, text, env, stdin=None):
            recorded["cmd"] = cmd
            recorded["env"] = env
            # appimagetool writes the output file (a temp path swapped in later).
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

    def test_cross_build_uses_host_appimagetool(
        self, tmp_path, monkeypatch, fake_tools
    ):
        """aarch64 AppImages still exec the host-arch appimagetool."""
        fetches: list[tuple[str, str]] = []
        orig = appimage.fetch_artifact

        def spy_fetch(*, name, filename, **k):
            fetches.append((name, filename))
            return orig(name=name, filename=filename, **k)

        monkeypatch.setattr(appimage, "fetch_artifact", spy_fetch)

        def fake_run(cmd, *, capture_output, text, env, stdin=None):
            Path(cmd[-1]).write_text("APPIMAGE")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(appimage.subprocess, "run", fake_run)
        monkeypatch.setattr(appimage.platform, "machine", lambda: "x86_64")
        appdir = tmp_path / "App.AppDir"
        appdir.mkdir()
        output = tmp_path / "dist" / "app-aarch64.AppImage"
        cache = ArtifactCache(root=tmp_path / "cache" / "artifacts")
        appimage.build_appimage(
            appdir, output, "aarch64", project_root=tmp_path, cache=cache
        )
        names = dict(fetches)
        assert "x86_64" in names["appimagetool"]
        assert "aarch64" in names["type2 runtime"]
        assert "aarch64" not in names["appimagetool"]

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

    def test_failure_sends_both_streams_to_progress_not_the_error(
        self, tmp_path, monkeypatch, fake_tools
    ):
        def fake_run(cmd, **k):
            return subprocess.CompletedProcess(
                cmd, 1, "Creating squashfs...\n", "mksquashfs: out of space\n"
            )

        monkeypatch.setattr(appimage.subprocess, "run", fake_run)
        appdir = tmp_path / "app.AppDir"
        appdir.mkdir()
        cache = ArtifactCache(root=tmp_path / "cache" / "artifacts")
        progress: list[str] = []
        with pytest.raises(AppDirError) as info:
            appimage.build_appimage(
                appdir,
                tmp_path / "out.AppImage",
                "x86_64",
                project_root=tmp_path,
                cache=cache,
                echo=progress.append,
            )
        # stdout used to be dropped whenever stderr had anything in it.
        assert "Creating squashfs..." in progress
        assert "mksquashfs: out of space" in progress
        assert "exit 1" in str(info.value)
        assert "squashfs" not in str(info.value)

    def test_failure_preserves_previous_output(self, tmp_path, monkeypatch, fake_tools):
        # A tool failure must not destroy the previous good .AppImage: we emit to
        # a temp file and only swap it in on success, and clean the temp up.
        def fake_run(cmd, **k):
            Path(cmd[-1]).write_text("PARTIAL")  # tool wrote a partial, then failed
            return subprocess.CompletedProcess(cmd, 1, "", "boom")

        monkeypatch.setattr(appimage.subprocess, "run", fake_run)
        appdir = tmp_path / "app.AppDir"
        appdir.mkdir()
        output = tmp_path / "dist" / "linux" / "myapp-1.0-x86_64.AppImage"
        output.parent.mkdir(parents=True)
        output.write_text("PREVIOUS-GOOD")
        cache = ArtifactCache(root=tmp_path / "cache" / "artifacts")

        with pytest.raises(AppDirError, match="appimagetool failed"):
            appimage.build_appimage(
                appdir, output, "x86_64", project_root=tmp_path, cache=cache
            )

        assert output.read_text() == "PREVIOUS-GOOD"
        # No leftover .<name>.tmp-* file beside the preserved distributable.
        assert [p.name for p in output.parent.iterdir()] == [output.name]

    def test_oserror_launching_tool_is_actionable(
        self, tmp_path, monkeypatch, fake_tools
    ):
        # appimagetool itself failing to exec (e.g. no /dev/fuse, bad binary)
        # surfaces as an AppDirError rather than a raw OSError.
        def cannot_exec(cmd, **k):
            raise OSError("Exec format error")

        monkeypatch.setattr(appimage.subprocess, "run", cannot_exec)
        appdir = tmp_path / "app.AppDir"
        appdir.mkdir()
        cache = ArtifactCache(root=tmp_path / "cache" / "artifacts")
        with pytest.raises(AppDirError, match="failed to run appimagetool"):
            appimage.build_appimage(
                appdir,
                tmp_path / "out.AppImage",
                "x86_64",
                project_root=tmp_path,
                cache=cache,
            )

    def test_tool_download_failure_is_translated(self, tmp_path, monkeypatch):
        # A DownloadError acquiring the pinned appimagetool/runtime is reported
        # as an AppDirError (no fake_tools here: we want the fetch to fail).
        from kivyforge.artifacts.download import DownloadError

        def boom(**k):
            raise DownloadError("could not fetch appimagetool: network down")

        monkeypatch.setattr(appimage, "fetch_artifact", boom)
        appdir = tmp_path / "app.AppDir"
        appdir.mkdir()
        cache = ArtifactCache(root=tmp_path / "cache" / "artifacts")
        with pytest.raises(AppDirError, match="network down"):
            appimage.build_appimage(
                appdir,
                tmp_path / "out.AppImage",
                "x86_64",
                project_root=tmp_path,
                cache=cache,
            )
