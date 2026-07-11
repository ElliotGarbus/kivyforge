"""CLI platform glue: overlay detection + resolution error surfacing."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli._common import ToolchainError
from kivyforge.cli._platform import configured_platforms, resolve_target
from kivyforge.cli.lock import lock
from kivyforge.cli.run import run

PYPROJECT_IOS = (
    textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"

        [tool.kivy]
        app_dir = "src"

        [tool.kivy.ios]
        schema_version = 1
        bundle_id = "org.example.myapp"
        """
    ).strip()
    + "\n"
)


def test_configured_platforms_detects_ios(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(PYPROJECT_IOS)
    assert configured_platforms(p) == {"ios"}


def test_configured_platforms_empty_without_overlay(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "x"\nversion = "1"\n')
    assert configured_platforms(p) == set()


def test_configured_platforms_missing_file(tmp_path):
    assert configured_platforms(tmp_path / "nope.toml") == set()


def test_resolve_target_success_via_env(tmp_path, monkeypatch):
    # KIVYFORGE_PLATFORM=ios is set by the autouse conftest fixture.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_IOS)
    backend, root = resolve_target(None)
    assert backend.name == "ios"
    assert (root / "pyproject.toml").is_file()


def test_resolve_target_no_pyproject(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ToolchainError, match="no pyproject.toml"):
        resolve_target(None)


def test_resolve_target_unresolved_is_actionable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_IOS)
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    with pytest.raises(ToolchainError, match="no target platform"):
        resolve_target(None)


def test_resolve_target_default_verb_is_build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_IOS)
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    with pytest.raises(ToolchainError, match="kivyforge build --platform"):
        resolve_target(None)


def test_resolve_target_passes_verb_through_to_error(tmp_path, monkeypatch):
    # Regression: every CLI command used to see "kivyforge build ..." in this
    # error even when it wasn't `build` that failed to resolve.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_IOS)
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    with pytest.raises(ToolchainError, match="kivyforge lock --platform"):
        resolve_target(None, verb="lock")


def test_lock_cli_unresolved_error_names_lock_not_build(tmp_path, monkeypatch):
    """End-to-end regression for the reported bug: `kf lock`'s error must
    suggest `kivyforge lock --platform ...`, not `kivyforge build ...`."""
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        (Path(fs) / "pyproject.toml").write_text(PYPROJECT_IOS)
        result = runner.invoke(lock, [])
    assert result.exit_code != 0
    assert "kivyforge lock --platform" in result.output
    assert "kivyforge build --platform" not in result.output


def test_run_cli_unresolved_error_names_run_not_build(tmp_path, monkeypatch):
    monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        (Path(fs) / "pyproject.toml").write_text(PYPROJECT_IOS)
        result = runner.invoke(run, [])
    assert result.exit_code != 0
    assert "kivyforge run --platform" in result.output
