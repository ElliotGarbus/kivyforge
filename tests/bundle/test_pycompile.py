"""kivyforge.bundle.pycompile — shared byte-compile/strip mechanics."""

from __future__ import annotations

import sys

import pytest

from kivyforge.bundle.pycompile import PycompileError, byte_compile, strip_sources


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
        import greet

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
