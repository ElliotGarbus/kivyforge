"""The structured ``status`` types (roadmap item 3).

``status`` used to fuse state, remediation and presentation into one string --
``"out of date (run `kivyforge lock -p linux`)"`` was a single value. These tests
pin the three apart, since keeping them apart is the whole point of the refactor.

``humanize_age`` itself is covered in ``tests/cli/test_status_clean_upgrade.py``,
which owned those cases before the function moved here.
"""

from __future__ import annotations

from pathlib import Path

from kivyforge.status import (
    BuildArtifact,
    LockState,
    LockStatus,
    StatusReport,
)


class TestLockStatus:
    def test_in_sync_renders_without_a_command(self):
        """The command is set even when in sync, and must stay unmentioned --
        suggesting a relock to someone whose lock is fine is just noise."""
        lock = LockStatus(LockState.IN_SYNC, "kivyforge lock -p linux")
        assert lock.render() == "in sync"
        assert lock.in_sync is True

    def test_a_problem_renders_the_command(self):
        lock = LockStatus(LockState.OUT_OF_DATE, "kivyforge lock -p linux")
        assert lock.render() == "out of date (run `kivyforge lock -p linux`)"
        assert lock.in_sync is False

    def test_no_command_renders_the_bare_state(self):
        """Android reported bare states for its whole life; the model has to be
        able to express that rather than forcing a suggestion."""
        assert LockStatus(LockState.MISSING).render() == "missing"

    def test_as_dict_separates_state_from_remediation(self):
        payload = LockStatus(LockState.UNREADABLE, "kivyforge lock -p macos").as_dict()
        assert payload == {
            "state": "unreadable",
            "in_sync": False,
            "relock_command": "kivyforge lock -p macos",
        }

    def test_as_dict_omits_an_absent_command(self):
        assert "relock_command" not in LockStatus(LockState.MISSING).as_dict()

    def test_in_sync_is_a_derived_flag_for_consumers(self):
        """So an agent can branch without knowing the state vocabulary."""
        assert LockStatus(LockState.IN_SYNC).as_dict()["in_sync"] is True
        assert LockStatus(LockState.OUT_OF_DATE).as_dict()["in_sync"] is False


class TestBuildArtifact:
    def test_probe_of_a_missing_path_is_not_built(self, tmp_path):
        artifact = BuildArtifact.probe(tmp_path / "nope")
        assert artifact.built is False
        assert artifact.mtime is None
        assert artifact.render() == "not built"

    def test_probe_of_an_existing_path_is_built(self, tmp_path):
        target = tmp_path / "app"
        target.mkdir()
        artifact = BuildArtifact.probe(target)
        assert artifact.built is True
        assert "last built" in artifact.render()

    def test_render_uses_an_injected_clock(self):
        """So a test never has to sleep or monkeypatch the time module."""
        artifact = BuildArtifact(path=Path("app"), mtime=1000.0)
        assert artifact.render(now=1000.0 + 7200) == "last built 2 hours ago"

    def test_built_is_derived_from_mtime_not_stored_separately(self):
        """Two fields that must agree are two fields that can disagree."""
        assert BuildArtifact(path=Path("a"), mtime=1.0).built is True
        assert BuildArtifact(path=Path("a")).built is False

    def test_as_dict_reports_the_path_even_when_not_built(self):
        """It tells an agent where the artifact *would* be, which is most of the
        value of reporting paths at all."""
        payload = BuildArtifact.probe(Path("build") / "linux" / "app").as_dict()
        assert payload["built"] is False
        assert payload["path"] == "build/linux/app"
        assert "mtime" not in payload

    def test_as_dict_uses_posix_separators(self):
        """So the value does not change shape depending on the build host."""
        payload = BuildArtifact(path=Path("build") / "windows" / "My App").as_dict()
        assert payload["path"] == "build/windows/My App"

    def test_as_dict_omits_an_empty_label(self):
        assert "label" not in BuildArtifact(path=Path("a")).as_dict()
        assert BuildArtifact(path=Path("a"), label="apk (debug)").as_dict()[
            "label"
        ] == ("apk (debug)")


class TestStatusReport:
    def _report(self, **kwargs) -> StatusReport:
        base = {
            "platform": "linux",
            "app_name": "My App",
            "app_id": "org.example.myapp",
            "python_version": "3.13.14",
            "lock": LockStatus(LockState.IN_SYNC, "kivyforge lock -p linux"),
            "artifacts": (BuildArtifact(path=Path("build/linux/My App.AppDir")),),
        }
        return StatusReport(**{**base, **kwargs})

    def test_as_dict_nests_app_identity(self):
        payload = self._report().as_dict()
        assert payload["app"] == {"name": "My App", "id": "org.example.myapp"}

    def test_extra_is_always_present_as_a_mapping(self):
        """Empty for four of the five backends, and still present, so a consumer
        never has to branch on the platform to read it."""
        assert self._report().as_dict()["extra"] == {}

    def test_extra_preserves_order_and_values(self):
        report = self._report(
            extra=(("Kivy/SDL", "kivy 2.3.1"), ("ABIs", "arm64-v8a, x86_64"))
        )
        extra = report.as_dict()["extra"]
        assert isinstance(extra, dict)
        assert list(extra) == ["Kivy/SDL", "ABIs"]

    def test_artifacts_serialise_in_order(self):
        report = self._report(
            artifacts=(
                BuildArtifact(path=Path("a"), label="apk (debug)"),
                BuildArtifact(path=Path("b"), label="aab (release)"),
            )
        )
        artifacts = report.as_dict()["artifacts"]
        assert isinstance(artifacts, list)
        labels = [a["label"] for a in artifacts]
        assert labels == ["apk (debug)", "aab (release)"]
