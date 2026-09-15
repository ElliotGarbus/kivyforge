"""``kivyforge status --json`` and the shared renderer (roadmap item 3).

Two halves: :func:`kivyforge.cli.status.render` is a pure function over a
:class:`~kivyforge.status.StatusReport`, so the human layout is tested without a
project on disk; the CLI tests drive the real command with a faked backend to
cover the envelope, the lock diagnostics and the exit code.

That the human output did not change is covered where it already was -- the
per-platform status tests in ``tests/platforms/*`` and
``tests/cli/test_status_clean_upgrade.py`` assert exact lines like
``"Lock:       in sync"`` and still pass unmodified.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.status import render, status
from kivyforge.platforms import get_platform
from kivyforge.report import diagnostics, exit_codes
from kivyforge.status import BuildArtifact, LockState, LockStatus, StatusReport

MINIMAL_PYPROJECT = '[project]\nname = "myapp"\nversion = "1.0.0"\n'


def make_report(
    *,
    platform: str = "linux",
    lock_state: LockState = LockState.IN_SYNC,
    relock: str = "kivyforge lock -p linux",
    artifacts: tuple[BuildArtifact, ...] | None = None,
    extra: tuple[tuple[str, str], ...] = (),
) -> StatusReport:
    if artifacts is None:
        artifacts = (BuildArtifact(path=Path("build/linux/My App.AppDir")),)
    return StatusReport(
        platform=platform,
        app_name="My App",
        app_id="org.example.myapp",
        python_version="3.13.14",
        lock=LockStatus(lock_state, relock),
        artifacts=artifacts,
        extra=extra,
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(tmp_path, runner):
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        (Path(fs) / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
        yield Path(fs)


@pytest.fixture
def backend(monkeypatch, project):
    """Point ``status`` at a faked Linux backend returning a report we choose."""

    def install(report: StatusReport) -> None:
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        monkeypatch.setattr(get_platform("linux"), "status", lambda root: report)

    monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
    return install


class TestRenderLayout:
    def test_the_four_standard_rows_line_up(self):
        assert render(make_report()) == [
            "App:        My App  (org.example.myapp)",
            "Python:     3.13.14",
            "Lock:       in sync",
            "Build:      not built",
        ]

    def test_a_single_unlabelled_artifact_shares_the_build_row(self):
        """Four of the five platforms produce one artifact, and an indented list
        of one reads badly."""
        assert render(make_report())[-1].startswith("Build:      ")

    def test_several_artifacts_open_an_indented_list(self):
        lines = render(
            make_report(
                artifacts=(
                    BuildArtifact(path=Path("a"), label="simulator (arm64)"),
                    BuildArtifact(path=Path("b"), label="device"),
                )
            )
        )
        assert lines[-3] == "Build:"
        assert lines[-2] == "  simulator (arm64)   not built"
        assert lines[-1] == "  device              not built"

    def test_extra_rows_sit_between_python_and_lock(self):
        """Where Android has always put its Kivy generation and ABI list."""
        lines = render(
            make_report(extra=(("Kivy/SDL", "kivy 2.3.1"), ("ABIs", "arm64-v8a")))
        )
        assert lines[1].startswith("Python:")
        assert lines[2] == "Kivy/SDL:   kivy 2.3.1"
        assert lines[3] == "ABIs:       arm64-v8a"
        assert lines[4].startswith("Lock:")

    def test_a_problem_lock_carries_its_command_inline(self):
        lines = render(make_report(lock_state=LockState.OUT_OF_DATE))
        assert "Lock:       out of date (run `kivyforge lock -p linux`)" in lines

    def test_no_row_has_trailing_whitespace(self):
        """``Build:`` with an empty value must not become ``"Build:      "``."""
        lines = render(make_report(artifacts=()))
        assert all(line == line.rstrip() for line in lines)


class TestEnvelope:
    def test_stdout_is_nothing_but_the_envelope(self, runner, backend):
        backend(make_report())
        result = runner.invoke(status, ["--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["command"] == "status"
        assert payload["platform"] == "linux"
        assert payload["ok"] is True

    def test_the_human_report_is_suppressed(self, runner, backend):
        backend(make_report())
        result = runner.invoke(status, ["--json"])
        assert "App:" not in result.stdout

    def test_data_carries_identity_python_lock_and_artifacts(self, runner, backend):
        backend(make_report())
        data = json.loads(runner.invoke(status, ["--json"]).stdout)["data"]
        assert data["app"] == {"name": "My App", "id": "org.example.myapp"}
        assert data["python"] == "3.13.14"
        assert data["lock"]["in_sync"] is True
        assert data["artifacts"][0]["built"] is False

    def test_artifact_paths_are_reported(self, runner, backend):
        """Agent-friendliness point 2: the build layout is deterministic, but an
        agent should not have to know it from the docs."""
        backend(make_report())
        data = json.loads(runner.invoke(status, ["--json"]).stdout)["data"]
        assert data["artifacts"][0]["path"] == "build/linux/My App.AppDir"


class TestLockDiagnostics:
    """A stale lock is the one thing ``status`` reports that an agent must act on."""

    @pytest.mark.parametrize(
        "state,code",
        [
            (LockState.OUT_OF_DATE, diagnostics.LOCK_DRIFT),
            (LockState.MISSING, diagnostics.LOCK_MISSING),
            (LockState.UNREADABLE, diagnostics.LOCK_UNREADABLE),
        ],
    )
    def test_each_problem_state_has_its_own_code(self, runner, backend, state, code):
        backend(make_report(lock_state=state))
        found = json.loads(runner.invoke(status, ["--json"]).stdout)["diagnostics"]
        assert [d["code"] for d in found] == [code]

    def test_an_in_sync_lock_produces_no_diagnostic(self, runner, backend):
        """The expected case is not news."""
        backend(make_report())
        assert json.loads(runner.invoke(status, ["--json"]).stdout)["diagnostics"] == []

    def test_the_relock_command_is_the_remediation_field(self, runner, backend):
        backend(make_report(lock_state=LockState.OUT_OF_DATE))
        found = json.loads(runner.invoke(status, ["--json"]).stdout)["diagnostics"]
        assert found[0]["remediation"] == "kivyforge lock -p linux"

    def test_drift_is_a_warning_and_does_not_fail_the_command(self, runner, backend):
        """``status`` is read-only: a stale lock is news about the project, not a
        failure of the verb, and it has never affected the exit code."""
        backend(make_report(lock_state=LockState.OUT_OF_DATE))
        result = runner.invoke(status, ["--json"])
        assert result.exit_code == exit_codes.SUCCESS
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["diagnostics"][0]["severity"] == diagnostics.WARNING


class TestHumanMode:
    def test_the_report_goes_to_stdout(self, runner, backend):
        backend(make_report())
        result = runner.invoke(status, [])
        assert result.exit_code == 0, result.output
        assert "App:        My App  (org.example.myapp)" in result.stdout

    def test_no_json_appears_without_the_flag(self, runner, backend):
        backend(make_report())
        assert '"schema"' not in runner.invoke(status, []).stdout

    def test_no_color_leaves_no_escapes(self, runner, backend, monkeypatch):
        monkeypatch.setenv("FORCE_COLOR", "1")
        backend(make_report())
        assert "\x1b" not in runner.invoke(status, ["--no-color"]).stdout
