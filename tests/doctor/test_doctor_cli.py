"""``kivyforge doctor`` platform dispatch (real probe, offline)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.doctor import _resolve_doctor_platform, doctor

MACOS_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.0.0'\n"
    "[tool.kivy]\napp_dir='src'\n"
    "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\n"
    "archs=['arm64']\n"
    "[tool.kivy.macos.python]\nversion='3.14.5'\n"
)

LINUX_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.0.0'\n"
    "[tool.kivy]\napp_dir='src'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
    "archs=['x86_64']\n"
    "[tool.kivy.linux.python]\nversion='3.14.5'\n"
)


@pytest.fixture
def runner():
    return CliRunner()


def test_resolve_prefers_cli_platform(tmp_path):
    assert _resolve_doctor_platform("macos", tmp_path) == "macos"


def test_resolve_falls_back_to_ios(tmp_path, monkeypatch):
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    assert _resolve_doctor_platform(None, tmp_path) == "ios"


def test_doctor_macos_project_header(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        Path(fs, "pyproject.toml").write_text(MACOS_PYPROJECT)
        (Path(fs) / "src").mkdir()
        result = runner.invoke(doctor, ["-p", "macos", "--offline"])
        assert "kivyforge doctor (macos, project mode)" in result.output
        assert "Host is macOS" in result.output


def test_doctor_macos_environment_mode(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(doctor, ["-p", "macos", "--offline"])
        assert "(macos, environment mode)" in result.output


def test_doctor_linux_project_header(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        Path(fs, "pyproject.toml").write_text(LINUX_PYPROJECT)
        (Path(fs) / "src").mkdir()
        result = runner.invoke(doctor, ["-p", "linux", "--offline"])
        assert "kivyforge doctor (linux, project mode)" in result.output
        assert "Host is Linux" in result.output


def test_doctor_linux_environment_mode(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(doctor, ["-p", "linux", "--offline"])
        assert "(linux, environment mode)" in result.output
