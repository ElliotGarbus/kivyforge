"""CLI platform glue: overlay detection + resolution error surfacing."""

from __future__ import annotations

import textwrap

import pytest

from kivyforge.cli._common import ToolchainError
from kivyforge.cli._platform import configured_platforms, resolve_target

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
