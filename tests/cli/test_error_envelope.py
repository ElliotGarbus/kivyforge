"""A failing ``--json`` run must still produce a parseable envelope.

Before roadmap item 3's wrapper, a bad ``pyproject.toml`` under ``--json`` gave
**empty stdout**: ``ToolchainError`` propagated, click printed ``Error: ...`` to
stderr, and no envelope was written. That is the run an agent most needs to read,
and it was indistinguishable from a crash or from a verb that said nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli._common import ToolchainError, _extract_fix
from kivyforge.cli._output import reporting
from kivyforge.cli.status import status
from kivyforge.platforms import get_platform
from kivyforge.report import diagnostics, exit_codes


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestToolchainErrorStructure:
    def test_defaults_keep_the_historical_behaviour(self):
        """An untriaged raise site must be unspecific, never wrong."""
        exc = ToolchainError("something broke")
        assert exc.exit_code == exit_codes.CONFIG_ERROR
        assert exc.code == diagnostics.UNSPECIFIED

    def test_a_raise_site_can_narrow_both_code_and_exit_status(self):
        exc = ToolchainError(
            "no Android SDK",
            code=diagnostics.HOST_INCAPABLE,
            exit_code=exit_codes.ENVIRONMENT_ERROR,
        )
        assert exc.code == diagnostics.HOST_INCAPABLE
        assert exc.exit_code == exit_codes.ENVIRONMENT_ERROR

    def test_as_diagnostic_is_always_an_error(self):
        found = ToolchainError("broken").as_diagnostic()
        assert found.severity == diagnostics.ERROR
        assert found.message == "broken"


class TestFixExtraction:
    """The backends already end failures with a ``Fix:`` line (roadmap item 1),
    so honouring it gives every existing raise site a remediation for free."""

    def test_a_trailing_fix_line_becomes_the_remediation(self):
        assert _extract_fix("bad thing\n  Fix: run the other command") == (
            "run the other command"
        )

    def test_a_message_without_one_yields_nothing(self):
        assert _extract_fix("bad thing, no advice") == ""

    def test_the_trailing_fix_wins(self):
        """Messages are built by concatenation, so the last word is the one the
        author meant to leave the reader with."""
        assert _extract_fix("Fix: first\nmore text\nFix: second") == "second"

    def test_an_explicit_remediation_beats_the_heuristic(self):
        exc = ToolchainError("bad\n  Fix: parsed", remediation="explicit")
        assert exc.remediation == "explicit"

    def test_an_explicit_empty_remediation_suppresses_extraction(self):
        """``remediation=""`` is a decision; only ``None`` means "go and look"."""
        assert ToolchainError("bad\n  Fix: parsed", remediation="").remediation == ""

    def test_extraction_flows_into_the_diagnostic(self):
        exc = ToolchainError("bad\n  Fix: re-lock it")
        assert exc.as_diagnostic().remediation == "re-lock it"


class TestReportingContextManager:
    def test_a_failure_emits_an_envelope_on_stdout(self, capsys):
        with pytest.raises(ToolchainError):
            with reporting("status", json_out=True, no_color=True):
                raise ToolchainError("no pyproject.toml here")

        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert payload["command"] == "status"
        assert payload["diagnostics"][0]["message"] == "no pyproject.toml here"

    def test_the_exception_is_re_raised_untouched(self, capsys):
        """So click still prints ``Error: ...`` to stderr and still chooses the
        exit code. The failure is reported in both registers, not moved."""
        original = ToolchainError("boom", exit_code=exit_codes.LOCK_DRIFT)
        with pytest.raises(ToolchainError) as caught:
            with reporting("lock", json_out=True, no_color=True):
                raise original
        assert caught.value is original
        assert caught.value.exit_code == exit_codes.LOCK_DRIFT
        capsys.readouterr()

    def test_platform_is_null_when_the_failure_precedes_resolution(self, capsys):
        """Resolving the target reads pyproject.toml, so it is itself one of the
        things that can fail -- which is why the key is nullable."""
        with pytest.raises(ToolchainError):
            with reporting("status", json_out=True, no_color=True):
                raise ToolchainError("cannot even tell which platform")
        assert json.loads(capsys.readouterr().out)["platform"] is None

    def test_a_platform_learned_mid_run_reaches_the_envelope(self, capsys):
        with pytest.raises(ToolchainError):
            with reporting("status", json_out=True, no_color=True) as report:
                report.platform = "android"
                raise ToolchainError("failed after resolving")
        assert json.loads(capsys.readouterr().out)["platform"] == "android"

    def test_nothing_is_written_to_stdout_without_json(self, capsys):
        """Human mode already had a perfectly good error path: click's."""
        with pytest.raises(ToolchainError):
            with reporting("status", json_out=False, no_color=True):
                raise ToolchainError("boom")
        assert capsys.readouterr().out == ""

    def test_a_clean_run_is_left_entirely_alone(self, capsys):
        with reporting("status", json_out=True, no_color=True) as report:
            report.emit(ok=True, data={"fine": True})
        assert json.loads(capsys.readouterr().out)["ok"] is True

    def test_an_unexpected_exception_is_not_swallowed(self, capsys):
        """Only ``ToolchainError`` means "an expected failure". A ``KeyError`` is
        a bug, and a bug must keep its traceback rather than be dressed up as a
        clean diagnostic."""
        with pytest.raises(KeyError):
            with reporting("status", json_out=True, no_color=True):
                raise KeyError("bug")
        assert capsys.readouterr().out == ""


class TestThroughTheRealCli:
    def test_status_json_reports_a_missing_pyproject(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(status, ["-p", "linux", "--json"])
        assert result.exit_code == exit_codes.CONFIG_ERROR
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["diagnostics"][0]["code"] == diagnostics.UNSPECIFIED
        assert "pyproject.toml" in payload["diagnostics"][0]["message"]

    def test_the_human_error_still_goes_to_stderr(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(status, ["-p", "linux", "--json"])
        assert "Error:" in result.stderr

    def test_a_backend_failure_after_resolution_names_the_platform(
        self, runner, tmp_path, monkeypatch
    ):
        def boom(root):
            raise ToolchainError("backend said no")

        monkeypatch.setattr(get_platform("linux"), "status", boom)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(
                '[project]\nname = "myapp"\nversion = "1.0.0"\n'
            )
            result = runner.invoke(status, ["-p", "linux", "--json"])
        assert json.loads(result.stdout)["platform"] == "linux"

    def test_a_bad_flag_stays_clicks_usage_error(self, runner, tmp_path):
        """Raised during parsing, before any verb body runs, so no envelope is
        possible -- and ``2`` is exactly how a caller tells the two apart."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(status, ["--bogus-flag", "--json"])
        assert result.exit_code == exit_codes.USAGE_ERROR
        assert result.stdout == ""
