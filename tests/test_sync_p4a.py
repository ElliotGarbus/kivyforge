"""scripts/sync_p4a.py: code vendored from python-for-android stays as pinned.

Hermetic: upstream is a dict of fake file texts, and the template tree is a
copy in tmp_path; nothing is fetched.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path, PurePosixPath

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "sync_p4a", REPO / "scripts" / "sync_p4a.py"
)
assert _spec and _spec.loader
sp = importlib.util.module_from_spec(_spec)
sys.modules["sync_p4a"] = sp
_spec.loader.exec_module(sp)

OLD = "a" * 40
NEW = "b" * 40

ACTIVITY_V1 = """\
public class PythonActivity extends SDLActivity {
    public interface DarkModeListener {
        void onDarkModeChanged(boolean isDarkMode);
    }

    private DarkModeListener darkModeListener = null;

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        String s = "}";  // a brace in a literal: }
        super.onConfigurationChanged(newConfig);
    }

    public static void changeKeyboard(int inputType) {
        /*
         if (x) {
        */
    }
}
"""

ACTIVITY_V2 = ACTIVITY_V1.replace(
    "        super.onConfigurationChanged(newConfig);\n",
    "        notify(newConfig);\n        super.onConfigurationChanged(newConfig);\n",
)

MANIFEST = f"""\
[upstream]
repo = "kivy/python-for-android"
rev = "{OLD}"

[[file]]
path = "p4a/android/darkmode.py"
source = "src/android/darkmode.py"

[[block]]
name = "dark-mode"
target = "java/PythonActivity.java"
sources = ["sdl2/PythonActivity.java", "sdl3/PythonActivity.java"]
first = "public interface DarkModeListener {{"
last = "public void onConfigurationChanged(Configuration newConfig) {{"

[[block]]
name = "change-keyboard"
fragment = "p4a/java/changeKeyboard.java.in"
source = "sdl3/PythonActivity.java"
first = "public static void changeKeyboard(int inputType) {{"
"""


def _upstream(activity_sdl2: str, activity_sdl3: str, darkmode: str):
    return {
        "src/android/darkmode.py": darkmode,
        "sdl2/PythonActivity.java": activity_sdl2,
        "sdl3/PythonActivity.java": activity_sdl3,
    }


def _fake_fetch(revs: dict[str, dict[str, str]]):
    def fetch(rev: str, path: str) -> str:
        try:
            return revs[rev][path]
        except KeyError:
            raise sp.SyncError(f"{path}@{rev}: not found") from None

    return fetch


OURS_HEAD = """\
public class PythonActivity extends SDLActivity {
    private static final String TAG = "kivyforge";

    // BEGIN p4a dark-mode
"""
OURS_TAIL = """\
    // END p4a dark-mode

    protected void ours() {
    }
}
"""


@pytest.fixture
def tree(tmp_path, monkeypatch):
    templates = tmp_path / "templates"
    manifest = templates / "p4a" / "P4A_VENDOR.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(MANIFEST, encoding="utf-8")
    monkeypatch.setattr(sp, "TEMPLATES_ROOT", templates)
    monkeypatch.setattr(sp, "MANIFEST", manifest)
    block = sp.extract_block(
        ACTIVITY_V1,
        "public interface DarkModeListener {",
        "public void onConfigurationChanged(Configuration newConfig) {",
    )
    (templates / "java").mkdir()
    (templates / "java" / "PythonActivity.java").write_text(
        OURS_HEAD + block + OURS_TAIL, encoding="utf-8"
    )
    (templates / "p4a" / "android").mkdir()
    (templates / "p4a" / "android" / "darkmode.py").write_text("v1\n", encoding="utf-8")
    (templates / "p4a" / "java").mkdir()
    keyboard = "public static void changeKeyboard(int inputType) {"
    (templates / "p4a" / "java" / "changeKeyboard.java.in").write_text(
        sp.extract_block(ACTIVITY_V1, keyboard, keyboard), encoding="utf-8"
    )
    return templates


REVS = {
    OLD: _upstream(ACTIVITY_V1, ACTIVITY_V1, "v1\n"),
    NEW: _upstream(ACTIVITY_V2, ACTIVITY_V2, "v2\n"),
}


class TestExtractBlock:
    def test_runs_from_first_through_the_end_of_last(self):
        block = sp.extract_block(
            ACTIVITY_V1,
            "public interface DarkModeListener {",
            "public void onConfigurationChanged(Configuration newConfig) {",
        )
        assert block.startswith("    public interface DarkModeListener {\n")
        assert block.endswith(
            "        super.onConfigurationChanged(newConfig);\n    }\n"
        )
        assert "darkModeListener = null;" in block
        assert "changeKeyboard" not in block

    def test_braces_in_literals_comments_and_block_comments_do_not_count(self):
        block = sp.extract_block(
            ACTIVITY_V1,
            "public static void changeKeyboard(int inputType) {",
            "public static void changeKeyboard(int inputType) {",
        )
        assert block.endswith("        */\n    }\n")

    def test_a_field_ends_at_its_semicolon(self):
        anchor = "private DarkModeListener darkModeListener = null;"
        assert sp.extract_block(ACTIVITY_V1, anchor, anchor) == f"    {anchor}\n"

    def test_crlf_source_reads_as_lf(self):
        anchor = "private DarkModeListener darkModeListener = null;"
        crlf = ACTIVITY_V1.replace("\n", "\r\n")
        assert sp.extract_block(crlf, anchor, anchor) == f"    {anchor}\n"

    @pytest.mark.parametrize("anchor", ["}", "public void missing() {"])
    def test_an_anchor_must_match_exactly_one_line(self, anchor):
        with pytest.raises(sp.SyncError, match="exactly one line"):
            sp.extract_block(ACTIVITY_V1, anchor, anchor)

    def test_last_before_first_is_an_error(self):
        with pytest.raises(sp.SyncError, match="comes before"):
            sp.extract_block(
                ACTIVITY_V1,
                "public void onConfigurationChanged(Configuration newConfig) {",
                "public interface DarkModeListener {",
            )


class TestCheck:
    def test_matching_tree_passes(self, tree):
        assert sp.check(sp.load_manifest(), _fake_fetch(REVS)) == []

    def test_an_edited_file_fails(self, tree):
        (tree / "p4a" / "android" / "darkmode.py").write_text("edited\n")
        problems = sp.check(sp.load_manifest(), _fake_fetch(REVS))
        assert problems == [
            "p4a/android/darkmode.py differs from p4a src/android/darkmode.py"
        ]

    def test_an_edit_inside_a_fence_fails(self, tree):
        target = tree / "java" / "PythonActivity.java"
        target.write_text(target.read_text().replace("= null;", "= null; // mine"))
        problems = sp.check(sp.load_manifest(), _fake_fetch(REVS))
        assert len(problems) == 1
        assert "block 'dark-mode' differs" in problems[0]

    def test_an_edit_outside_the_fences_passes(self, tree):
        target = tree / "java" / "PythonActivity.java"
        target.write_text(target.read_text().replace("ours()", "renamed()"))
        assert sp.check(sp.load_manifest(), _fake_fetch(REVS)) == []

    def test_crlf_checkout_passes(self, tree):
        target = tree / "java" / "PythonActivity.java"
        lf = target.read_bytes().replace(b"\r\n", b"\n")
        target.write_bytes(lf.replace(b"\n", b"\r\n"))
        assert sp.check(sp.load_manifest(), _fake_fetch(REVS)) == []

    def test_a_missing_file_and_fence_are_reported(self, tree):
        (tree / "p4a" / "android" / "darkmode.py").unlink()
        target = tree / "java" / "PythonActivity.java"
        target.write_text(target.read_text().replace("// END p4a dark-mode", ""))
        problems = sp.check(sp.load_manifest(), _fake_fetch(REVS))
        assert "p4a/android/darkmode.py: vendored file is missing" in problems
        assert any("// END p4a dark-mode" in p for p in problems)

    def test_sources_that_disagree_are_reported(self, tree):
        revs = {OLD: _upstream(ACTIVITY_V1, ACTIVITY_V2, "v1\n")}
        problems = sp.check(sp.load_manifest(), _fake_fetch(revs))
        assert any("its sources differ" in p for p in problems)


class TestUpdate:
    def test_rewrites_vendored_code_and_the_pin_only(self, tree):
        target = tree / "java" / "PythonActivity.java"
        before = target.read_text()
        changes = sp.update(sp.load_manifest(), NEW, _fake_fetch(REVS))

        assert {rel for rel, _, _ in changes} == {
            "p4a/android/darkmode.py",
            "java/PythonActivity.java",
        }
        after = target.read_text()
        assert "notify(newConfig);" in after
        # Everything outside the fence is kivyforge's and is left alone.
        assert after.replace("        notify(newConfig);\n", "") == before
        assert (tree / "p4a" / "android" / "darkmode.py").read_text() == "v2\n"
        manifest = sp.load_manifest()
        assert manifest.rev == NEW
        assert sp.check(manifest, _fake_fetch(REVS)) == []

    def test_writes_lf(self, tree):
        sp.update(sp.load_manifest(), NEW, _fake_fetch(REVS))
        assert b"\r\n" not in (tree / "java" / "PythonActivity.java").read_bytes()

    def test_main_check_exit_codes(self, tree, capsys):
        assert sp.main(["check"], fetch=_fake_fetch(REVS)) == 0
        (tree / "p4a" / "android" / "darkmode.py").write_text("edited\n")
        assert sp.main(["check"], fetch=_fake_fetch(REVS)) == 1
        assert "FAILED" in capsys.readouterr().err


class TestManifest:
    def test_needs_exactly_one_of_target_or_fragment(self, tmp_path):
        path = tmp_path / "m.toml"
        path.write_text(
            '[upstream]\nrepo = "r"\nrev = "x"\n'
            '[[block]]\nname = "b"\nsource = "s"\nfirst = "f"\n'
        )
        with pytest.raises(sp.SyncError, match="exactly one of target or fragment"):
            sp.load_manifest(path)

    def test_set_pin_moves_only_the_rev_line(self):
        text = MANIFEST
        assert sp.set_pin(text, NEW) == text.replace(OLD, NEW)


class TestRealManifest:
    """The checked-in P4A_VENDOR.toml and the files it names."""

    def test_every_vendored_path_exists(self):
        manifest = sp.load_manifest()
        paths = [f.path for f in manifest.files]
        paths += [b.fragment or b.target for b in manifest.blocks]
        for rel in paths:
            assert rel is not None
            assert (sp.TEMPLATES_ROOT / rel).is_file(), rel

    def test_pin_is_a_full_sha(self):
        assert len(sp.load_manifest().rev) == 40

    def test_every_p4a_file_ships_in_the_wheel(self):
        """A vendored file the package data misses would be absent from an
        installed kivyforge, and its license with it."""
        pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
        globs = pyproject["tool"]["setuptools"]["package-data"][
            "kivyforge.platforms.android.bootstrap"
        ]
        package = REPO / "kivyforge/platforms/android/bootstrap"
        for path in (sp.TEMPLATES_ROOT / "p4a").rglob("*"):
            if not path.is_file():
                continue
            rel = PurePosixPath(path.relative_to(package).as_posix())
            assert any(rel.full_match(g) for g in globs), rel
