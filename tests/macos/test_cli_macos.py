"""macOS dispatch for build/run/package (bundler + launch faked)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli import _macos
from kivyforge.cli.build import build
from kivyforge.cli.package import package
from kivyforge.cli.run import run
from kivyforge.lock.macos import dumps
from kivyforge.lock.reader import compute_pyproject_sha256
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)

PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.0.0'\nrequires-python='>=3.14'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\n"
    "archs=['arm64','x86_64']\n"
    "[tool.kivy.macos.python]\nversion='3.14.5'\n"
)


def _write_project(fs: str, *, in_sync: bool = True) -> Path:
    root = Path(fs)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')\n")
    lock = WheelRuntimeLock(
        platform="macos",
        requires_python=">=3.14",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.14.5",
            artifacts=(
                RuntimeArtifact(arch="arm64", url="https://e/a", sha256="x"),
                RuntimeArtifact(arch="x86_64", url="https://e/i", sha256="y"),
            ),
        ),
        archs=("arm64", "x86_64"),
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256=(compute_pyproject_sha256(PYPROJECT) if in_sync else "0" * 64),
        tool_kivyforge_schema_version=1,
    )
    (root / "pylock.macos.toml").write_text(dumps(lock))
    return root


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def fake_bundler(monkeypatch):
    """build_app_bundle just materializes a minimal .app; no host tools run."""
    calls = {"arch": [], "sign": []}

    def fake_build(config, lock, project_root, *, arch=None, sign=True, **k):
        calls["arch"].append(arch)
        calls["sign"].append(sign)
        app = project_root / "build" / "macos" / f"{config.display_name}.app"
        (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
        (app / "Contents" / "MacOS" / config.app_slug).write_text("#!/bin/sh\n")
        return app

    monkeypatch.setattr(_macos, "build_app_bundle", fake_build)
    # macOS is the host default only on Darwin; force the capability check to pass.
    monkeypatch.setattr(_macos, "_require_macos_host", lambda: None)
    return calls


class TestBuild:
    def test_build_macos(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(build, ["-p", "macos"])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "build" / "macos" / "My App.app").exists()

    def test_build_arch_subset(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(build, ["-p", "macos", "--arch", "arm64"])
            assert result.exit_code == 0, result.output
            assert fake_bundler["arch"] == ["arm64"]

    def test_stale_lock_fails(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, in_sync=False)
            result = runner.invoke(build, ["-p", "macos"])
            assert result.exit_code != 0
            assert "out of date" in result.output

    def test_missing_lock_fails(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            Path(fs, "pyproject.toml").write_text(PYPROJECT)
            (Path(fs) / "src").mkdir()
            result = runner.invoke(build, ["-p", "macos"])
            assert result.exit_code != 0
            assert "kivyforge lock -p macos" in result.output

    def test_ios_target_flag_rejected_on_macos(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(build, ["-p", "macos", "--release"])
            assert result.exit_code != 0
            assert "iOS target" in result.output


class TestRun:
    def test_run_builds_and_launches(self, runner, tmp_path, fake_bundler, monkeypatch):
        launched = []
        monkeypatch.setattr(
            _macos.subprocess,
            "run",
            lambda cmd: launched.append(cmd) or subprocess.CompletedProcess(cmd, 0),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(run, ["-p", "macos"])
            assert result.exit_code == 0, result.output
            assert launched and launched[0][0].endswith("/MacOS/myapp")

    def test_run_no_build_requires_existing(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(run, ["-p", "macos", "--no-build"])
            assert result.exit_code != 0
            assert "run without --no-build" in result.output


class TestPackage:
    def test_package_app(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(package, ["-p", "macos"])
            assert result.exit_code == 0, result.output
            assert "ad-hoc signed" in result.output
            assert fake_bundler["sign"] == [True]

    def test_package_rejects_ipa_format(self, runner, tmp_path, fake_bundler):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(package, ["-p", "macos", "-f", "ipa"])
            assert result.exit_code != 0
            assert "unknown package format" in result.output
