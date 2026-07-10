""".desktop entry generation."""

from __future__ import annotations

import subprocess

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.linux import AppDirError, desktop

_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.0.0'\ndescription='A demo app'\n"
    "requires-python='>=3.15'\ndependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
    "[tool.kivy.linux.desktop]\ncategories=['Utility','Development']\n"
    "[tool.kivy.linux.python]\nversion='3.15.0'\n"
)


def _config(text=_PYPROJECT):
    return load_config_from_text(text, require_ios=False, require_linux=True)


class TestRenderDesktopEntry:
    def test_fields(self):
        entry = desktop.render_desktop_entry(_config())
        assert "[Desktop Entry]" in entry
        assert "Type=Application" in entry
        assert "Name=My App" in entry
        assert "Comment=A demo app" in entry
        assert "Exec=AppRun %f" in entry
        assert "Icon=org.example.myapp" in entry
        assert "Categories=Utility;Development;" in entry
        assert "StartupWMClass=org.example.myapp" in entry
        assert "Terminal=false" in entry

    def test_default_category(self):
        text = _PYPROJECT.replace(
            "[tool.kivy.linux.desktop]\ncategories=['Utility','Development']\n", ""
        )
        entry = desktop.render_desktop_entry(_config(text))
        assert "Categories=Utility;" in entry

    def test_no_description_omits_comment(self):
        text = _PYPROJECT.replace("description='A demo app'\n", "")
        entry = desktop.render_desktop_entry(_config(text))
        assert "Comment=" not in entry

    def test_write(self, tmp_path):
        dest = tmp_path / "org.example.myapp.desktop"
        desktop.write_desktop_entry(_config(), dest)
        assert dest.read_text().startswith("[Desktop Entry]")


class TestValidateDesktopFile:
    def test_skips_when_tool_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(desktop.shutil, "which", lambda _: None)
        # No tool → no-op (must not raise even for a bogus file).
        desktop.validate_desktop_file(tmp_path / "does-not-matter.desktop")

    def test_passes_on_valid(self, tmp_path, monkeypatch):
        dest = tmp_path / "org.example.myapp.desktop"
        desktop.write_desktop_entry(_config(), dest)
        monkeypatch.setattr(desktop.shutil, "which", lambda _: "/usr/bin/dfv")

        def fake_run(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(desktop.subprocess, "run", fake_run)
        desktop.validate_desktop_file(dest)  # no raise

    def test_hard_fails_on_errors(self, tmp_path, monkeypatch):
        dest = tmp_path / "org.example.myapp.desktop"
        desktop.write_desktop_entry(_config(), dest)
        monkeypatch.setattr(desktop.shutil, "which", lambda _: "/usr/bin/dfv")

        def fake_run(argv, **kw):
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="error: value ... contains an invalid category",
                stderr="",
            )

        monkeypatch.setattr(desktop.subprocess, "run", fake_run)
        with pytest.raises(AppDirError, match="failed desktop-file-validate"):
            desktop.validate_desktop_file(dest)
