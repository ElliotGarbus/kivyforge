"""The ``entry_point`` line ``kivyforge init`` writes, given the gui-scripts.

Since issue #68, an unset ``[tool.kivy].entry_point`` starts the one
``[project.gui-scripts]`` entry, and an explicit one overrides it. So ``init``
writes ``entry_point = "main"`` only for a project without gui-scripts; for one
gui-script it writes none, and for several it names the first. Each case is
checked by loading what ``init`` wrote, the way a build would.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from kivyforge.cli.init import init
from kivyforge.cli.init_writer import (
    GuiScripts,
    entry_point_lines,
    render_android_tables,
    render_kivy_tables,
    render_linux_tables,
    render_macos_tables,
    render_windows_tables,
)
from kivyforge.config.loader import load_config_from_text, script_entry_point

HEAD = '[project]\nname = "myapp"\nversion = "1.0.0"\ndependencies = ["kivy"]\n'


def init_and_load(tmp_path, monkeypatch, project_tables: str, *args: str):
    """Run ``init -p windows`` on a project; return its output and config."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(HEAD + project_tables, encoding="utf-8")
    result = CliRunner().invoke(init, ["-p", "windows", *args])
    assert result.exit_code == 0, result.output
    text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    config = load_config_from_text(text, require_ios=False)
    return result, text, config


class TestLines:
    def test_no_gui_scripts_is_unchanged(self):
        assert entry_point_lines() == [
            'entry_point = "main"  # module run as __main__ at launch (src/main.py)'
        ]

    def test_one_gui_script_writes_no_entry_point(self):
        lines = entry_point_lines(GuiScripts((("myapp", "myapp.app:main"),)))
        assert not any(ln.startswith("entry_point") for ln in lines)
        assert all(ln.startswith("#") for ln in lines)
        assert '[project.gui-scripts] myapp = "myapp.app:main"' in lines[0]

    def test_several_name_the_first(self):
        scripts = GuiScripts((("a", "pkg.a:main"), ("b", "pkg.b:run")))
        (line,) = entry_point_lines(scripts)
        assert line.startswith('entry_point = "pkg.a:main"  #')
        assert "2 entries (a, b)" in line

    def test_dynamic_needs_a_name_even_for_one(self):
        scripts = GuiScripts((("a", "pkg.a:main"),), dynamic=True)
        (line,) = entry_point_lines(scripts)
        assert line.startswith('entry_point = "pkg.a:main"  #')
        assert "dynamic" in line

    def test_written_as_entry_point_takes_it(self):
        """A gui-script may carry extras and spaces; entry_point may not."""
        scripts = GuiScripts((("a", "pkg.a : main [gui]"), ("b", "pkg.b:run")))
        assert entry_point_lines(scripts)[0].startswith('entry_point = "pkg.a:main"')
        assert script_entry_point("pkg.a : main [gui]") == "pkg.a:main"

    def test_quotes_are_escaped(self):
        lines = entry_point_lines(GuiScripts((("q", 'odd"value'),)))
        assert '"odd\\"value"' in lines[0]

    @pytest.mark.parametrize(
        "render",
        [
            render_kivy_tables,
            render_android_tables,
            render_macos_tables,
            render_linux_tables,
            render_windows_tables,
        ],
    )
    def test_every_platform_renders_it(self, render):
        block = render("myapp", gui_scripts=GuiScripts((("m", "myapp.app:main"),)))
        assert not any(ln.startswith("entry_point") for ln in block.splitlines())
        assert "[project.gui-scripts] m" in block


class TestInit:
    def test_no_gui_scripts(self, tmp_path, monkeypatch):
        result, text, config = init_and_load(tmp_path, monkeypatch, "")
        assert 'entry_point = "main"' in text
        assert config.kivy.entry_spec == "main"
        assert "Entry point" not in result.output

    def test_console_scripts_are_not_gui_scripts(self, tmp_path, monkeypatch):
        tables = '\n[project.scripts]\nmyapp-cli = "myapp.cli:main"\n'
        _, text, config = init_and_load(tmp_path, monkeypatch, tables)
        assert 'entry_point = "main"' in text
        assert config.kivy.entry_spec == "main"

    def test_one_gui_script_is_what_starts(self, tmp_path, monkeypatch):
        tables = '\n[project.gui-scripts]\nmyapp = "myapp.app:main"\n'
        result, text, config = init_and_load(tmp_path, monkeypatch, tables)
        assert "\nentry_point" not in text
        assert config.kivy.entry_spec == "myapp.app:main"
        assert config.kivy.entry_origin == "[project.gui-scripts] myapp"
        assert "Entry point: [project.gui-scripts] myapp" in result.output

    def test_several_load_to_the_first(self, tmp_path, monkeypatch):
        tables = (
            "\n[project.gui-scripts]\n"
            'myapp = "myapp.app:main"\nmyapp-admin = "myapp.admin:main"\n'
        )
        result, text, config = init_and_load(tmp_path, monkeypatch, tables)
        assert config.kivy.entry_spec == "myapp.app:main"
        assert config.kivy.entry_origin == "[tool.kivy].entry_point"
        assert "myapp, myapp-admin" in text
        assert "change entry_point" in result.output

    def test_force_keeps_the_shared_table(self, tmp_path, monkeypatch):
        """--force regenerates the overlay only, so an entry_point the user
        set (or left unset) in [tool.kivy] is never rewritten."""
        tables = '\n[project.gui-scripts]\nmyapp = "myapp.app:main"\n'
        init_and_load(tmp_path, monkeypatch, tables)
        pyproject = tmp_path / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8").replace(
            'app_dir = "src"', 'app_dir = "src"\nentry_point = "main"'
        )
        pyproject.write_text(text, encoding="utf-8")
        result = CliRunner().invoke(init, ["-p", "windows", "--force"])
        assert result.exit_code == 0, result.output
        again = pyproject.read_text(encoding="utf-8")
        config = load_config_from_text(again, require_ios=False)
        assert config.kivy.entry_spec == "main"
        assert again.count("[tool.kivy]\n") == 1
