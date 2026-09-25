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
