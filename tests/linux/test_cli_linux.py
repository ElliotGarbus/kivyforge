"""Linux dispatch for build/run (bundler + launch faked)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli import _linux
from kivyforge.cli.build import build
from kivyforge.cli.package import package
from kivyforge.cli.run import run
from kivyforge.lock.linux import dumps
from kivyforge.lock.reader import compute_pyproject_sha256
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)

PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.0.0'\nrequires-python='>=3.15'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
    "[tool.kivy.linux.python]\nversion='3.15.0'\n"
)


def _write_project(fs: str, *, in_sync: bool = True) -> Path:
    root = Path(fs)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')\n")
    lock = WheelRuntimeLock(
        platform="linux",
        requires_python=">=3.15",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.15.0",
            artifacts=(RuntimeArtifact(arch="x86_64", url="https://e/a", sha256="x"),),
            floor="2.17",
        ),
        archs=("x86_64",),
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256=(
            compute_pyproject_sha256(PYPROJECT) if in_sync else "0" * 64
        ),
        tool_kivyforge_schema_version=1,
    )
    (root / "pylock.linux.toml").write_text(dumps(lock))
    return root


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def fake_bundler(monkeypatch):
    """build_appdir just materializes a minimal AppDir; no host tools run."""
    calls = {"arch": []}

    def fake_build(config, lock, project_root, *, arch=None, **k):
        calls["arch"].append(arch)
        appdir = project_root / "build" / "linux" / f"{config.display_name}.AppDir"
        appdir.mkdir(parents=True, exist_ok=True)
        (appdir / "AppRun").write_text("#!/bin/sh\n")
        (appdir / "AppRun").chmod(0o755)
        return appdir

    monkeypatch.setattr(_linux, "build_appdir", fake_build)
    # Linux is the host default only on Linux; force the capability check to pass.
    monkeypatch.setattr(_linux, "_require_linux_host", lambda: None)
    return calls


class TestBuild:
    def test_build_linux(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(build, ["-p", "linux"])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "build" / "linux" / "My App.AppDir").exists()

    def test_stale_lock_fails(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, in_sync=False)
            result = runner.invoke(build, ["-p", "linux"])
            assert result.exit_code != 0
            assert "out of date" in result.output

    def test_missing_lock_fails(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            Path(fs, "pyproject.toml").write_text(PYPROJECT)
            (Path(fs) / "src").mkdir()
            result = runner.invoke(build, ["-p", "linux"])
            assert result.exit_code != 0
            assert "kivyforge lock -p linux" in result.output

    def test_ios_target_flag_rejected(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(build, ["-p", "linux", "--release"])
            assert result.exit_code != 0
            assert "iOS target" in result.output


class TestRun:
    def test_run_builds_and_launches(self, runner, tmp_path, fake_bundler, monkeypatch):
        launched = []
        monkeypatch.setattr(
            _linux.subprocess,
            "run",
            lambda cmd: launched.append(cmd) or subprocess.CompletedProcess(cmd, 0),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(run, ["-p", "linux"])
            assert result.exit_code == 0, result.output
            assert launched and launched[0][0].endswith("/AppRun")

    def test_run_no_build_requires_existing(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(run, ["-p", "linux", "--no-build"])
            assert result.exit_code != 0
            assert "run without --no-build" in result.output


class TestPackage:
    def test_package_folder(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(package, ["-p", "linux", "-f", "folder"])
            assert result.exit_code == 0, result.output
            assert "AppDir folder" in result.output
            assert (Path(fs) / "build" / "linux" / "My App.AppDir").exists()

    def test_package_appimage_default(self, runner, tmp_path, fake_bundler, monkeypatch):
        built = {}

        def fake_appimage(appdir, output, arch, **k):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("APPIMAGE")
            built["output"] = output
            built["arch"] = arch
            return output

        monkeypatch.setattr(_linux, "build_appimage", fake_appimage)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(package, ["-p", "linux"])
            assert result.exit_code == 0, result.output
            expected = Path(fs) / "dist" / "linux" / "myapp-1.0.0-x86_64.AppImage"
            assert expected.exists()
            assert built["arch"] == "x86_64"

    def test_package_rejects_unknown_format(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(package, ["-p", "linux", "-f", "deb"])
            assert result.exit_code != 0
            assert "unknown package format" in result.output
