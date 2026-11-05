"""kivyforge.bundle.pycompile — shared byte-compile/strip mechanics."""

from __future__ import annotations

import importlib
import sys

import pytest

from kivyforge.bundle.pycompile import (
    Candidate,
    PycompileError,
    _accept,
    byte_compile,
    compile_stdlib,
    find_interpreter,
    no_interpreter,
    select_compiler,
    stdlib_dir,
    strip_sources,
    target_minor,
)
from kivyforge.report import diagnostics, exit_codes


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

    def test_unknown_compiler_is_classified_toolchain_missing(self, tmp_path):
        # The compiler is a spawned tool like any other, so a build that cannot
        # start it must say "fix the environment" (exit 3), not "fix the file".
        tree = tmp_path / "app"
        _write(tree / "main.py")
        with pytest.raises(PycompileError, match="could not run") as excinfo:
            byte_compile(
                [tree], compiler=("no-such-interpreter-xyz",), stripdir=tmp_path
            )
        assert excinfo.value.code == diagnostics.TOOLCHAIN_MISSING
        assert excinfo.value.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert excinfo.value.context == {"tool": "no-such-interpreter-xyz"}

    def test_pyc_records_stripdir_relative_path(self, tmp_path):
        # A .pyc embeds the source path it was compiled from; stripdir keeps
        # that relative rather than leaking the tmp_path host path.
        tree = tmp_path / "app"
        _write(tree / "main.py")
        byte_compile([tree], stripdir=tmp_path)
        pyc = next((tree / "__pycache__").glob("*.pyc"))
        assert str(tmp_path) not in pyc.read_bytes().decode("latin-1")


class TestStdlibDir:
    """Located by looking for ``os.py``, so a runtime bump cannot no-op this."""

    def test_windows_layout(self, tmp_path):
        _write(tmp_path / "Lib" / "os.py")
        assert stdlib_dir(tmp_path) == tmp_path / "Lib"

    def test_posix_layout(self, tmp_path):
        _write(tmp_path / "lib" / "python3.13" / "os.py")
        assert stdlib_dir(tmp_path) == tmp_path / "lib" / "python3.13"

    def test_a_lib_dir_without_a_stdlib_is_not_one(self, tmp_path):
        # The AppDir's usr/lib holds site-packages, not a stdlib.
        _write(tmp_path / "lib" / "python3.13" / "somewheel" / "__init__.py")
        assert stdlib_dir(tmp_path) is None

    def test_absent_runtime(self, tmp_path):
        assert stdlib_dir(tmp_path) is None


class TestCompileStdlib:
    def _home(self, tmp_path):
        home = tmp_path / "python"
        _write(home / "Lib" / "os.py")
        _write(home / "Lib" / "json" / "decoder.py")
        _write(home / "Lib" / "site-packages" / "kivy" / "__init__.py")
        return home

    def test_compiles_the_stdlib_and_keeps_the_sources(self, tmp_path):
        home = self._home(tmp_path)
        compile_stdlib(home, stripdir=tmp_path)
        # Sources stay: they are what tracebacks, inspect and linecache read.
        assert (home / "Lib" / "os.py").is_file()
        assert (home / "Lib" / "__pycache__").glob("os.*.pyc")
        assert list((home / "Lib" / "json" / "__pycache__").glob("decoder.*.pyc"))

    def test_site_packages_is_left_to_the_payload_compile(self, tmp_path):
        home = self._home(tmp_path)
        compile_stdlib(home, stripdir=tmp_path)
        # The caller compiles it under its own strip setting; doing it here too
        # would compile it twice and, worse, without that setting.
        assert not list((home / "Lib" / "site-packages").rglob("*.pyc"))

    def test_absent_stdlib_is_a_no_op(self, tmp_path):
        compile_stdlib(tmp_path / "python", stripdir=tmp_path)  # no raise

    def test_announces_itself(self, tmp_path):
        home = self._home(tmp_path)
        said: list[str] = []
        compile_stdlib(home, stripdir=tmp_path, echo=said.append)
        assert said == ["[stage] byte-compiling the embedded stdlib"]


class TestTargetMinor:
    def test_plain_version(self):
        assert target_minor("3.14.6") == (3, 14)

    def test_release_candidate_suffix_is_tolerated(self):
        assert target_minor("3.14.0rc2") == (3, 14)


_PYCOMPILE = "kivyforge.bundle.pycompile"


@pytest.fixture(autouse=True)
def _no_uv(monkeypatch):
    """uv is optional, and whether this host has it must not reach a test."""
    monkeypatch.setattr(f"{_PYCOMPILE}._uv_executable", lambda: None)


def _versions(table):
    """A ``_probe_version`` stand-in: argv -> version_info tuple, else absent."""
    return lambda argv: table.get(argv)


class TestPreReleaseInterpretersRejected:
    """A pre-release of the *right* minor must not be used as the compiler.

    CPython bumps the .pyc magic number through the alpha/beta cycle and only
    freezes it at the first release candidate, so 3.14.0a7 (magic 3621) writes
    bytecode that shipped 3.14.6 (magic 3627) refuses to import — while still
    answering "3.14" to a bare version check. Caught in the field: an Android
    build picked a 3.14.0a7 and produced an unbootable bundle, visible only
    because two 3.14 stdlib modules use t-string syntax the alpha cannot parse.
    """

    def _fake_interpreter(self, monkeypatch, version: str, releaselevel: str):
        """Stand in for a real interpreter answering the probe."""
        import subprocess

        major, minor, micro = version.split(".")

        class _Proc:
            returncode = 0
            stdout = f"{major} {minor} {micro} {releaselevel} 1\n"
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())

    def _accepts(self) -> bool:
        return _accept(("python3.14",), "3.14", "python3.14", [])

    def test_final_release_accepted(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14.6", "final")
        assert self._accepts() is True

    def test_alpha_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14.0", "alpha")
        assert self._accepts() is False

    def test_beta_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14.0", "beta")
        assert self._accepts() is False

    def test_release_candidate_rejected(self, monkeypatch):
        # Safe in principle (the magic freezes at rc1), but the margin is not
        # worth it when the fallback is simply shipping readable source.
        self._fake_interpreter(monkeypatch, "3.14.0", "candidate")
        assert self._accepts() is False

    def test_wrong_minor_still_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.13.9", "final")
        assert self._accepts() is False

    def test_running_under_a_prerelease_is_not_used_in_process(self, monkeypatch):
        """The `return ()` in-process shortcut needs the same guard."""
        version = f"{sys.version_info[0]}.{sys.version_info[1]}.0"
        monkeypatch.setattr(f"{_PYCOMPILE}.is_final_release", lambda: False)
        # No other interpreter can be found either, so the search degrades.
        monkeypatch.setattr(f"{_PYCOMPILE}._probe_version", lambda argv: None)
        assert find_interpreter(version) is None


class TestFindInterpreter:
    def test_this_interpreter_is_used_when_it_matches(self):
        version = f"{sys.version_info[0]}.{sys.version_info[1]}.0"
        assert find_interpreter(version) == ()

    def test_a_matching_interpreter_elsewhere_is_found(self, monkeypatch):
        """The whole point: kivyforge need not *run* on the target's minor."""
        monkeypatch.setattr(
            f"{_PYCOMPILE}._probe_version",
            _versions({("python9.9",): (9, 9, 0, "final", 0)}),
        )
        assert find_interpreter("9.9.1") == ("python9.9",)

    def test_no_match_degrades_to_none(self, monkeypatch):
        monkeypatch.setattr(f"{_PYCOMPILE}._probe_version", lambda argv: None)
        assert find_interpreter("9.9.1") is None

    def test_records_what_it_looked_at(self, monkeypatch):
        """Issue #209: the failure has to be able to say what was searched."""
        monkeypatch.setattr(f"{_PYCOMPILE}.os.name", "posix")
        monkeypatch.setattr(
            f"{_PYCOMPILE}._probe_version",
            _versions({("python9",): (9, 8, 3, "final", 0)}),
        )
        searched: list[Candidate] = []
        assert find_interpreter("9.9.1", searched=searched) is None
        assert [(c.label, c.version) for c in searched[1:]] == [
            ("python9.9", None),
            ("python9", "9.8.3"),
            ("python", None),
        ]
        assert searched[0].label.startswith("this interpreter (")


class TestUvIsOptional:
    """``uv python find`` is a last rung, used only when uv is installed.

    An interpreter uv manages is often not on ``PATH``, so without this rung a
    host that has the right Python still failed to byte-compile. uv must never
    be required, so its absence is silent: no candidate, no hint to install it.
    """

    def _uv(self, monkeypatch, *, found):
        monkeypatch.setattr(f"{_PYCOMPILE}._uv_executable", lambda: "/bin/uv")
        monkeypatch.setattr(f"{_PYCOMPILE}._uv_find", lambda uv, tag: found)

    def test_found_by_uv_when_path_has_nothing(self, monkeypatch):
        self._uv(monkeypatch, found=("/uv/python9.9",))
        monkeypatch.setattr(
            f"{_PYCOMPILE}._probe_version",
            _versions({("/uv/python9.9",): (9, 9, 0, "final", 0)}),
        )
        assert find_interpreter("9.9.1") == ("/uv/python9.9",)

    def test_uv_answer_gets_the_same_final_release_check(self, monkeypatch):
        self._uv(monkeypatch, found=("/uv/python9.9",))
        monkeypatch.setattr(
            f"{_PYCOMPILE}._probe_version",
            _versions({("/uv/python9.9",): (9, 9, 0, "beta", 2)}),
        )
        searched: list[Candidate] = []
        assert find_interpreter("9.9.1", searched=searched) is None
        assert searched[-1] == Candidate("uv python find (/uv/python9.9)", "9.9.0b2")

    def test_uv_with_no_match_is_reported(self, monkeypatch):
        self._uv(monkeypatch, found=None)
        monkeypatch.setattr(f"{_PYCOMPILE}._probe_version", lambda argv: None)
        searched: list[Candidate] = []
        assert find_interpreter("9.9.1", searched=searched) is None
        assert searched[-1] == Candidate("uv python find", None)

    def test_no_uv_leaves_no_trace(self, monkeypatch):
        monkeypatch.setattr(f"{_PYCOMPILE}._probe_version", lambda argv: None)
        searched: list[Candidate] = []
        find_interpreter("9.9.1", searched=searched)
        assert not any(c.label.startswith("uv") for c in searched)

    def test_uv_find_stays_off_the_network(self, monkeypatch):
        import subprocess

        from kivyforge.bundle.pycompile import _uv_find

        seen = {}

        class _Proc:
            returncode = 0
            stdout = "/uv/python9.9\n"

        def run(cmd, **kwargs):
            seen["cmd"], seen["stdin"] = cmd, kwargs.get("stdin")
            return _Proc()

        monkeypatch.setattr(subprocess, "run", run)
        assert _uv_find("/bin/uv", "9.9") == ("/uv/python9.9",)
        assert "--no-python-downloads" in seen["cmd"]
        assert "--no-project" in seen["cmd"]
        assert seen["stdin"] is subprocess.DEVNULL


class TestNoInterpreterMessage:
    """One wording for six backends and doctor (issue #209).

    The old message led with "Pre-releases do not count", which read as
    kivyforge believing 3.15 unreleased; the reporter simply had no 3.15 on
    ``PATH``. The note now appears only when a pre-release was actually seen.
    """

    TABLE = "tool.kivy.ios.python.build_settings"

    def _missing(self, *searched):
        return no_interpreter("3.15.2", table=self.TABLE, searched=list(searched))

    def test_names_what_was_searched_and_found(self):
        missing = self._missing(
            Candidate("python3.15", None), Candidate("python3", "3.14.7")
        )
        assert missing.headline == (
            "no final CPython 3.15 found (this project ships 3.15.2)"
        )
        detail = missing.detail()
        assert "  python3.15: not found" in detail
        assert "  python3: 3.14.7" in detail
        assert "pre-release" not in detail

    def test_prerelease_note_only_when_one_was_seen(self):
        missing = self._missing(Candidate("python3.15", "3.15.0rc1"))
        assert "3.15.0rc1 is a pre-release" in missing.detail()

    def test_other_minors_prerelease_is_not_mentioned(self):
        missing = self._missing(Candidate("python3", "3.16.0a1"))
        assert "pre-release" not in missing.detail()

    def test_fix_names_the_table_and_an_install_route(self):
        fix = self._missing().lines[-1]
        assert fix.startswith("Fix: install any final CPython 3.15.x")
        assert "uv python install 3.15" in fix
        assert f"[{self.TABLE}]" in fix

    def test_required_message_shape(self):
        message = self._missing(Candidate("python3", "3.14.7")).required(self.TABLE)
        assert message.startswith(
            f"[{self.TABLE}].byte_compile = true, but no final CPython 3.15 found"
        )

    def test_classified_as_a_missing_tool(self):
        """Exit 3, "fix the machine": it was KF-ERROR / exit 1 before #209."""
        classification = self._missing().classification
        assert classification.get("code") == diagnostics.BYTECOMPILE_NO_INTERP
        assert classification.get("exit_code") == exit_codes.ENVIRONMENT_ERROR
        assert classification.get("context") == {"tool": "python3.15"}

    def test_encodes_for_a_redirected_stream(self):
        missing = self._missing(Candidate("python3.15", "3.15.0b1"))
        missing.required(self.TABLE).encode("cp1252")


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
            f"{_PYCOMPILE}._probe_version",
            _versions({("python9.9",): (9, 9, 0, "final", 0)}),
        )
        assert select_compiler(
            staged_interpreter=staged, native=False, python_version="9.9.1"
        ) == ("python9.9",)

    def test_missing_staged_interpreter_still_searches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            f"{_PYCOMPILE}._probe_version",
            _versions({("python9.9",): (9, 9, 0, "final", 0)}),
        )
        assert select_compiler(
            staged_interpreter=tmp_path / "absent",
            native=True,
            python_version="9.9.1",
        ) == ("python9.9",)

    def test_degrades_when_nothing_matches(self, tmp_path, monkeypatch):
        monkeypatch.setattr(f"{_PYCOMPILE}._probe_version", lambda argv: None)
        searched: list[Candidate] = []
        assert (
            select_compiler(
                staged_interpreter=tmp_path / "absent",
                native=False,
                python_version="9.9.1",
                searched=searched,
            )
            is None
        )
        assert searched, "the search is passed through for the failure message"


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
