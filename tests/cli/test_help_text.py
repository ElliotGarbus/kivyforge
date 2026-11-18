"""Help text is ASCII, and says what the tool is."""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from kivyforge.cli import main


def _help_strings(cmd: click.Command, path: str) -> list[tuple[str, str]]:
    found = [(path, cmd.help or ""), (path, cmd.short_help or "")]
    for param in cmd.params:
        if isinstance(param, click.Option):
            found.append((f"{path} {param.opts[-1]}", param.help or ""))
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            found.extend(_help_strings(sub, f"{path} {name}"))
    return found


@pytest.mark.parametrize(("where", "text"), _help_strings(main, "kivyforge"))
def test_help_is_ascii(where: str, text: str):
    """Stricter than the cp1252 rule, because help is so often piped.

    A redirected stream is decoded by whatever reads it, and on Windows that
    is often the OEM code page: an em dash arrived as ``ΓÇö``. ASCII survives
    every code page.
    """
    assert text.isascii(), f"{where}: {[c for c in text if not c.isascii()]}"


def test_top_level_help_names_every_platform():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for platform in ("Android", "iOS", "macOS", "Windows", "Linux"):
        assert platform in result.output


def test_top_level_help_points_agents_at_capabilities_and_the_guide():
    """An agent that reads only --help still finds where to start."""
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    output = " ".join(result.output.split())
    assert "kivyforge capabilities --json" in output
    assert "'Working with agents' in the kivyforge README" in output


def test_every_verb_but_run_takes_json_as_the_help_says():
    """The help promises --json on every command except run; hold it to that."""
    without = sorted(
        name
        for name, cmd in main.commands.items()
        if not any(
            "--json" in p.opts for p in cmd.params if isinstance(p, click.Option)
        )
    )
    assert without == ["run"]
