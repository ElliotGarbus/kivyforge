"""Onedir path depth vs. MAX_PATH (test-matrix §5.6), hermetic.

Pure path arithmetic plus the package-time warning; none of it needs a
Windows host. The live reproduction, with long paths actually switched off,
is ``test_long_paths_live.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from kivyforge.build_outcome import BuildEvents
from kivyforge.platforms.windows import cli
from kivyforge.platforms.windows.pathdepth import (
    MAX_PATH_CHARS,
    MIN_FOLDER_HEADROOM,
    deepest_relative_path,
    folder_headroom,
)
from kivyforge.report import diagnostics


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


class TestDeepestRelativePath:
    def test_empty_tree(self, tmp_path):
        assert deepest_relative_path(tmp_path) == ""

    def test_finds_the_longest_and_spells_it_for_windows(self, tmp_path):
        _touch(tmp_path / "a" / "b.py")
        _touch(tmp_path / "python" / "Lib" / "site-packages" / "pkg" / "mod.py")
        assert deepest_relative_path(tmp_path) == "\\".join(
            ["python", "Lib", "site-packages", "pkg", "mod.py"]
        )

    def test_an_empty_directory_counts(self, tmp_path):
        _touch(tmp_path / "short.py")
        (tmp_path / "a-much-longer-empty-directory").mkdir()
        assert deepest_relative_path(tmp_path) == "a-much-longer-empty-directory"

    def test_ties_resolve_to_sorted_order(self, tmp_path):
        _touch(tmp_path / "bb")
        _touch(tmp_path / "aa")
        assert deepest_relative_path(tmp_path) == "aa"


class TestFolderHeadroom:
    def test_arithmetic(self):
        # folder + separator + deepest must fit in 259 characters.
        assert MAX_PATH_CHARS == 259
        assert folder_headroom("x" * 105) == 153  # the 2026-09-24 measurement
        assert folder_headroom("") == 258


class _Events:
    def __init__(self):
        self.progress: list[str] = []
        self.notes: list[tuple[str, str, Mapping[str, str] | None]] = []

    def build(self) -> BuildEvents:
        return BuildEvents(
            on_line=lambda s: None,
            on_progress=self.progress.append,
            on_artifact=lambda a: None,
            on_note=lambda c, m, ctx: self.notes.append((c, m, ctx)),
        )


class TestPackageWarning:
    def _bundle(self, tmp_path, rel_len):
        head = "python/Lib/site-packages/pkg/"
        _touch(tmp_path / head / ("m" * (rel_len - len(head) - 3) + ".py"))
        return tmp_path

    def test_silent_with_enough_headroom(self, tmp_path):
        rel_len = MAX_PATH_CHARS - 1 - MIN_FOLDER_HEADROOM  # exactly enough
        events = _Events()
        cli._note_path_depth(self._bundle(tmp_path, rel_len), events.build())
        assert events.progress == [] and events.notes == []

    def test_warns_and_notes_one_character_short(self, tmp_path):
        rel_len = MAX_PATH_CHARS - MIN_FOLDER_HEADROOM  # one past
        events = _Events()
        cli._note_path_depth(self._bundle(tmp_path, rel_len), events.build())
        [line] = events.progress
        assert line.startswith("[package] warning: the deepest path in this bundle")
        assert f"at most {MIN_FOLDER_HEADROOM - 1} characters" in line
        [(code, message, context)] = events.notes
        assert code == diagnostics.PATH_DEPTH == "KF-PATH-DEPTH"
        assert context is not None
        assert context["folder_headroom"] == str(MIN_FOLDER_HEADROOM - 1)
        assert context["deepest"].startswith("python\\Lib\\site-packages\\pkg\\")
        assert message in line
