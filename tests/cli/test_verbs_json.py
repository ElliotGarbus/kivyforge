"""``--json`` for the four smaller verbs: clean, open, upgrade, init.

The envelope shape itself is pinned in ``tests/report``; what matters here is
each verb's ``data`` payload, and that the human lines are gone from stdout so
the document parses. Fields are asserted individually rather than as a golden
blob, because the envelope carries ``__version__``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli import upgrade as upgrade_mod
from kivyforge.cli.clean import clean
from kivyforge.cli.init import init
from kivyforge.cli.open_cmd import open_
from kivyforge.cli.upgrade import upgrade
from kivyforge.platforms import get_platform
from kivyforge.report import diagnostics, exit_codes
from tests.cli.test_status_clean_upgrade import PYPROJECT, _write


@pytest.fixture
def runner():
    return CliRunner()


def _run(runner, command, args, *, expect_ok=True):
    result = runner.invoke(command, [*args, "--json"])
    envelope = json.loads(result.stdout)  # exactly one document, nothing else
    assert envelope["ok"] is expect_ok, result.output
    return result, envelope


class TestClean:
    def test_reports_what_it_removed(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = _write(fs)
            (root / "myapp-ios").mkdir()
            (root / "build" / "linux").mkdir(parents=True)

            result, envelope = _run(runner, clean, [])

            assert envelope["command"] == "clean"
            assert sorted(envelope["data"]["removed"]) == [
                "build/linux",
                "myapp-ios",
            ]
            assert envelope["data"]["cache_flushed"] is False
            assert "Removed" not in result.stdout  # human lines are suppressed
            assert "Removed" in result.stderr or result.stderr == ""

    def test_nothing_to_clean_is_an_empty_list_not_an_error(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result, envelope = _run(runner, clean, [])
            assert result.exit_code == 0
            assert envelope["data"]["removed"] == []

    def test_cache_flush_is_reported(self, runner, tmp_path, monkeypatch):
        cleared = []
        monkeypatch.setattr(
            "kivyforge.artifacts.cache.ArtifactCache.clear",
            lambda self: cleared.append(True),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            _result, envelope = _run(runner, clean, ["--cache"])
            assert envelope["data"]["cache_flushed"] is True
            assert cleared == [True]

    def test_no_pyproject_fails_with_an_envelope(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result, envelope = _run(runner, clean, [], expect_ok=False)
            assert result.exit_code == exit_codes.CONFIG_ERROR
            # Recorded before the failure, so the key is present either way.
            assert envelope["data"]["removed"] == []


class TestOpen:
    def test_reports_the_project_it_opened(self, runner, tmp_path, monkeypatch):
        opened = []
        monkeypatch.setattr(
            get_platform("ios"),
            "open_project",
            lambda root, **kw: (
                opened.append(root) or root / "myapp-ios/myapp.xcodeproj"
            ),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            _result, envelope = _run(runner, open_, ["-p", "ios"])
            assert envelope["command"] == "open"
            assert envelope["platform"] == "ios"
            assert envelope["data"] == {"project": "myapp-ios/myapp.xcodeproj"}

    def test_a_missing_launcher_is_a_note_not_a_failure(self, tmp_path, monkeypatch):
        """Android with no Studio on PATH: ok, but the envelope says so."""
        from kivyforge.build_outcome import BuildEvents

        notes: list[tuple[str, str, Mapping[str, str] | None]] = []
        lines: list[str] = []
        events = BuildEvents(
            on_line=lines.append,
            on_progress=lambda _m: None,
            on_artifact=lambda _a: None,
            on_note=lambda code, message, context=None: notes.append(
                (code, message, context)
            ),
        )
        from kivyforge.platforms.android import cli as android_cli
        from tests.platforms.android import test_cli as android_tests

        root = tmp_path / "proj"
        root.mkdir()
        (root / "pyproject.toml").write_text(android_tests.PYPROJECT, encoding="utf-8")
        (root / "demoapp-android").mkdir()
        monkeypatch.setattr(android_cli.shutil, "which", lambda name: None)

        opened = android_cli.android_open(root, events=events)

        assert opened == root / "demoapp-android"
        assert [code for code, _m, _c in notes] == [diagnostics.IDE_NOT_FOUND]
        assert any("not found on PATH" in line for line in lines)


class TestUpgrade:
    def _fetched(self, monkeypatch):
        seen: list[str] = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda **kw: seen.append(kw["name"]) or Path("/x"),
        )
        return seen

    def test_names_every_artifact_it_refreshed(self, runner, tmp_path, monkeypatch):
        from kivyforge.platforms.ios.lock import LockedXcframework

        self._fetched(monkeypatch)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(
                fs,
                xcframeworks=(
                    LockedXcframework(
                        name="MyLib.xcframework",
                        version="1.0",
                        sha256="d" * 64,
                        slices=("ios-arm64",),
                        url="https://example/mylib.zip",
                    ),
                ),
            )
            _result, envelope = _run(runner, upgrade, ["-p", "ios"])
            assert envelope["command"] == "upgrade"
            assert envelope["data"] == {
                "refreshed": ["Python.xcframework", "MyLib.xcframework"],
                "skipped": 0,
            }

    def test_vendored_entries_are_counted_as_skipped(
        self, runner, tmp_path, monkeypatch
    ):
        from kivyforge.platforms.ios.lock import LockedXcframework

        self._fetched(monkeypatch)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(
                fs,
                xcframeworks=(
                    LockedXcframework(
                        name="Vendored.xcframework",
                        version="1.0",
                        sha256="e" * 64,
                        slices=("ios-arm64",),
                        path="vendor/Vendored.xcframework",
                    ),
                ),
            )
            _result, envelope = _run(runner, upgrade, ["-p", "ios"])
            assert envelope["data"]["refreshed"] == ["Python.xcframework"]
            assert envelope["data"]["skipped"] == 1

    def test_a_failure_still_names_what_was_already_refreshed(
        self, runner, tmp_path, monkeypatch
    ):
        from kivyforge.artifacts.verify import HashMismatch
        from kivyforge.platforms.ios.lock import LockedXcframework

        def fetch(**kw):
            if kw["name"] == "Python.xcframework":
                return Path("/x")
            raise HashMismatch(
                name="MyLib.xcframework",
                source="https://example/mylib.zip",
                expected="d" * 64,
                actual="f" * 64,
            )

        monkeypatch.setattr(upgrade_mod, "fetch_artifact", fetch)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(
                fs,
                xcframeworks=(
                    LockedXcframework(
                        name="MyLib.xcframework",
                        version="1.0",
                        sha256="d" * 64,
                        slices=("ios-arm64",),
                        url="https://example/mylib.zip",
                    ),
                ),
            )
            _result, envelope = _run(runner, upgrade, ["-p", "ios"], expect_ok=False)
            # The first artifact really was re-fetched; the envelope says so.
            assert envelope["data"]["refreshed"] == ["Python.xcframework"]


class TestInit:
    def test_reports_the_tables_it_wrote(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(
                '[project]\nname = "myapp"\nversion = "1.0.0"\n', encoding="utf-8"
            )
            _result, envelope = _run(runner, init, ["-p", "macos"])
            assert envelope["command"] == "init"
            assert envelope["platform"] == "macos"
            assert envelope["data"]["action"] == "added"
            assert envelope["data"]["tables"] == ["tool.kivy", "tool.kivy.macos"]

    def test_regenerate_reports_only_the_overlay(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
            _result, envelope = _run(runner, init, ["-p", "ios", "--force"])
            assert envelope["data"]["action"] == "regenerated"
            assert envelope["data"]["tables"] == ["tool.kivy.ios"]

    def test_existing_overlay_without_force_fails_with_an_envelope(
        self, runner, tmp_path
    ):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
            result, envelope = _run(runner, init, ["-p", "ios"], expect_ok=False)
            assert result.exit_code == exit_codes.CONFIG_ERROR
            assert envelope["diagnostics"][0]["code"] == diagnostics.UNSPECIFIED
