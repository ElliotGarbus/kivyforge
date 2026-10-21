"""Which entry point an app starts in, and in which form (issue #68).

``[tool.kivy].entry_point`` wins when set: ``"main"`` runs a module as
``__main__``, as it always has, and ``"pkg.app:main"`` calls a function. Unset,
the one ``[project.gui-scripts]`` entry is used; ``[project.scripts]`` never is.
How each platform then starts it is ``tests/bundle/test_entry_launcher.py``.
"""

from __future__ import annotations

import pytest

from kivyforge.config.errors import ConfigError
from kivyforge.config.loader import load_config_from_text

HEAD = """\
[project]
name = "demo"
version = "1.0"
"""


def load(project_tables: str = "", kivy: str = "", *, head: str = HEAD):
    text = head + project_tables + '\n[tool.kivy]\napp_dir = "src"\n' + kivy
    return load_config_from_text(text, require_ios=False)


def rejected(project_tables: str = "", kivy: str = "", **kwargs) -> ConfigError:
    with pytest.raises(ConfigError) as exc:
        load(project_tables, kivy, **kwargs)
    return exc.value


def line_of(text: str, needle: str) -> int:
    return next(i for i, line in enumerate(text.splitlines(), 1) if needle in line)


class TestToolKivyEntryPoint:
    """The bare form is today's behaviour, unchanged."""

    def test_default_is_main(self):
        kivy = load().kivy
        assert (kivy.entry_point, kivy.entry_function) == ("main", None)
        assert kivy.entry_origin == "[tool.kivy].entry_point"
        assert kivy.entry_spec == "main"

    @pytest.mark.parametrize("value", ["main", "pkg.start"])
    def test_bare_module(self, value):
        kivy = load(kivy=f'entry_point = "{value}"\n').kivy
        assert (kivy.entry_point, kivy.entry_function) == (value, None)

    @pytest.mark.parametrize(
        ("value", "module", "function"),
        [
            ("pkg.app:main", "pkg.app", "main"),
            ("app:run", "app", "run"),
            ("pkg.app:App.launch", "pkg.app", "App.launch"),
        ],
    )
    def test_module_function(self, value, module, function):
        kivy = load(kivy=f'entry_point = "{value}"\n').kivy
        assert (kivy.entry_point, kivy.entry_function) == (module, function)
        assert kivy.entry_spec == value
        assert kivy.entry_origin == "[tool.kivy].entry_point"

    @pytest.mark.parametrize(
        "value",
        [
            "pkg.app:",
            ":main",
            "pkg.app:main:x",
            "pkg.app:class",
            "pkg.app:a-b",
            "pkg.app:main [gui]",
            "pkg.app: main",
        ],
    )
    def test_invalid_function(self, value):
        error = rejected(kivy=f'entry_point = "{value}"\n')
        assert error.key_path == "tool.kivy.entry_point"
        assert "entry_point" in error.message

    def test_overrides_gui_scripts(self):
        kivy = load(
            '\n[project.gui-scripts]\na = "pkg.a:main"\nb = "pkg.b:main"\n',
            'entry_point = "main"\n',
        ).kivy
        assert (kivy.entry_point, kivy.entry_function) == ("main", None)


class TestGuiScripts:
    def test_the_only_entry_is_used(self):
        kivy = load('\n[project.gui-scripts]\ndemo = "demo.app:main"\n').kivy
        assert (kivy.entry_point, kivy.entry_function) == ("demo.app", "main")
        assert kivy.entry_origin == "[project.gui-scripts] demo"

    def test_console_scripts_are_not_used(self):
        kivy = load('\n[project.scripts]\ndemo-cli = "demo.cli:main"\n').kivy
        assert (kivy.entry_point, kivy.entry_function) == ("main", None)

    def test_console_scripts_beside_one_gui_script(self):
        kivy = load(
            '\n[project.scripts]\ncli = "demo.cli:main"\n'
            '\n[project.gui-scripts]\ngui = "demo.gui:run"\n'
        ).kivy
        assert (kivy.entry_point, kivy.entry_function) == ("demo.gui", "run")

    def test_extras_and_spaces_are_ignored(self):
        """The entry-points spec: readers ignore spaces around the colon, and
        may ignore extras."""
        kivy = load('\n[project.gui-scripts]\ndemo = "demo.app : main [gui]"\n').kivy
        assert (kivy.entry_point, kivy.entry_function) == ("demo.app", "main")

    def test_attribute_path(self):
        kivy = load('\n[project.gui-scripts]\ndemo = "demo.app:App.launch"\n').kivy
        assert kivy.entry_function == "App.launch"

    def test_several_without_entry_point(self):
        tables = (
            '\n[project.gui-scripts]\nalpha = "demo.a:main"\nbeta = "demo.b:main"\n'
        )
        error = rejected(tables)
        assert "2 entries (alpha, beta)" in error.message
        assert "[tool.kivy].entry_point is not set" in error.message
        assert error.key_path == "tool.kivy.entry_point"
        assert error.line == line_of(HEAD + tables, "[project.gui-scripts]")
        assert error.hint is not None
        assert 'entry_point = "demo.a:main"' in error.hint

    def test_the_suggestion_is_a_valid_entry_point(self):
        """Extras and spaces are fine in a gui-script, not in entry_point."""
        error = rejected(
            '\n[project.gui-scripts]\na = "demo.a : main [gui]"\nb = "demo.b:main"\n'
        )
        assert error.hint is not None
        assert 'entry_point = "demo.a:main"' in error.hint

    def test_module_only_is_not_a_script(self):
        tables = '\n[project.gui-scripts]\ndemo = "demo.app"\n'
        error = rejected(tables)
        assert "names a module, not a function" in error.message
        assert error.line == line_of(HEAD + tables, "demo =")
        assert error.hint is not None
        assert 'entry_point = "demo.app"' in error.hint

    def test_invalid_reference(self):
        error = rejected('\n[project.gui-scripts]\ndemo = "demo-app:main"\n')
        assert "not a valid module:function reference" in error.message
        assert error.key_path == "project.gui-scripts"

    def test_dynamic_gui_scripts_need_entry_point(self):
        """A backend may append to a dynamic gui-scripts table, so one static
        entry is not known to be the only one."""
        head = HEAD + 'dynamic = ["gui-scripts"]\n'
        error = rejected('\n[project.gui-scripts]\ndemo = "demo.app:main"\n', head=head)
        assert "dynamic lists gui-scripts" in error.message

    def test_dynamic_gui_scripts_alone_keep_the_default(self):
        head = HEAD + 'dynamic = ["gui-scripts"]\n'
        kivy = load(head=head).kivy
        assert (kivy.entry_point, kivy.entry_function) == ("main", None)

    def test_dynamic_with_entry_point_is_fine(self):
        head = HEAD + 'dynamic = ["gui-scripts"]\n'
        kivy = load(
            '\n[project.gui-scripts]\ndemo = "demo.app:main"\n',
            'entry_point = "demo.app:main"\n',
            head=head,
        ).kivy
        assert kivy.entry_function == "main"
