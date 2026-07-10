"""``kivyforge package`` — format resolution + iOS release path (subprocess mocked)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli._common import ToolchainError
from kivyforge.cli.package import _resolve_format, package
from kivyforge.platforms.ios import IosPlatform
from kivyforge.platforms.ios import cli as ios_cli
from kivyforge.platforms.ios.lock import (
    Lockfile,
    PythonXcframework,
    compute_pyproject_sha256,
    dumps,
)

PYPROJECT = (
    textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.15"
        dependencies = ["kivy"]

        [tool.kivy]
        app_dir = "src"

        [tool.kivy.ios]
        schema_version = 1
        bundle_id = "org.example.myapp"
        deployment_target = "13.0"

        [tool.kivy.ios.python]
        version = "3.15.0"
        """
    ).strip()
    + "\n"
)


def _write_project(fs: str) -> Path:
    root = Path(fs)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')\n")
    lock = Lockfile(
        requires_python=">=3.15",
        packages=(),
        python_xcframework=PythonXcframework(
            version="3.15.0", url="https://example/py.tar.gz", sha256="c" * 64
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256=compute_pyproject_sha256(PYPROJECT),
        tool_kivyforge_schema_version=1,
    )
    (root / "pylock.ios.toml").write_text(dumps(lock))
    return root


class _Proc:
    returncode = 0
    stdout = ""
    stderr = ""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def mock_build(monkeypatch):
    monkeypatch.setattr(ios_cli, "collect_artifacts", lambda *a, **k: None)
    monkeypatch.setattr(ios_cli, "default_simulator_arch", lambda: "arm64")
    monkeypatch.setattr(ios_cli, "run_command", lambda *a, **k: _Proc())


class TestFormatResolution:
    def test_default_is_ipa(self):
        assert _resolve_format(IosPlatform(), None) == "ipa"

    def test_explicit_valid(self):
        assert _resolve_format(IosPlatform(), "ipa") == "ipa"

    def test_unknown_format_errors(self):
        with pytest.raises(ToolchainError, match="unknown package format"):
            _resolve_format(IosPlatform(), "app")


class TestPackageIos:
    def test_release_writes_export_options(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(package, ["--team-id", "ABCDE12345"])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "myapp-ios" / "build" / "ExportOptions.plist").is_file()

    def test_unknown_format_via_cli(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(package, ["-f", "app", "--team-id", "ABCDE12345"])
            assert result.exit_code != 0
            assert "unknown package format" in result.output

    def test_release_without_team_id_errors(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs)
            result = runner.invoke(package, [])
            assert result.exit_code != 0
