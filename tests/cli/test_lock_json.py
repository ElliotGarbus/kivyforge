"""``kivyforge lock --json`` and its narrowed diagnostics (roadmap item 3).

Driven through a fake ``_LockOps`` rather than any real resolver. What is under
test is the *verb*: which envelope each of the five outcomes produces, and which
code and exit status each failure carries. Real resolution is covered per
platform in ``tests/platforms/*/lock/test_lock_cli.py``, and those tests still
assert the unchanged human output.

``lock`` is the first verb whose failures got specific exit codes, so the
assertions on :mod:`kivyforge.report.exit_codes` here are the contract: `--check`
answering "stale" is the one kivyforge failure a CI job is most likely to branch
on, and it must not be confused with a bad flag (``2``, click's) or a broken
``pyproject.toml`` (``1``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli import lock as lock_mod
from kivyforge.cli.lock import _LockOps, lock
from kivyforge.lock.reader import LockError
from kivyforge.report import diagnostics, exit_codes

LINUX_PYPROJECT = """\
[project]
name = "myapp"
version = "1.0.0"
requires-python = ">=3.15"
dependencies = ["kivy>=3.0,<4"]

[tool.kivy]
app_dir = "src"

[tool.kivy.linux]
schema_version = 1
app_id = "org.example.myapp"

[tool.kivy.linux.python]
version = "3.15.0"
"""

DIFF = ["  + added: rich 13.7.0", "  - removed: six 1.16.0"]


class FakeBuildError(Exception):
    pass


@dataclass
class FakeLock:
    packages: tuple[str, ...] = ("click", "packaging", "rich")


def make_ops(
    *,
    in_sync: bool = True,
    loadable: bool = True,
    warnings: tuple[str, ...] = (),
) -> _LockOps:
    """A ``_LockOps`` whose resolution is a constant.

    *in_sync* drives ``semantic_equal`` (the ``--check`` verdict); *loadable*
    makes ``load`` raise ``LockError`` to stand in for a corrupt lock.
    """

    def load(_path):
        if not loadable:
            raise LockError("expected a table, found a string")
        return FakeLock()

    def build(_config, _text, *, project_root=None, offline=False, **kwargs):
        for message in warnings:
            kwargs["on_warning"](message)
        return FakeLock()

    return _LockOps(
        build=build,
        dumps=lambda _lock: "# fake lock\n",
        load=load,
        semantic_equal=lambda _a, _b: in_sync,
        diff_summary=lambda _a, _b: DIFF,
        build_error=FakeBuildError,
        require_ios=False,
        require_macos=False,
        emits_warnings=bool(warnings),
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project(monkeypatch, tmp_path, runner):
    """An isolated project targeting linux, with the lock ops faked out."""
    monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")

    def install(ops: _LockOps) -> None:
        monkeypatch.setattr(lock_mod, "_lock_ops", lambda _platform: ops)
        # The non-check path consults the real drift check; the fake lock is
        # not something it can hash, so its verdict is chosen here too.
        monkeypatch.setattr(lock_mod, "is_in_sync", lambda _lock, _text: True)

    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        (Path(fs) / "pyproject.toml").write_text(LINUX_PYPROJECT)
        yield install


def envelope(result) -> dict:
    return json.loads(result.stdout)


class TestWrite:
    def test_a_fresh_lock_reports_what_it_wrote(self, runner, project):
        project(make_ops())
        result = runner.invoke(lock, ["--json"])
        assert result.exit_code == exit_codes.SUCCESS, result.output
        payload = envelope(result)
        assert payload["command"] == "lock"
        assert payload["platform"] == "linux"
        assert payload["ok"] is True
        assert payload["data"] == {
            "lockfile": "pylock.linux.toml",
            "action": "wrote",
            "in_sync": True,
            "packages": 3,
        }

    def test_the_lockfile_is_named_rather_than_left_to_be_deduced(
        self, runner, project
    ):
        """Agent-friendliness point 2. The path is deterministic; needing to know
        that from the docs is the thing being removed."""
        project(make_ops())
        assert envelope(runner.invoke(lock, ["--json"]))["data"]["lockfile"] == (
            "pylock.linux.toml"
        )

    def test_an_in_sync_lock_is_left_alone(self, runner, project):
        project(make_ops())
        runner.invoke(lock, [])
        payload = envelope(runner.invoke(lock, ["--json"]))
        assert payload["ok"] is True
        assert payload["data"]["action"] == "unchanged"

    def test_update_forces_a_rewrite(self, runner, project):
        project(make_ops())
        runner.invoke(lock, [])
        payload = envelope(runner.invoke(lock, ["--json", "--update"]))
        assert payload["data"]["action"] == "wrote"


class TestCheck:
    def test_an_up_to_date_lock_passes(self, runner, project):
        project(make_ops())
        runner.invoke(lock, [])
        result = runner.invoke(lock, ["--json", "--check"])
        assert result.exit_code == exit_codes.SUCCESS, result.output
        payload = envelope(result)
        assert payload["ok"] is True
        assert payload["data"]["action"] == "checked"
        assert payload["data"]["in_sync"] is True

    def test_a_stale_lock_fails_with_the_drift_code_and_exit(self, runner, project):
        project(make_ops(in_sync=False))
        runner.invoke(lock, [])
        result = runner.invoke(lock, ["--json", "--check"])
        assert result.exit_code == exit_codes.LOCK_DRIFT
        payload = envelope(result)
        assert payload["ok"] is False
        assert [d["code"] for d in payload["diagnostics"]] == [diagnostics.LOCK_DRIFT]
        assert payload["diagnostics"][0]["remediation"] == "kivyforge lock -p linux"

    def test_the_diff_survives_into_the_failure_envelope(self, runner, project):
        """The point of ``Report.record``.

        Before it, a failing verb emitted ``"data": {}`` -- so the one run a CI
        job most wants to read machine-side told it drift had happened and not
        *what* drifted, even though the human stderr had the answer.
        """
        project(make_ops(in_sync=False))
        runner.invoke(lock, [])
        payload = envelope(runner.invoke(lock, ["--json", "--check"]))
        assert payload["data"]["diff"] == DIFF
        assert payload["data"]["in_sync"] is False
        assert payload["data"]["lockfile"] == "pylock.linux.toml"

    def test_a_missing_lock_is_its_own_code(self, runner, project):
        project(make_ops())
        result = runner.invoke(lock, ["--json", "--check"])
        assert result.exit_code == exit_codes.LOCK_DRIFT
        found = envelope(result)["diagnostics"]
        assert [d["code"] for d in found] == [diagnostics.LOCK_MISSING]

    def test_a_corrupt_lock_is_distinguishable_from_a_stale_one(self, runner, project):
        """A bad merge or truncated write deserves noticing, not silent re-locking."""
        project(make_ops(loadable=False))
        runner.invoke(lock, [])
        result = runner.invoke(lock, ["--json", "--check"])
        assert result.exit_code == exit_codes.LOCK_DRIFT
        found = envelope(result)["diagnostics"]
        assert [d["code"] for d in found] == [diagnostics.LOCK_UNREADABLE]

    def test_all_three_failures_share_one_exit_code(self, runner, project):
        """Deliberate: a consumer that only wants "re-lock and retry" branches on
        the number, and one that wants the distinction reads the code."""
        assert (
            diagnostics.LOCK_DRIFT
            != diagnostics.LOCK_MISSING
            != diagnostics.LOCK_UNREADABLE
        )
        assert exit_codes.LOCK_DRIFT not in (
            exit_codes.SUCCESS,
            exit_codes.CONFIG_ERROR,
            exit_codes.USAGE_ERROR,
        )


class TestWarnings:
    def test_a_resolution_warning_reaches_the_envelope(self, runner, project):
        """These went to stderr only, so a machine could not see that the
        resolver had accepted (say) a vendored plain ``linux_*`` wheel."""
        project(make_ops(warnings=("accepted vendored wheel foo-1.0-linux_x86_64",)))
        payload = envelope(runner.invoke(lock, ["--json"]))
        assert payload["ok"] is True
        assert payload["diagnostics"][0]["code"] == diagnostics.LOCK_WARNING
        assert payload["diagnostics"][0]["severity"] == diagnostics.WARNING

    def test_a_warning_does_not_fail_the_lock(self, runner, project):
        project(make_ops(warnings=("heads up",)))
        result = runner.invoke(lock, ["--json"])
        assert result.exit_code == exit_codes.SUCCESS
        assert envelope(result)["data"]["action"] == "wrote"


class TestHumanMode:
    def test_stdout_still_says_what_it_wrote(self, runner, project):
        project(make_ops())
        result = runner.invoke(lock, [])
        assert result.exit_code == 0, result.output
        assert "Wrote pylock.linux.toml (3 packages pinned)." in result.stdout

    def test_the_drift_diff_stays_on_stderr(self, runner, project):
        """It always went to stderr, and it should: under ``--json`` stdout has to
        stay a single parseable document."""
        project(make_ops(in_sync=False))
        runner.invoke(lock, [])
        result = runner.invoke(lock, ["--check"])
        assert "is out of date:" in result.stderr
        assert DIFF[0] in result.stderr
        assert '"schema"' not in result.stdout

    def test_json_mode_suppresses_the_human_lines(self, runner, project):
        project(make_ops())
        assert "packages pinned" not in runner.invoke(lock, ["--json"]).stdout

    def test_no_color_leaves_no_escapes(self, runner, project, monkeypatch):
        monkeypatch.setenv("FORCE_COLOR", "1")
        project(make_ops())
        assert "\x1b" not in runner.invoke(lock, []).stdout
