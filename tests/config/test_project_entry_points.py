"""``[project]`` entry points and name, as the loader reads and rejects them.

docs/design/dev/package-metadata-proposal.md section 2.1: kivyforge writes the
app's ``entry_points.txt`` and ``METADATA`` from these, so it applies the rules
the specs give and every build backend enforces. Each is a config error at the
line that breaks it. What the files then contain is
``tests/bundle/test_app_metadata.py``.
"""

from __future__ import annotations

import pytest

from kivyforge.config.errors import ConfigError
from kivyforge.config.loader import load_config_from_text, load_declared_project
from kivyforge.config.model import DEFAULT_BUILD_BACKEND, EntryPoint

HEAD = """\
[project]
name = "demo"
version = "1.0"
"""

KIVY = """
[tool.kivy]
app_dir = "src"
"""


def load(project_tables: str, *, head: str = HEAD, before: str = ""):
    return load_config_from_text(
        before + head + project_tables + KIVY, require_ios=False
    )


def rejected(project_tables: str, **kwargs) -> ConfigError:
    with pytest.raises(ConfigError) as exc:
        load(project_tables, **kwargs)
    return exc.value


def line_of(text: str, needle: str) -> int:
    return next(i for i, line in enumerate(text.splitlines(), 1) if needle in line)


class TestRead:
    def test_none_declared(self):
        config = load("")
        assert config.project.entry_points == ()
        assert config.project.dynamic == ()

    def test_scripts_and_gui_scripts_are_their_groups(self):
        config = load(
            '[project.scripts]\ncli = "demo.cli:main"\n'
            '[project.gui-scripts]\ngui = "demo.gui:main"\n'
        )
        assert config.project.entry_points == (
            EntryPoint("console_scripts", "cli", "demo.cli:main"),
            EntryPoint("gui_scripts", "gui", "demo.gui:main"),
        )

    def test_groups_in_declared_order_values_as_written(self):
        config = load(
            '[project.entry-points."demo.plugins"]\n'
            'MyPlugin = "demo.plugins:Mine"\n'
            'fancy = "demo.extra:Fancy [fancy]"\n'
            "[project.entry-points.pytest11]\n"
            'demo = "demo.pytest_plugin"\n'
        )
        assert config.project.entry_points == (
            EntryPoint("demo.plugins", "MyPlugin", "demo.plugins:Mine"),
            EntryPoint("demo.plugins", "fancy", "demo.extra:Fancy [fancy]"),
            EntryPoint("pytest11", "demo", "demo.pytest_plugin"),
        )

    def test_non_ascii_names(self):
        config = load('[project.entry-points."démo.plugins"]\n"ñame" = "démo:Ñ"\n')
        assert config.project.entry_points == (
            EntryPoint("démo.plugins", "ñame", "démo:Ñ"),
        )

    def test_an_empty_table_declares_none(self):
        assert load("[project.entry-points]\n").project.entry_points == ()

    def test_dynamic_is_kept(self):
        head = HEAD + 'dynamic = ["entry-points", "scripts"]\n'
        assert load("", head=head).project.dynamic == ("entry-points", "scripts")

    @pytest.mark.parametrize(
        ("build_system", "backend"),
        [
            ("", DEFAULT_BUILD_BACKEND),
            ('[build-system]\nrequires = ["setuptools"]\n', DEFAULT_BUILD_BACKEND),
            (
                '[build-system]\nbuild-backend = "hatchling.build"\n',
                "hatchling.build",
            ),
        ],
    )
    def test_build_backend(self, build_system, backend):
        assert load("", before=build_system).project.build_backend == backend

    def test_the_verbs_read_it_without_the_rest(self, tmp_path):
        """What build/package/run check before any backend runs."""
        (tmp_path / "pyproject.toml").write_text(
            HEAD + '[project.scripts]\ncli = "demo:main"\n' + KIVY,
            encoding="utf-8",
        )
        project, app_dir = load_declared_project(tmp_path / "pyproject.toml")
        assert project.entry_points == (
            EntryPoint("console_scripts", "cli", "demo:main"),
        )
        assert app_dir == "src"

    def test_the_verbs_tolerate_no_tool_kivy(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(HEAD, encoding="utf-8")
        assert load_declared_project(tmp_path / "pyproject.toml")[1] is None


class TestRejected:
    @pytest.mark.parametrize(
        ("group", "instead"),
        [("console_scripts", "scripts"), ("gui_scripts", "gui-scripts")],
    )
    def test_reserved_groups(self, group, instead):
        tables = f'[project.entry-points.{group}]\ncli = "demo:main"\n'
        error = rejected(tables)
        assert group in error.message
        assert f"[project.{instead}]" in (error.hint or "")
        assert error.line == line_of(HEAD + tables, "entry-points")

    def test_nested_tables(self):
        # The usual cause: a dotted group name left unquoted.
        tables = '[project.entry-points.demo.plugins]\nmine = "demo:Mine"\n'
        error = rejected(tables)
        assert "nest" in error.message
        assert '"demo.plugins"' in (error.hint or "")
        assert error.line == line_of(HEAD + tables, "entry-points")

    @pytest.mark.parametrize("group", ["demo plugins", "demo..plugins", ".demo", "a-b"])
    def test_group_names(self, group):
        tables = f'[project.entry-points."{group}"]\nmine = "demo:Mine"\n'
        error = rejected(tables)
        assert repr(group) in error.message
        assert error.line == line_of(HEAD + tables, "entry-points")

    @pytest.mark.parametrize(
        ("name", "why"),
        [
            ("a=b", "'='"),
            ("[a", "'['"),
            (" lead", "whitespace"),
            ("trail ", "whitespace"),
        ],
    )
    def test_entry_point_names(self, name, why):
        tables = f'[project.entry-points."demo.plugins"]\n"{name}" = "demo:Mine"\n'
        error = rejected(tables)
        assert repr(name) in error.message
        assert why in error.message
        assert error.line == line_of(HEAD + tables, f'"{name}"')

    def test_script_names_too(self):
        tables = '[project.scripts]\n"a=b" = "demo:main"\n'
        error = rejected(tables)
        assert "'a=b'" in error.message
        assert error.line == line_of(HEAD + tables, '"a=b"')

    @pytest.mark.parametrize(
        "tables",
        [
            'entry-points = "demo:main"\n',
            "[project.scripts]\ncli = 1\n",
            '[project.scripts]\ncli = ""\n',
            '[project.entry-points]\n"demo.plugins" = "demo:Mine"\n',
        ],
        ids=["not-a-table", "not-a-string", "empty", "group-not-a-table"],
    )
    def test_shapes(self, tables):
        if tables.startswith("entry-points"):
            error = rejected("", head=HEAD + tables)
        else:
            error = rejected(tables)
        assert error.key_path is not None
        assert error.key_path.startswith("project.")

    def test_a_line_break_cannot_be_written(self):
        tables = '[project.scripts]\ncli = "demo:main\\nother = x:y"\n'
        error = rejected(tables)
        assert "line break" in error.message

    @pytest.mark.parametrize(
        "name", ["my app", "-demo", "demo-", "demo!", "démo", "demo\n", "_demo"]
    )
    def test_project_names(self, name):
        head = f'[project]\nname = "{name.replace(chr(10), chr(92) + "n")}"\n'
        head += 'version = "1.0"\n'
        error = rejected("", head=head)
        assert "[project].name" in error.message
        assert error.line == 2

    @pytest.mark.parametrize("name", ["a", "A1", "my-app", "My.App_2", "x" * 80])
    def test_valid_project_names(self, name):
        head = f'[project]\nname = "{name}"\nversion = "1.0"\n'
        assert load("", head=head).project.name == name
