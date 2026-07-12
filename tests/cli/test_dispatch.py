"""Phase 0 — CLI dispatch and help."""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from kivyforge.cli import main

REAL_VERBS = [
    "init",
    "lock",
    "build",
    "run",
    "open",
    "upgrade",
    "clean",
    "status",
    "doctor",
]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestTopLevel:
    def test_help_lists_every_real_verb(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        for verb in REAL_VERBS:
            assert verb in result.output, f"{verb} missing from --help"

    def test_version(self, runner):
        from kivyforge import __version__

        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestRealVerbDispatch:
    @pytest.mark.parametrize("verb", REAL_VERBS)
    def test_verb_is_dispatchable(self, runner, verb):
        # Every real verb resolves and prints per-verb help with exit 0.
        result = runner.invoke(main, [verb, "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    @pytest.mark.parametrize("verb", REAL_VERBS)
    def test_verb_resolves_to_command(self, runner, verb):
        # Each verb resolves to a real click command (not "no such command").
        cmd = main.get_command(click.Context(main), cmd_name=verb)
        assert cmd is not None


class TestVerbErrors:
    def test_unknown_verb_errors(self, runner):
        result = runner.invoke(main, ["frobnicate"])
        assert result.exit_code != 0
