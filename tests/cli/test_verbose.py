"""``-v`` / ``-vv`` through the real verbs (issue #64, verbose-output-proposal).

The level travels to Gradle in a ``ContextVar``, so a verb that forgot to set it
would still build -- at level 0, with nobody noticing. The per-verb tests here
are the guard (§3.5): each runs the real ``run_gradle`` with only its
subprocess faked and checks ``--stacktrace`` reached the command.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from kivyforge.cli import main
from kivyforge.cli.build import build
from kivyforge.cli.capabilities import capabilities, render
from kivyforge.cli.package import package
from kivyforge.cli.run import run as run_cmd
from kivyforge.platforms.android import gradlew as gradlew_mod
from kivyforge.report import exit_codes
from kivyforge.report.verbosity import current_verbosity


@pytest.fixture
def seen(monkeypatch):
    """The level ``capabilities`` ran at: the cheapest verb to observe it in."""
    import kivyforge.cli.capabilities as capabilities_mod

    levels: list[int] = []
    real = capabilities_mod.collect

    def collect():
        levels.append(current_verbosity())
        return real()

    monkeypatch.setattr(capabilities_mod, "collect", collect)
    return levels


class TestParsing:
    @pytest.mark.parametrize(
        ("args", "level"),
        [
            ([], 0),
            (["-v"], 1),
            (["--verbose"], 1),
            (["-vv"], 2),
            (["-v", "-v"], 2),
            (["-vvv"], 2),  # above 2 is 2: there is no --debug level
        ],
    )
    def test_flag(self, seen, args, level):
        result = CliRunner().invoke(capabilities, args)
        assert result.exit_code == 0, result.output
        assert seen == [level]

    @pytest.mark.parametrize(
        ("value", "args", "level"),
        [
            ("1", [], 1),
            ("2", [], 2),
            ("2", ["-v"], 1),  # the flag replaces the variable, never adds
            ("", [], 0),
        ],
    )
    def test_environment_variable(self, seen, value, args, level):
        result = CliRunner().invoke(
            capabilities, args, env={"KIVYFORGE_VERBOSE": value}
        )
        assert result.exit_code == 0, result.output
        assert seen == [level]

    @pytest.mark.parametrize("value", ["abc", "-1"])
    def test_a_bad_variable_is_a_usage_error_before_any_work(self, seen, value):
        result = CliRunner().invoke(
            capabilities, ["--json"], env={"KIVYFORGE_VERBOSE": value}
        )
        assert result.exit_code == exit_codes.USAGE_ERROR
        assert seen == []
        assert result.stdout == ""  # click refused it; no envelope was started

    def test_every_verb_accepts_it(self):
        """One flag everywhere, documented as Gradle-only for now (§3.1)."""
        for name, command in main.commands.items():
            assert any(p.name == "verbosity" for p in command.params), name


@pytest.fixture
def gradle(monkeypatch):
    """The real ``run_gradle``, with Gradle itself faked out.

    The ``android`` fixture stubs ``run_gradle`` at the backend; this puts the
    real one back behind that stub, so the verb's level has to arrive through
    the ContextVar to show up in the command.
    """
    from kivyforge.platforms.android import cli
    from tests.platforms.android import test_cli as android_tests

    state: dict = {"ran": [], "returncode": 0}

    def fake_subprocess(cmd, **kw):
        state["ran"].append(cmd)
        return subprocess.CompletedProcess(cmd, state["returncode"])

    def through(dest, tasks, **kw):
        (dest / _wrapper_name()).write_text("", encoding="utf-8")
        gradlew_mod.run_gradle(dest, tasks, **kw)
        android_tests._gradle_output_for(dest, tasks)

    monkeypatch.setattr(gradlew_mod.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(gradlew_mod, "_require_jdk", lambda: None)
    monkeypatch.setattr(
        gradlew_mod, "_install_missing_sdk_packages", lambda events: None
    )
    monkeypatch.setattr(cli, "run_gradle", through)
    return state


def _wrapper_name() -> str:
    return "gradlew.bat" if os.name == "nt" else "gradlew"


def _flags(cmd: list[str]) -> list[str]:
    return [arg for arg in cmd if arg in ("--stacktrace", "--info", "--debug")]


class TestEveryVerbThatRunsGradle:
    def test_build(self, android, gradle):
        result = CliRunner().invoke(build, ["-p", "android", "--debug", "-v"])
        assert result.exit_code == 0, result.output
        assert [_flags(cmd) for cmd in gradle["ran"]] == [["--stacktrace"]]

    def test_package_both_runs(self, android, gradle):
        """lintRelease and the release build: -v applies to every Gradle run."""
        result = CliRunner().invoke(package, ["-p", "android", "-vv"])
        assert result.exit_code == 0, result.output
        assert [_flags(cmd) for cmd in gradle["ran"]] == [
            ["--stacktrace", "--info"],
            ["--stacktrace", "--info"],
        ]

    def test_run(self, android, gradle, monkeypatch):
        """``run`` has no reporting(); its own wrapper sets the level."""
        from kivyforge.platforms.android import cli

        def fake_android_run(project_root, **kw):
            gradlew_mod.run_gradle(project_root / "demoapp-android", ["assembleDebug"])

        (android / "demoapp-android").mkdir()
        (android / "demoapp-android" / _wrapper_name()).write_text("")
        monkeypatch.setattr(cli, "android_run", fake_android_run)
        result = CliRunner().invoke(run_cmd, ["-p", "android", "-v"])
        assert result.exit_code == 0, result.output
        assert [_flags(cmd) for cmd in gradle["ran"]] == [["--stacktrace"]]
        assert "[gradle] in " in result.stderr

    def test_without_the_flag_nothing_is_added(self, android, gradle):
        result = CliRunner().invoke(build, ["-p", "android", "--debug"])
        assert result.exit_code == 0, result.output
        assert [_flags(cmd) for cmd in gradle["ran"]] == [[]]
        assert "[gradle] in " not in result.stderr


class TestJsonIsUnaffected:
    """The echoed command is progress: stderr only, stdout stays one envelope."""

    @pytest.mark.parametrize("flag", ["-v", "-vv"])
    def test_success(self, android, gradle, flag):
        result = CliRunner().invoke(build, ["-p", "android", "--debug", flag, "--json"])
        envelope = json.loads(result.stdout)  # exactly one document
        assert result.exit_code == 0
        assert envelope["ok"] is True
        assert "[gradle] in " in result.stderr
        assert "--stacktrace" in result.stderr
        assert "--stacktrace" not in result.stdout

    def test_gradle_failure(self, android, gradle):
        gradle["returncode"] = 1
        result = CliRunner().invoke(build, ["-p", "android", "--debug", "-v", "--json"])
        envelope = json.loads(result.stdout)
        assert result.exit_code == exit_codes.BUILD_FAILURE
        assert envelope["ok"] is False
        (diagnostic,) = envelope["diagnostics"]
        # The rerun hint is part of the failure message, in both registers.
        assert "To rerun it by hand:" in diagnostic["message"]
        assert "--stacktrace assembleDebug" in diagnostic["message"]
        assert "[gradle] in " in result.stderr


class TestCapabilities:
    def test_every_verb_says_it_accepts_v(self):
        result = CliRunner().invoke(capabilities, ["--json"])
        verbs = json.loads(result.stdout)["data"]["verbs"]
        assert {verb["name"]: verb["verbose"] for verb in verbs} == dict.fromkeys(
            main.commands, True
        )

    def test_only_android_acts_on_it(self):
        result = CliRunner().invoke(capabilities, ["--json"])
        platforms = json.loads(result.stdout)["data"]["platforms"]
        assert [p["name"] for p in platforms if p["verbose"]] == ["android"]

    def test_the_human_report_names_where_it_acts(self):
        from kivyforge.capabilities import collect

        assert "Verbose (-v) acts on: android" in render(collect())
