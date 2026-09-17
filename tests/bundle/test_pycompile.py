"""kivyforge.bundle.pycompile — shared byte-compile/strip mechanics."""

from __future__ import annotations

import importlib
import sys

import pytest

from kivyforge.bundle.pycompile import (
    PycompileError,
    _reports_version,
    byte_compile,
    find_interpreter,
    select_compiler,
    strip_sources,
    target_minor,
)


def _write(path, text="x = 1\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestByteCompile:
    def test_keeps_source_by_default(self, tmp_path):
        tree = tmp_path / "app"
        _write(tree / "main.py")
        byte_compile([tree], stripdir=tmp_path)
        assert (tree / "main.py").is_file()
        assert list(tree.rglob("*.pyc"))
        # Non-legacy layout: the .pyc lives in __pycache__/, not beside the .py.
        assert list((tree / "__pycache__").glob("*.pyc"))

    def test_strip_source_removes_py_and_pycache(self, tmp_path):
        tree = tmp_path / "app"
        _write(tree / "main.py")
        byte_compile([tree], strip_source=True, stripdir=tmp_path)
        assert not (tree / "main.py").exists()
        assert not (tree / "__pycache__").exists()
        # Legacy (sourceless) layout: foo.pyc sits at foo.py's own path.
        assert (tree / "main.pyc").is_file()

    def test_stripped_module_is_importable(self, tmp_path, monkeypatch):
        tree = tmp_path / "app"
        _write(tree / "greet.py", "def hi():\n    return 'hi'\n")
        byte_compile([tree], strip_source=True, stripdir=tmp_path)
        monkeypatch.syspath_prepend(str(tree))
        greet = importlib.import_module("greet")
        assert greet.hi() == "hi"
        sys.modules.pop("greet", None)

    def test_missing_tree_is_skipped_not_errored(self, tmp_path):
        byte_compile([tmp_path / "does-not-exist"], stripdir=tmp_path)  # no raise

    def test_multiple_trees_all_compiled(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        _write(a / "one.py")
        _write(b / "two.py")
        byte_compile([a, b], strip_source=True, stripdir=tmp_path)
        assert (a / "one.pyc").is_file()
        assert (b / "two.pyc").is_file()

    def test_syntax_error_raises_pycompile_error(self, tmp_path):
        tree = tmp_path / "app"
        _write(tree / "broken.py", "def (\n")
        with pytest.raises(PycompileError, match="byte-compiling"):
            byte_compile([tree], stripdir=tmp_path)

    def test_unknown_compiler_raises_pycompile_error(self, tmp_path):
        tree = tmp_path / "app"
        _write(tree / "main.py")
        with pytest.raises(PycompileError, match="could not run"):
            byte_compile(
                [tree], compiler=("no-such-interpreter-xyz",), stripdir=tmp_path
            )

    def test_pyc_records_stripdir_relative_path(self, tmp_path):
        # A .pyc embeds the source path it was compiled from; stripdir keeps
        # that relative rather than leaking the tmp_path host path.
        tree = tmp_path / "app"
        _write(tree / "main.py")
        byte_compile([tree], stripdir=tmp_path)
        pyc = next((tree / "__pycache__").glob("*.pyc"))
        assert str(tmp_path) not in pyc.read_bytes().decode("latin-1")


class TestTargetMinor:
    def test_plain_version(self):
        assert target_minor("3.14.6") == (3, 14)

    def test_release_candidate_suffix_is_tolerated(self):
        assert target_minor("3.14.0rc2") == (3, 14)


class TestPreReleaseInterpretersRejected:
    """A pre-release of the *right* minor must not be used as the compiler.

    CPython bumps the .pyc magic number through the alpha/beta cycle and only
    freezes it at the first release candidate, so 3.14.0a7 (magic 3621) writes
    bytecode that shipped 3.14.6 (magic 3627) refuses to import — while still
    answering "3.14" to a bare version check. Caught in the field: an Android
    build picked a 3.14.0a7 and produced an unbootable bundle, visible only
    because two 3.14 stdlib modules use t-string syntax the alpha cannot parse.
    """

    def _fake_interpreter(self, monkeypatch, minor: str, releaselevel: str):
        """Stand in for a real interpreter answering the probe."""
        import subprocess

        class _Proc:
            returncode = 0
            stdout = f"{minor} {releaselevel}\n"
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())

    def test_final_release_accepted(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14", "final")
        assert _reports_version(("python3.14",), "3.14") is True

    def test_alpha_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14", "alpha")
        assert _reports_version(("python3.14",), "3.14") is False

    def test_beta_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14", "beta")
        assert _reports_version(("python3.14",), "3.14") is False

    def test_release_candidate_rejected(self, monkeypatch):
        # Safe in principle (the magic freezes at rc1), but the margin is not
        # worth it when the fallback is simply shipping readable source.
        self._fake_interpreter(monkeypatch, "3.14", "candidate")
        assert _reports_version(("python3.14",), "3.14") is False

    def test_wrong_minor_still_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.13", "final")
        assert _reports_version(("python3.14",), "3.14") is False

    def test_running_under_a_prerelease_is_not_used_in_process(self, monkeypatch):
        """The `return ()` in-process shortcut needs the same guard."""
        version = f"{sys.version_info[0]}.{sys.version_info[1]}.0"
        monkeypatch.setattr(
            "kivyforge.bundle.pycompile.is_final_release", lambda: False
        )
        # No other interpreter can be found either, so the search degrades.
        monkeypatch.setattr(
            "kivyforge.bundle.pycompile._reports_version", lambda argv, tag: False
        )
        assert find_interpreter(version) is None


class TestFindInterpreter:
    def test_this_interpreter_is_used_when_it_matches(self):
        version = f"{sys.version_info[0]}.{sys.version_info[1]}.0"
        assert find_interpreter(version) == ()

    def test_a_matching_interpreter_elsewhere_is_found(self, monkeypatch):
        """The whole point: kivyforge need not *run* on the target's minor."""
        monkeypatch.setattr(
            "kivyforge.bundle.pycompile._reports_version",
            lambda argv, tag: argv == ("python9.9",),
        )
        assert find_interpreter("9.9.1") == ("python9.9",)

    def test_no_match_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.bundle.pycompile._reports_version", lambda argv, tag: False
        )
        assert find_interpreter("9.9.1") is None


class TestSelectCompiler:
    """The ladder: staged interpreter (native only) → any final match → degrade.

    The native gate matters because kivyforge never depends on emulation, and
    the fallback is valid because a .pyc's magic number is keyed to CPython's
    minor version, never to architecture.
    """

    def test_staged_interpreter_preferred_when_native(self, tmp_path):
        staged = tmp_path / "python"
        staged.write_text("", encoding="utf-8")
        assert select_compiler(
            staged_interpreter=staged, native=True, python_version="9.9.1"
        ) == (str(staged),)

    def test_staged_interpreter_ignored_when_cross(self, tmp_path, monkeypatch):
        """A foreign-arch binary cannot be run here, so it must not be chosen."""
        staged = tmp_path / "python"
        staged.write_text("", encoding="utf-8")
        monkeypatch.setattr(
            "kivyforge.bundle.pycompile._reports_version",
            lambda argv, tag: argv == ("python9.9",),
        )
        assert select_compiler(
            staged_interpreter=staged, native=False, python_version="9.9.1"
        ) == ("python9.9",)

    def test_missing_staged_interpreter_still_searches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.bundle.pycompile._reports_version",
            lambda argv, tag: argv == ("python9.9",),
        )
        assert select_compiler(
            staged_interpreter=tmp_path / "absent",
            native=True,
            python_version="9.9.1",
        ) == ("python9.9",)

    def test_degrades_when_nothing_matches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.bundle.pycompile._reports_version", lambda argv, tag: False
        )
        assert (
            select_compiler(
                staged_interpreter=tmp_path / "absent",
                native=False,
                python_version="9.9.1",
            )
            is None
        )


class TestStripSources:
    def test_only_removes_py_with_compiled_counterpart(self, tmp_path):
        tree = tmp_path / "app"
        _write(tree / "compiled.py")
        _write(tree / "compiled.pyc", "")
        _write(tree / "uncompiled.py")  # no sibling .pyc
        strip_sources(tree)
        assert not (tree / "compiled.py").exists()
        assert (tree / "uncompiled.py").exists()

    def test_removes_pycache_dirs(self, tmp_path):
        tree = tmp_path / "app"
        _write(tree / "sub" / "__pycache__" / "mod.cpython-314.pyc", "")
        strip_sources(tree)
        assert not (tree / "sub" / "__pycache__").exists()
