"""Download progress rendering: Rich bars on a terminal, lines elsewhere."""

from __future__ import annotations

import io
import re

import pytest
from rich.console import Console

from kivyforge.report.console import Report
from kivyforge.report.transfers import (
    PercentThrottle,
    TransferLines,
    TransferRenderer,
    megabytes,
)

LABEL = "[lock] arm64_v8a: Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl"


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).replace("\r", "\n")


class TestPercentThrottle:
    def test_first_steps_and_last_are_due(self):
        throttle = PercentThrottle(step=10, interval=999)
        due = [pct for pct in (0, 3, 9, 10, 15, 20, 100) if throttle.due(pct)]
        assert due == [0, 10, 20, 100]

    def test_a_slow_transfer_still_shows_movement(self, monkeypatch):
        clock = iter([0.0, 0.0, 11.0])
        monkeypatch.setattr(
            "kivyforge.report.transfers.time.monotonic", lambda: next(clock)
        )
        throttle = PercentThrottle(step=10, interval=10)
        assert throttle.due(1)
        assert throttle.due(2)  # only 1 point, but 11 s since the last line

    def test_never_goes_backwards(self):
        throttle = PercentThrottle()
        assert throttle.due(50)
        assert not throttle.due(40)


class TestTransferLines:
    def test_bytes_lines_name_the_size(self):
        lines: list[str] = []
        render = TransferLines(lines.append)
        for done in (0, 2_000_000, 8_889_878):
            render(LABEL, done, 8_889_878, "bytes")
        assert lines[0] == f"{LABEL}  0% of 8.9 MB"
        assert lines[-1] == f"{LABEL}  100% of 8.9 MB"

    def test_a_small_file_gets_one_line_at_the_end(self):
        lines: list[str] = []
        render = TransferLines(lines.append)
        for done in (0, 20_000, 37_210):
            render("[download] filetype-1.2.0 (any)", done, 37_210, "bytes")
        assert lines == ["[download] filetype-1.2.0 (any)  100% of 37 kB"]

    def test_sizes_are_readable(self):
        assert megabytes(8_889_878) == "8.9 MB"
        assert megabytes(37_210) == "37 kB"
        assert megabytes(1) == "1 kB"

    def test_percent_lines_have_no_size(self):
        lines: list[str] = []
        TransferLines(lines.append)("[sdk] NDK", 40, 100, "percent")
        assert lines == ["[sdk] NDK  40%"]

    def test_unknown_total_is_ignored(self):
        lines: list[str] = []
        TransferLines(lines.append)(LABEL, 5, 0, "bytes")
        assert lines == []

    def test_a_label_starts_over_after_it_finishes(self):
        lines: list[str] = []
        render = TransferLines(lines.append)
        render("x", 100, 100, "percent")
        render("x", 0, 100, "percent")
        assert lines == ["x  100%", "x  0%"]


class TestTransferRenderer:
    def test_not_a_terminal_means_lines(self):
        lines: list[str] = []
        console = Console(file=io.StringIO(), force_terminal=False)
        TransferRenderer(console, lines.append)(LABEL, 1_000_000, 2_000_000, "bytes")
        assert lines == [f"{LABEL}  50% of 2.0 MB"]

    def test_a_terminal_draws_a_bar_and_keeps_the_label(self):
        """markup off: Rich would otherwise eat "[lock]" as a style tag."""
        out = io.StringIO()
        console = Console(file=out, force_terminal=True, markup=False)
        render = TransferRenderer(console, console.print)
        for done in (0, 4_000_000, 8_889_878):
            render("[lock] arm64_v8a: Kivy-2.3.1", done, 8_889_878, "bytes")
        text = _plain(out.getvalue())
        assert "[lock] arm64_v8a: Kivy-2.3.1" in text
        assert "100%" in text
        assert f"{megabytes(8_889_878)} / {megabytes(8_889_878)}" in text

    def test_a_label_too_long_for_the_width_is_cut_not_wrapped(self):
        out = io.StringIO()
        console = Console(file=out, force_terminal=True, markup=False)
        render = TransferRenderer(console, console.print)
        render("[lock] " + "x" * 200, 10, 10, "bytes")
        last = [line for line in _plain(out.getvalue()).splitlines() if line][-1]
        assert last.startswith("[lock] xxx")
        assert "…" in last  # the ellipsis
        assert "100%" in last

    def test_messages_during_a_bar_print_through_the_live_console(self):
        out = io.StringIO()
        console = Console(file=out, force_terminal=True, width=100, markup=False)
        render = TransferRenderer(console, console.print)
        render(LABEL, 1, 10, "bytes")
        assert render.active
        render.print("[lock] x86_64: resolving wheels")
        render(LABEL, 10, 10, "bytes")
        assert not render.active
        assert "[lock] x86_64: resolving wheels" in _plain(out.getvalue())

    def test_the_live_bar_wraps_to_the_terminal_width(self):
        """The report console soft-wraps; a live display must not, or each
        refresh piles up on one line instead of redrawing."""
        console = Console(file=io.StringIO(), force_terminal=True, soft_wrap=True)
        render = TransferRenderer(console, console.print)
        render(LABEL, 1, 10, "bytes")
        assert render._live_console is not None
        assert render._live_console.soft_wrap is False
        render.close()

    def test_close_is_safe_twice_and_without_a_bar(self):
        console = Console(file=io.StringIO(), force_terminal=True)
        render = TransferRenderer(console, console.print)
        render.close()
        render(LABEL, 1, 10, "bytes")
        render.close()
        render.close()


class TestReport:
    @pytest.mark.parametrize("json_mode", [False, True])
    def test_transfer_goes_to_stderr_in_both_modes(self, json_mode):
        out, err = io.StringIO(), io.StringIO()
        report = Report(
            command="lock",
            kivyforge_version="0",
            json_mode=json_mode,
            no_color=True,
            stdout=out,
            stderr=err,
        )
        report.transfer(LABEL, 10, 10, "bytes")
        assert out.getvalue() == ""
        assert f"{LABEL}  100%" in err.getvalue()
