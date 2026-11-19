"""kivyforge lock -p android: an edited ``include_files`` file is accepted by
plain ``lock``, without re-resolving anything.

The include pins are content hashes, outside ``lock_inputs_sha256``, so the
lock read as in sync and plain ``lock`` did nothing while ``build`` refused the
drift and told the user to run plain ``lock`` (#176).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.lock import lock
from kivyforge.platforms.android.cli import android_status
from kivyforge.platforms.android.lock import builder, reader
from kivyforge.status import LockState
from tests.platforms.android.lock.test_lock import (
    PYPROJECT,
    FakeProvider,
    FakeResolver,
    _pkg,
)

INCLUDE_PYPROJECT = PYPROJECT.replace(
    "[tool.kivy.android.python]",
    "[[tool.kivy.android.include_files]]\n"
    'dest = "app"\n'
    'sources = ["config"]\n\n'
    "[tool.kivy.android.python]",
)


@pytest.fixture
def resolver(monkeypatch) -> FakeResolver:
    """The fake every lock in the test resolves with; ``calls`` counts them."""
    fake = FakeResolver([_pkg()])
    real_build = builder.build_lockfile

    def build(config, **kwargs):
        return real_build(
            config, resolver=fake, python_provider=FakeProvider(), **kwargs
        )

    monkeypatch.setattr(builder, "build_lockfile", build)
    return fake


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "app"
    (root / "src").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "google-services.json").write_text("{}", encoding="utf-8")
    (root / "pyproject.toml").write_text(INCLUDE_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(root)
    return root


def _lock(*args: str) -> dict:
    result = CliRunner().invoke(lock, ["-p", "android", "--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _pins(root: Path) -> dict[str, str]:
    locked = reader.load(root / "pylock.android.toml")
    return {p.source: p.sha256 for p in locked.include_files}


class TestIncludeFilesRelock:
    def test_an_unchanged_project_is_left_alone(self, project, resolver):
        _lock()
        before = (project / "pylock.android.toml").read_bytes()
        assert _lock()["data"]["action"] == "unchanged"
        assert (project / "pylock.android.toml").read_bytes() == before
        assert len(resolver.calls) == 1

    def test_an_edited_file_is_re_recorded(self, project, resolver):
        _lock()
        old = _pins(project)["config/google-services.json"]
        (project / "config" / "google-services.json").write_text(
            '{"project_id": "x"}', encoding="utf-8"
        )
        assert _lock()["data"]["action"] == "wrote"
        assert _pins(project)["config/google-services.json"] != old
        assert len(resolver.calls) == 1

    def test_a_file_added_to_a_directory_source_is_recorded(self, project, resolver):
        _lock()
        (project / "config" / "extra.json").write_text("{}", encoding="utf-8")
        assert _lock()["data"]["action"] == "wrote"
        assert set(_pins(project)) == {
            "config/extra.json",
            "config/google-services.json",
        }
        assert len(resolver.calls) == 1

    def test_a_deleted_file_is_dropped(self, project, resolver):
        (project / "config" / "extra.json").write_text("{}", encoding="utf-8")
        _lock()
        (project / "config" / "extra.json").unlink()
        assert _lock()["data"]["action"] == "wrote"
        assert set(_pins(project)) == {"config/google-services.json"}
        assert len(resolver.calls) == 1

    def test_the_rewrite_keeps_everything_that_was_resolved(self, project, resolver):
        _lock()
        before = reader.load(project / "pylock.android.toml")
        (project / "config" / "google-services.json").write_text("[]")
        _lock()
        after = reader.load(project / "pylock.android.toml")
        assert after.packages == before.packages
        assert after.python_android == before.python_android
        assert after.lock_inputs_sha256 == before.lock_inputs_sha256

    def test_the_rewrite_is_reported(self, project, resolver):
        CliRunner().invoke(lock, ["-p", "android"])
        (project / "config" / "google-services.json").write_text("[]")
        result = CliRunner().invoke(lock, ["-p", "android", "--no-color"])
        assert result.exit_code == 0, result.output
        assert "no package re-resolved" in result.stdout
        assert (
            "include_files: config/google-services.json -> app (changed)"
            in result.stderr
        )

    def test_a_re_lock_converges(self, project, resolver):
        """The loop itself: after one plain ``lock``, the next is a no-op."""
        _lock()
        (project / "config" / "google-services.json").write_text("[]")
        _lock()
        assert _lock()["data"]["action"] == "unchanged"

    def test_build_accepts_the_re_recorded_pins(self, project, resolver, tmp_path):
        """What the drift message promises: after plain ``lock``, the build's
        own include check passes for an edit, an addition and a deletion."""
        from kivyforge.build_outcome import BuildEvents, discard_artifact, discard_note
        from kivyforge.config.loader import load_config
        from kivyforge.platforms.android.cli import _copy_include_files

        (project / "config" / "doomed.json").write_text("{}", encoding="utf-8")
        _lock()
        (project / "config" / "google-services.json").write_text("[]")
        (project / "config" / "extra.json").write_text("{}", encoding="utf-8")
        (project / "config" / "doomed.json").unlink()
        _lock()
        config = load_config(
            project / "pyproject.toml", require_ios=False, require_android=True
        )
        events = BuildEvents(
            on_line=lambda _: None,
            on_progress=lambda _: None,
            on_artifact=discard_artifact,
            on_note=discard_note,
        )
        _copy_include_files(
            project,
            tmp_path / "generated",
            config.android_required,
            reader.load(project / "pylock.android.toml"),
            events,
        )
        assert (tmp_path / "generated" / "app" / "extra.json").is_file()

    def test_check_names_the_drifted_file(self, project, resolver):
        _lock()
        (project / "config" / "google-services.json").write_text("[]")
        result = CliRunner().invoke(lock, ["-p", "android", "--json", "--check"])
        assert result.exit_code != 0
        assert json.loads(result.stdout)["data"]["diff"] == [
            "  ~ include_files: config/google-services.json -> app (changed)"
        ]


class TestStatus:
    def test_include_drift_reads_as_out_of_date(self, project, resolver):
        _lock()
        assert android_status(project).lock.state is LockState.IN_SYNC
        (project / "config" / "google-services.json").write_text("[]")
        assert android_status(project).lock.state is LockState.OUT_OF_DATE


RULES_PYPROJECT = PYPROJECT.replace(
    "[tool.kivy.android.python]",
    "[tool.kivy.android.proguard]\n"
    'keep = ["-keep class com.google.zxing.** { *; }"]\n'
    'rules_files = ["proguard/vendor.pro"]\n\n'
    "[tool.kivy.android.python]",
)


@pytest.fixture
def rules_project(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "app"
    (root / "src").mkdir(parents=True)
    (root / "proguard").mkdir()
    (root / "proguard" / "vendor.pro").write_text(
        "-keep class com.vendor.** { *; }\n", encoding="utf-8"
    )
    (root / "proguard" / "extra.pro").write_text("-dontwarn x.**\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(RULES_PYPROJECT, encoding="utf-8")
    monkeypatch.chdir(root)
    return root


def _rules_pins(root: Path) -> dict[str, str]:
    locked = reader.load(root / "pylock.android.toml")
    return {p.source: p.sha256 for p in locked.proguard_rules_files}


def _set_rules_files(root: Path, *paths: str) -> None:
    listed = ", ".join(f'"{p}"' for p in paths)
    text = RULES_PYPROJECT.replace(
        'rules_files = ["proguard/vendor.pro"]', f"rules_files = [{listed}]"
    )
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


def _build_load(root: Path):
    from kivyforge.platforms.android.cli import _load

    return _load(root, None, no_verify_lock=False)


class TestProguardRulesFiles:
    """rules_files are pinned like include_files (android/01 §proguard)."""

    def test_lock_pins_each_rules_file(self, rules_project, resolver):
        import hashlib

        _lock()
        digest = hashlib.sha256(
            (rules_project / "proguard" / "vendor.pro").read_bytes()
        ).hexdigest()
        assert _rules_pins(rules_project) == {"proguard/vendor.pro": digest}
        text = (rules_project / "pylock.android.toml").read_text()
        assert (
            "[[tool.kivyforge.proguard_rules_files]]\n"
            'source = "proguard/vendor.pro"\n'
            f'sha256 = "{digest}"\n'
        ) in text
        # keep is read on every build, never written to the lock.
        assert "zxing" not in text

    def test_build_accepts_a_fresh_lock(self, rules_project, resolver):
        _lock()
        _build_load(rules_project)

    def test_build_refuses_an_edited_rules_file(self, rules_project, resolver):
        from kivyforge.platforms.android import LockDrift
        from kivyforge.report import diagnostics, exit_codes

        _lock()
        (rules_project / "proguard" / "vendor.pro").write_text("-keep class y.** {*;}")
        with pytest.raises(LockDrift, match="has changed since the lock") as exc:
            _build_load(rules_project)
        assert exc.value.code == diagnostics.LOCK_DRIFT
        assert exc.value.exit_code == exit_codes.LOCK_DRIFT
        assert exc.value.context == {"source": "proguard/vendor.pro"}

    def test_build_refuses_an_unpinned_rules_file(self, rules_project, resolver):
        from kivyforge.platforms.android import LockDrift

        _lock()
        _set_rules_files(rules_project, "proguard/vendor.pro", "proguard/extra.pro")
        with pytest.raises(LockDrift, match="records no hash for it"):
            _build_load(rules_project)

    def test_build_refuses_a_pin_nothing_declares(self, rules_project, resolver):
        from kivyforge.platforms.android import LockDrift

        _lock()
        _set_rules_files(rules_project)
        with pytest.raises(LockDrift, match="no longer declares"):
            _build_load(rules_project)

    def test_no_verify_lock_skips_the_pins(self, rules_project, resolver):
        from kivyforge.platforms.android.cli import _load

        _lock()
        (rules_project / "proguard" / "vendor.pro").write_text("changed")
        _load(rules_project, None, no_verify_lock=True)

    def test_an_edit_is_re_recorded_without_resolving(self, rules_project, resolver):
        _lock()
        old = _rules_pins(rules_project)["proguard/vendor.pro"]
        (rules_project / "proguard" / "vendor.pro").write_text("-dontwarn z.**\n")
        assert _lock()["data"]["action"] == "wrote"
        assert _rules_pins(rules_project)["proguard/vendor.pro"] != old
        assert len(resolver.calls) == 1
        _build_load(rules_project)

    def test_an_added_and_a_removed_file_are_re_recorded(self, rules_project, resolver):
        _lock()
        _set_rules_files(rules_project, "proguard/extra.pro")
        assert _lock()["data"]["action"] == "wrote"
        assert set(_rules_pins(rules_project)) == {"proguard/extra.pro"}
        # Not a lock input: the change is a pin refresh, not a re-resolve.
        assert len(resolver.calls) == 1
        _build_load(rules_project)

    def test_a_keep_edit_leaves_the_lock_alone(self, rules_project, resolver):
        _lock()
        before = (rules_project / "pylock.android.toml").read_bytes()
        text = RULES_PYPROJECT.replace("com.google.zxing", "com.example")
        (rules_project / "pyproject.toml").write_text(text, encoding="utf-8")
        assert _lock()["data"]["action"] == "unchanged"
        assert (rules_project / "pylock.android.toml").read_bytes() == before
        _build_load(rules_project)

    def test_the_rewrite_is_reported(self, rules_project, resolver):
        CliRunner().invoke(lock, ["-p", "android"])
        (rules_project / "proguard" / "vendor.pro").write_text("x\n")
        result = CliRunner().invoke(lock, ["-p", "android", "--no-color"])
        assert result.exit_code == 0, result.output
        assert "proguard.rules_files: proguard/vendor.pro (changed)" in result.stderr

    def test_check_names_the_drifted_file(self, rules_project, resolver):
        _lock()
        (rules_project / "proguard" / "vendor.pro").write_text("x\n")
        result = CliRunner().invoke(lock, ["-p", "android", "--json", "--check"])
        assert result.exit_code != 0
        assert json.loads(result.stdout)["data"]["diff"] == [
            "  ~ proguard.rules_files: proguard/vendor.pro (changed)"
        ]

    def test_status_reads_drift_as_out_of_date(self, rules_project, resolver):
        _lock()
        assert android_status(rules_project).lock.state is LockState.IN_SYNC
        (rules_project / "proguard" / "vendor.pro").write_text("x\n")
        assert android_status(rules_project).lock.state is LockState.OUT_OF_DATE
