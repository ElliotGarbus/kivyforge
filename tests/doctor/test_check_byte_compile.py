"""The byte-compile doctor check (roadmap item 1).

The gap being closed: a ``byte_compile`` setting that cannot find a matching
CPython used to surface only when the build ran, and with the default
``"release"`` tri-state it degraded *silently* to shipping source. Severity here
mirrors how the build reads the setting -- ``true`` is "I insist" (FAIL),
``"release"`` is "when it makes sense" (WARN).
"""

from __future__ import annotations

from kivyforge.doctor.checks_common import (
    BYTE_COMPILE_NAME,
    builds_natively,
    check_byte_compile,
)
from kivyforge.doctor.result import Status

from .probe_fakes import FakeProbe

TABLE = "tool.kivy.android.build_settings"


def _check(**kw):
    probe = kw.pop("probe", FakeProbe())
    kw.setdefault("python_version", "3.14.6")
    kw.setdefault("table", TABLE)
    kw.setdefault("native", False)
    return check_byte_compile(probe, **kw)


class TestOffIsNotAProblem:
    def test_byte_compile_false_skips(self):
        result = _check(byte_compile=False, probe=FakeProbe(byte_compiler=None))
        assert result.status is Status.SKIP
        assert "byte_compile = false" in result.detail


class TestCompilerFound:
    def test_release_default_passes(self):
        result = _check(byte_compile="release")
        assert result.status is Status.PASS
        assert result.name == BYTE_COMPILE_NAME

    def test_names_the_interpreter_it_found(self):
        result = _check(
            byte_compile=True, probe=FakeProbe(byte_compiler=("py", "-3.14"))
        )
        assert result.status is Status.PASS
        assert "py -3.14" in result.detail

    def test_this_interpreter_is_named_readably(self):
        """`()` is the resolver's "use this process", not "found nothing"."""
        result = _check(byte_compile=True, probe=FakeProbe(byte_compiler=()))
        assert result.status is Status.PASS
        assert "this interpreter" in result.detail


class TestCompilerMissing:
    """The two severities the roadmap specifies, and the remedy in both."""

    def test_explicit_true_is_a_failure(self):
        result = _check(byte_compile=True, probe=FakeProbe(byte_compiler=None))
        assert result.status is Status.FAIL
        assert "the build will fail" in result.detail

    def test_release_default_is_a_warning(self):
        result = _check(byte_compile="release", probe=FakeProbe(byte_compiler=None))
        assert result.status is Status.WARN
        assert "silently ship source" in result.detail

    def test_both_severities_say_how_to_fix_it(self):
        for setting in (True, "release"):
            result = _check(byte_compile=setting, probe=FakeProbe(byte_compiler=None))
            assert "Fix: install a final CPython 3.14" in result.hint
            assert f"byte_compile = false in [{TABLE}]" in result.hint
            # The *why* matters as much: a matching minor is not sufficient.
            assert "Pre-releases do not count" in result.hint

    def test_reports_the_configured_version_not_just_the_minor(self):
        result = _check(
            byte_compile=True,
            python_version="3.14.6",
            probe=FakeProbe(byte_compiler=None),
        )
        assert "3.14.6" in result.detail


class TestNativeBuildsNeedNoHostInterpreter:
    """When the build can run the interpreter it stages, that shipped runtime
    compiles its own payload and nothing on the host matters."""

    def test_native_passes_even_with_no_host_interpreter(self):
        result = _check(
            byte_compile=True, native=True, probe=FakeProbe(byte_compiler=None)
        )
        assert result.status is Status.PASS
        assert "staged runtime" in result.detail


class TestUnknownVersionSkips:
    def test_no_python_version_configured_skips(self):
        result = _check(byte_compile=True, python_version=None)
        assert result.status is Status.SKIP


class TestBuildsNatively:
    """Conservative on purpose: any foreign arch means the check must evaluate
    the host-interpreter fallback, because that is the rung that build lands on."""

    def test_single_matching_arch_is_native(self):
        assert builds_natively(FakeProbe(machine="arm64"), ("arm64",)) is True

    def test_foreign_arch_is_not_native(self):
        assert builds_natively(FakeProbe(machine="x86_64"), ("aarch64",)) is False

    def test_mixed_archs_are_not_native(self):
        probe = FakeProbe(machine="x86_64")
        assert builds_natively(probe, ("x86_64", "aarch64")) is False

    def test_no_archs_is_not_native(self):
        assert builds_natively(FakeProbe(machine="x86_64"), ()) is False
