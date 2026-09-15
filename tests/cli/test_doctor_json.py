"""``kivyforge doctor --json`` end to end (roadmap item 3).

Doctor is the first verb through the report seam, and the most useful one for an
agent: it answers "is a build even possible here" before anything expensive is
attempted. These tests drive the real CLI with a faked backend, so they cover the
wiring -- envelope, diagnostics, summary, exit code -- rather than re-testing the
checks themselves, which ``tests/doctor`` and ``tests/platforms/*/test_doctor.py``
already own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.doctor import doctor
from kivyforge.doctor import CheckResult, Status
from kivyforge.platforms import get_platform
from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.envelope import SCHEMA_VERSION

MINIMAL_PYPROJECT = '[project]\nname = "myapp"\nversion = "1.0.0"\n'

ALL_PLATFORMS = ["ios", "android", "macos", "linux", "windows"]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(tmp_path, runner):
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        (Path(fs) / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
        yield Path(fs)


def fake_backend(monkeypatch, platform: str, results: list[CheckResult]) -> None:
    monkeypatch.setattr(
        get_platform(platform), "doctor", lambda cwd, **kwargs: list(results)
    )


MIXED = [
    CheckResult("Python", Status.PASS, "3.13.1"),
    CheckResult("Native binaries", Status.SKIP, "not configured"),
    CheckResult("Lock freshness", Status.WARN, "older than pyproject", "run lock"),
    CheckResult(
        "Byte-compile interpreter",
        Status.FAIL,
        "no 3.13 interpreter found",
        "install Python 3.13",
        code=diagnostics.BYTECOMPILE_NO_INTERP,
    ),
]


class TestEnvelope:
    def test_stdout_is_nothing_but_the_envelope(self, runner, project, monkeypatch):
        """The one property everything else depends on. If a single stray line
        reaches stdout, every consumer's ``json.loads`` fails."""
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(monkeypatch, "linux", [CheckResult("Python", Status.PASS, "3.13")])
        result = runner.invoke(doctor, ["--offline", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["schema"] == SCHEMA_VERSION
        assert payload["command"] == "doctor"
        assert payload["platform"] == "linux"
        assert payload["ok"] is True

    def test_the_human_header_does_not_leak_into_json_mode(
        self, runner, project, monkeypatch
    ):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(monkeypatch, "linux", [CheckResult("Python", Status.PASS, "3.13")])
        result = runner.invoke(doctor, ["--offline", "--json"])
        assert "kivyforge doctor (" not in result.stdout

    @pytest.mark.parametrize("platform", ALL_PLATFORMS)
    def test_every_backend_reports_its_own_platform(
        self, runner, project, monkeypatch, platform
    ):
        """Five backends, one code path -- but the platform name is the field an
        agent keys off, so it is worth proving per backend rather than once."""
        monkeypatch.setenv("KIVYFORGE_PLATFORM", platform)
        fake_backend(
            monkeypatch, platform, [CheckResult("Python", Status.PASS, "3.13")]
        )
        result = runner.invoke(doctor, ["--offline", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["platform"] == platform


class TestData:
    @pytest.fixture(autouse=True)
    def _linux_with_mixed_results(self, monkeypatch, project):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(monkeypatch, "linux", MIXED)

    def test_checks_carry_name_status_detail_and_hint(self, runner):
        result = runner.invoke(doctor, ["--offline", "--json"])
        checks = {c["name"]: c for c in json.loads(result.stdout)["data"]["checks"]}
        assert checks["Python"] == {
            "name": "Python",
            "status": "PASS",
            "detail": "3.13.1",
        }
        assert checks["Lock freshness"]["hint"] == "run lock"

    def test_a_passing_check_keeps_its_hint_unlike_the_human_report(self, runner):
        """``render()`` hides hints on PASS to keep the human report terse. A
        machine consumer has no such problem and may well want it."""
        result = runner.invoke(doctor, ["--offline", "--json"])
        checks = {c["name"]: c for c in json.loads(result.stdout)["data"]["checks"]}
        assert "hint" not in checks["Python"]
        assert checks["Byte-compile interpreter"]["hint"] == "install Python 3.13"

    def test_summary_has_all_four_statuses_even_at_zero(self, runner):
        """So a consumer can read ``summary["FAIL"]`` unconditionally."""
        result = runner.invoke(doctor, ["--offline", "--json"])
        assert json.loads(result.stdout)["data"]["summary"] == {
            "PASS": 1,
            "WARN": 1,
            "FAIL": 1,
            "SKIP": 1,
        }

    def test_mode_is_reported(self, runner):
        result = runner.invoke(doctor, ["--offline", "--json"])
        assert json.loads(result.stdout)["data"]["mode"] == "project"

    def test_check_order_is_preserved(self, runner):
        """Backends order checks cheapest-first and most-fundamental-first, which
        is information a consumer can use."""
        result = runner.invoke(doctor, ["--offline", "--json"])
        names = [c["name"] for c in json.loads(result.stdout)["data"]["checks"]]
        assert names == [c.name for c in MIXED]


class TestDiagnostics:
    @pytest.fixture(autouse=True)
    def _linux_with_mixed_results(self, monkeypatch, project):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(monkeypatch, "linux", MIXED)

    def _diagnostics(self, runner) -> list[dict]:
        result = runner.invoke(doctor, ["--offline", "--json"])
        return json.loads(result.stdout)["diagnostics"]

    def test_only_warn_and_fail_produce_diagnostics(self, runner):
        """A diagnostics list that includes successes is one every consumer has
        to filter before using."""
        found = self._diagnostics(runner)
        assert [d["severity"] for d in found] == ["warning", "error"]

    def test_an_assigned_code_is_used(self, runner):
        error = self._diagnostics(runner)[1]
        assert error["code"] == diagnostics.BYTECOMPILE_NO_INTERP

    def test_an_unassigned_check_gets_the_generic_code(self, runner):
        """Generic but still branchable: it means "the detail is in data.checks,
        keyed by name", rather than leaving a null in the payload."""
        warning = self._diagnostics(runner)[0]
        assert warning["code"] == diagnostics.DOCTOR_CHECK

    def test_the_hint_becomes_remediation_rather_than_prose(self, runner):
        """Point 5 of the agent-friendliness list: the ``Fix:`` convention
        should not have to be recovered by string-splitting."""
        error = self._diagnostics(runner)[1]
        assert error["remediation"] == "install Python 3.13"

    def test_the_check_name_travels_as_context_for_joining(self, runner):
        error = self._diagnostics(runner)[1]
        assert error["context"] == {"check": "Byte-compile interpreter"}


class TestExitCodes:
    def test_a_fail_exits_environment_error_not_generic_one(
        self, runner, project, monkeypatch
    ):
        """A doctor FAIL means this machine or project is not ready, which wants
        a different reaction from "you passed a bad flag"."""
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(monkeypatch, "linux", MIXED)
        result = runner.invoke(doctor, ["--offline", "--json"])
        assert result.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert json.loads(result.stdout)["ok"] is False

    def test_warnings_alone_still_succeed(self, runner, project, monkeypatch):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(
            monkeypatch, "linux", [CheckResult("Lock freshness", Status.WARN, "old")]
        )
        result = runner.invoke(doctor, ["--offline", "--json"])
        assert result.exit_code == exit_codes.SUCCESS
        assert json.loads(result.stdout)["ok"] is True

    def test_a_failing_run_still_emits_a_parseable_envelope(
        self, runner, project, monkeypatch
    ):
        """The failure path is the one an agent most needs to read, so it must
        not be the path that stops producing JSON."""
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(monkeypatch, "linux", [CheckResult("Python", Status.FAIL, "gone")])
        result = runner.invoke(doctor, ["--offline", "--json"])
        assert result.exit_code != 0
        assert json.loads(result.stdout)["diagnostics"][0]["severity"] == "error"


class TestHumanModeUnchanged:
    def test_the_report_still_goes_to_stdout(self, runner, project, monkeypatch):
        """``kivyforge doctor > report.txt`` has always worked and must keep
        working: in human mode the report *is* the product, so it belongs on
        stdout even though progress does not."""
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(monkeypatch, "linux", MIXED)
        result = runner.invoke(doctor, ["--offline"])
        assert "kivyforge doctor (linux, project mode)" in result.stdout
        assert "[PASS] Python: 3.13.1" in result.stdout
        assert "hint: run lock" in result.stdout

    def test_no_json_appears_without_the_flag(self, runner, project, monkeypatch):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fake_backend(monkeypatch, "linux", MIXED)
        result = runner.invoke(doctor, ["--offline"])
        assert '"schema"' not in result.stdout

    def test_no_color_is_accepted_and_output_has_no_escapes(
        self, runner, project, monkeypatch
    ):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        monkeypatch.setenv("FORCE_COLOR", "1")
        fake_backend(monkeypatch, "linux", MIXED)
        result = runner.invoke(doctor, ["--offline", "--no-color"])
        assert result.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert "\x1b" not in result.stdout
