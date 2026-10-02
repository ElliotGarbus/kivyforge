"""``kivyforge doctor`` platform dispatch (real probe, offline)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.doctor import _resolve_doctor_backend, doctor

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
    assert _resolve_doctor_backend("macos", tmp_path).name == "macos"


def _project(tmp_path, *overlays):
    tables = "".join(f"[tool.kivy.{name}]\n" for name in overlays)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='myapp'\nversion='1.0.0'\n[tool.kivy]\napp_dir='src'\n"
        + tables
    )


@pytest.mark.parametrize(
    ("host", "expected"),
    [("Darwin", "ios"), ("Windows", "windows"), ("Linux", "linux")],
)
def test_resolve_bare_environment_falls_back_to_the_host(
    tmp_path, monkeypatch, host, expected
):
    """No project: iOS only on a Mac, where its Xcode checks can pass."""
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    assert _resolve_doctor_backend(None, tmp_path, host_system=host).name == expected


@pytest.mark.parametrize("host", ["Darwin", "Windows", "Linux"])
def test_resolve_uses_the_only_configured_platform(tmp_path, monkeypatch, host):
    """An Android-only project gets Android checks on every host, not iOS's."""
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    _project(tmp_path, "android")
    assert _resolve_doctor_backend(None, tmp_path, host_system=host).name == "android"


def test_resolve_ambiguous_project_falls_back_to_the_host(tmp_path, monkeypatch):
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    _project(tmp_path, "android", "ios")
    backend = _resolve_doctor_backend(None, tmp_path, host_system="Windows")
    assert backend.name == "windows"


def test_resolve_prefers_the_hosts_own_configured_platform(tmp_path, monkeypatch):
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    _project(tmp_path, "android", "windows")
    backend = _resolve_doctor_backend(None, tmp_path, host_system="Windows")
    assert backend.name == "windows"


def test_resolve_never_reports_ios_checks_off_a_mac(tmp_path, monkeypatch):
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    for host in ("Windows", "Linux"):
        for overlays in ((), ("android",), ("android", "ios")):
            _project(tmp_path, *overlays)
            backend = _resolve_doctor_backend(None, tmp_path, host_system=host)
            assert backend.name != "ios", (host, overlays)


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
