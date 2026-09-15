"""The output seam: stream routing, colour gating, and two rendering hazards.

The routing tests are the load-bearing ones. Everything else in roadmap item 3
assumes "product on stdout, progress on stderr, always", because that is what
makes ``kivyforge build --json > build.json`` parseable while the user still
watches the build.
"""

from __future__ import annotations

import io
import json

import pytest

from kivyforge.report import Diagnostic, Report, diagnostics, want_color


class FakeStream:
    """A text stream that can claim to be a terminal, since colour depends on it.

    Delegates to a ``StringIO`` rather than subclassing it: ``encoding`` is a
    read-only attribute on the C implementation, and both this and Rich need to
    read it.
    """

    def __init__(self, *, tty: bool = False, encoding: str = "utf-8") -> None:
        self._buffer = io.StringIO()
        self._tty = tty
        self.encoding = encoding

    def write(self, text: str) -> int:
        return self._buffer.write(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        if self._buffer.closed:
            # What a real closed stream does, and the branch want_color guards.
            raise ValueError("I/O operation on closed file")
        return self._tty

    def getvalue(self) -> str:
        return self._buffer.getvalue()

    def close(self) -> None:
        self._buffer.close()


@pytest.fixture
def streams() -> tuple[FakeStream, FakeStream]:
    return FakeStream(), FakeStream()


def _report(streams, **kwargs) -> Report:
    out, err = streams
    base = {
        "command": "doctor",
        "kivyforge_version": "3.0.0.dev0",
        "platform": "linux",
        "stdout": out,
        "stderr": err,
        "env": {},
    }
    return Report(**{**base, **kwargs})


class TestWantColor:
    """Precedence, most specific first: flag, NO_COLOR, FORCE_COLOR, isatty."""

    def test_flag_beats_everything(self):
        assert not want_color(
            no_color=True, stream=FakeStream(tty=True), env={"FORCE_COLOR": "1"}
        )

    def test_no_color_beats_force_color(self):
        """Both set is always an accident (a CI image and a user disagreeing).
        Unwanted escape codes corrupt a log; absent colour merely disappoints."""
        assert not want_color(
            no_color=False,
            stream=FakeStream(tty=True),
            env={"NO_COLOR": "1", "FORCE_COLOR": "1"},
        )

    def test_no_color_set_to_zero_still_disables(self):
        """Presence is what counts, per no-color.org. Surprising, but standard."""
        assert not want_color(
            no_color=False, stream=FakeStream(tty=True), env={"NO_COLOR": "0"}
        )

    def test_force_color_wins_over_a_pipe(self):
        assert want_color(
            no_color=False, stream=FakeStream(tty=False), env={"FORCE_COLOR": "1"}
        )

    def test_a_pipe_is_not_coloured(self):
        assert not want_color(no_color=False, stream=FakeStream(tty=False), env={})

    def test_a_terminal_is_coloured(self):
        assert want_color(no_color=False, stream=FakeStream(tty=True), env={})

    def test_a_stream_without_isatty_is_not_a_terminal(self):
        """Test doubles and capture objects have been known to lack it, and a
        crash in the output layer is a poor way to learn that."""

        class Bare:
            encoding = "utf-8"

        assert not want_color(no_color=False, stream=Bare(), env={})

    def test_a_closed_stream_is_not_a_terminal(self):
        stream = FakeStream()
        stream.close()
        assert not want_color(no_color=False, stream=stream, env={})


class TestStreamRoutingHumanMode:
    def test_report_lines_go_to_stdout(self, streams):
        out, err = streams
        _report(streams).line("[PASS] Xcode")
        assert "[PASS] Xcode" in out.getvalue()
        assert err.getvalue() == ""

    def test_progress_goes_to_stderr(self, streams):
        out, err = streams
        _report(streams).progress("[stage] flattening jniLibs")
        assert "[stage] flattening jniLibs" in err.getvalue()
        assert out.getvalue() == ""

    def test_emit_writes_nothing_without_json(self, streams):
        out, err = streams
        _report(streams).emit(ok=True, data={"mode": "project"})
        assert out.getvalue() == ""
        assert err.getvalue() == ""


class TestStreamRoutingJsonMode:
    def test_the_envelope_goes_to_stdout(self, streams):
        out, _ = streams
        _report(streams, json_mode=True).emit(ok=True, data={"mode": "project"})
        assert json.loads(out.getvalue())["data"] == {"mode": "project"}

    def test_report_lines_are_suppressed(self, streams):
        """The envelope supersedes the human report, and anything else on stdout
        makes the document unparseable."""
        out, _ = streams
        report = _report(streams, json_mode=True)
        report.line("kivyforge doctor (linux, project mode)")
        report.status_line("[FAIL] Xcode", "FAIL")
        assert out.getvalue() == ""

    def test_progress_still_reaches_stderr(self, streams):
        """The whole reason for the stdout/stderr split: ``--json`` never has to
        go quiet to stay parseable."""
        _, err = streams
        _report(streams, json_mode=True).progress("[gradle] assembleDebug")
        assert "[gradle] assembleDebug" in err.getvalue()

    def test_stdout_is_only_ever_the_envelope(self, streams):
        out, _ = streams
        report = _report(streams, json_mode=True)
        report.line("noise")
        report.progress("more noise")
        report.emit(ok=True)
        assert json.loads(out.getvalue())["command"] == "doctor"


class TestRenderingHazards:
    """Two ways passing existing text through Rich could go wrong."""

    def test_square_brackets_are_literal_text_not_markup(self, streams):
        """Rich's default ``markup=True`` reads ``[PASS]`` as a style tag and
        raises ``MissingStyle``, because ``PASS`` is not a style. Doctor has
        printed ``[PASS]``-prefixed lines since it existed, so leaving markup on
        would have been a crash caused purely by changing renderer.
        """
        out, _ = streams
        _report(streams).line("[PASS] Xcode: 26.0")
        assert "[PASS] Xcode: 26.0" in out.getvalue()

    def test_user_supplied_brackets_cannot_influence_rendering(self, streams):
        """Content comes from config, paths and subprocess output. A dependency
        named ``foo[bar]`` is ordinary PEP 508 and must render verbatim."""
        out, _ = streams
        _report(streams).line("resolving foo[bar]>=1.0 failed")
        assert "resolving foo[bar]>=1.0 failed" in out.getvalue()

    def test_numbers_and_paths_are_not_auto_highlighted(self, streams):
        """Rich's highlighter would colour the version and the path. On build
        output that is noise, and it would make output assertions depend on
        Rich's heuristics."""
        out, _ = streams
        _report(streams, no_color=False).line("wrote build/linux/app-1.0.0 (3 files)")
        assert out.getvalue() == "wrote build/linux/app-1.0.0 (3 files)\n"

    def test_json_survives_a_cp1252_stdout(self):
        """The scenario commit 219a8148 was about, on the machine path.

        A right arrow has no cp1252 representation, so writing it raw to a
        redirected Windows stdout raises from inside the print. The envelope
        escapes it instead, so the document is written and remains lossless.
        """
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="cp1252", newline="")
        report = Report(
            command="doctor",
            kivyforge_version="3.0.0.dev0",
            json_mode=True,
            stdout=out,
            stderr=FakeStream(),
            env={},
        )
        report.diagnose(
            Diagnostic(
                code=diagnostics.DOCTOR_CHECK,
                severity=diagnostics.WARNING,
                message="a \u2192 b",
            )
        )
        report.emit(ok=True)
        out.flush()

        written = raw.getvalue()
        assert b"\\u2192" in written
        assert json.loads(written.decode("cp1252"))["diagnostics"][0]["message"] == (
            "a \u2192 b"
        )


class TestColour:
    """Colour is applied through explicit styles, so it is gated by one flag."""

    @pytest.fixture(autouse=True)
    def _deterministic_terminal(self, monkeypatch):
        """Rich consults the real environment for terminal capability, so a
        developer's ``TERM=dumb`` or a CI runner's ``NO_COLOR`` would otherwise
        decide these tests."""
        monkeypatch.setenv("TERM", "xterm-256color")
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)

    def test_a_terminal_gets_ansi_escapes(self, streams):
        out, _ = streams
        out._tty = True
        _report(streams, env={"FORCE_COLOR": "1"}).status_line("[FAIL] Xcode", "FAIL")
        assert "\x1b[" in out.getvalue()

    def test_no_color_strips_every_escape_not_just_the_colour(self, streams):
        """Rich's own ``no_color`` drops colour but keeps other SGR attributes,
        so the ``bold red`` FAIL style would still emit ``\\x1b[1m`` on a
        terminal. Anyone passing ``--no-color`` is usually writing to a log or a
        CI transcript, where a stray bold code is as unwelcome as a colour."""
        out, _ = streams
        out._tty = True
        _report(streams, no_color=True, env={"FORCE_COLOR": "1"}).status_line(
            "[FAIL] Xcode", "FAIL"
        )
        assert "\x1b" not in out.getvalue()
        assert "[FAIL] Xcode" in out.getvalue()

    def test_a_pipe_gets_no_escapes_either(self, streams):
        out, _ = streams
        _report(streams).status_line("[FAIL] Xcode", "FAIL")
        assert "\x1b" not in out.getvalue()

    def test_an_unknown_status_renders_unstyled_rather_than_raising(self, streams):
        """A new Status member must not be able to crash the renderer."""
        out, _ = streams
        _report(streams).status_line("[HMM] something new", "HMM")
        assert "[HMM] something new" in out.getvalue()


class TestDiagnosticsCollection:
    def test_diagnostics_reach_the_envelope_in_order(self, streams):
        report = _report(streams)
        for code in ("KF-A", "KF-B"):
            report.diagnose(
                Diagnostic(code=code, severity=diagnostics.WARNING, message="m")
            )
        codes = [d["code"] for d in report.envelope(ok=True).as_dict()["diagnostics"]]
        assert codes == ["KF-A", "KF-B"]
