"""What ``kivyforge init`` writes, per platform: the template contract."""

from __future__ import annotations

import tomllib

import pytest
from click.testing import CliRunner

from kivyforge.cli.init import init
from kivyforge.cli.init_writer import (
    render_android_tables,
    render_kivy_tables,
    render_linux_tables,
    render_macos_tables,
    render_windows_tables,
)

_PROJECT = '[project]\nname = "myapp"\nversion = "1.0.0"\ndependencies = ["kivy"]\n\n'
_DESKTOP = [render_macos_tables, render_linux_tables, render_windows_tables]
_INDEX = "kivy-mobile-wheels"


def _active(block: str) -> list[str]:
    """The lines that are TOML, not comments."""
    return [ln for ln in block.splitlines() if ln.strip() and not ln.startswith("#")]


@pytest.mark.parametrize("render", _DESKTOP)
class TestDesktopTemplates:
    def test_orientation_is_not_written(self, render):
        # Only the iOS and Android backends read it.
        assert "orientation" not in render("myapp", has_kivy=True)

    def test_exclude_is_optional_not_applied(self, render):
        block = render("myapp", has_kivy=True)
        assert not any(ln.startswith("exclude") for ln in _active(block))
        assert "# exclude = [" in block
        assert "UrlRequest" in block

    def test_parses(self, render):
        tomllib.loads(_PROJECT + render("myapp", has_kivy=True))


@pytest.mark.parametrize("render", [render_kivy_tables, render_android_tables])
class TestMobileTemplates:
    def test_orientation_is_written(self, render):
        assert 'orientation = ["portrait"]' in render("myapp", has_kivy=True)

    def test_exclude_is_applied(self, render):
        block = render("myapp", has_kivy=True)
        assert "exclude = [" in _active(block)

    def test_index_is_active_when_kivy_is_a_dependency(self, render):
        block = render("myapp", has_kivy=True)
        assert any(
            ln.startswith("extra_index_urls") and _INDEX in ln for ln in _active(block)
        )

    def test_index_is_only_a_hint_without_kivy(self, render):
        block = render("myapp", has_kivy=False)
        assert not any(ln.startswith("extra_index_urls") for ln in _active(block))
        assert "# extra_index_urls" in block and _INDEX in block

    def test_parses(self, render):
        tomllib.loads(_PROJECT + render("myapp", has_kivy=True))


def test_every_shared_key_is_documented():
    block = render_kivy_tables("myapp")
    for key in ("display_name", "app_dir", "entry_point", "orientation"):
        line = next(ln for ln in block.splitlines() if ln.startswith(key))
        assert "#" in line, f"{key} has no comment"


def test_linux_template_mentions_raspberry_pi():
    block = render_linux_tables("myapp")
    assert "aarch64" in block and "Raspberry Pi" in block
    assert 'archs = ["x86_64"]' in block  # the default is unchanged


def test_mobile_platform_seeded_first_so_orientation_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(_PROJECT, encoding="utf-8")
    result = CliRunner().invoke(init, ["-p", "linux", "-p", "android"])
    assert result.exit_code == 0, result.output
    text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text)["tool"]["kivy"]["orientation"] == ["portrait"]
