"""Download and install progress, drawn by the renderer (issues #74, #84).

Backends report *numbers* -- what is moving, how far it has got, out of how
much -- through ``on_transfer``; they never format a bar. That keeps the
"backends never print" rule and lets the look depend on where output is going:

* **A terminal** gets a live Rich bar per transfer: percentage, size, time left.
* **Anything else** -- a CI log, a redirected stream, ``--no-color`` -- gets a
  few plain lines per transfer, throttled so a slow download keeps showing it
  is alive without flooding the log. A bar there would be a wall of redraws.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Column

#: ``on_transfer(label, done, total, unit)``; ``unit`` is ``"bytes"`` or
#: ``"percent"`` (a tool that reports only a percentage, like sdkmanager).
TransferCallback = Callable[[str, int, int, str], None]


#: Where a transfer deep inside a backend reports, without every call site
#: threading a callback through: the verb layer sets it for the verb's lifetime
#: (``reporting()``, and ``run``), and the shared downloader reads it.
_CURRENT: ContextVar[TransferCallback | None] = ContextVar(
    "kivyforge_transfer", default=None
)


@contextmanager
def transfers_to(callback: TransferCallback | None) -> Iterator[None]:
    """Send transfers reported in this context to ``callback``."""
    token = _CURRENT.set(callback)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def report_transfer(label: str, done: int, total: int, unit: str = "bytes") -> None:
    """Report to the current sink, if a verb has set one; otherwise nothing."""
    callback = _CURRENT.get()
    if callback is not None:
        callback(label, done, total, unit)


def megabytes(n: int) -> str:
    """A size for people: ``8889878`` -> ``8.9 MB``, ``37210`` -> ``37 kB``."""
    if n < 1_000_000:
        return f"{max(1, round(n / 1000))} kB"
    return f"{n / 1_000_000:.1f} MB"


#: Below this, a log gets one line per transfer, at the end: a 30 kB wheel's
#: 0% / 47% / 100% lines are noise, and it is over before anyone reads them.
SMALL_TRANSFER = 1_000_000


class PercentThrottle:
    """Which percentages of a transfer are worth a line.

    Every ``step`` percent, or after ``interval`` seconds if it has moved at
    all, and always the first and the last.
    """

    def __init__(self, step: int = 10, interval: float = 10.0) -> None:
        self._step = step
        self._interval = interval
        self._last_pct = -1
        self._last_time = time.monotonic()

    def due(self, pct: int) -> bool:
        if pct <= self._last_pct:
            return False
        now = time.monotonic()
        if (
            self._last_pct < 0
            or pct >= 100
            or pct - self._last_pct >= self._step
            or now - self._last_time >= self._interval
        ):
            self._last_pct = pct
            self._last_time = now
            return True
        return False


class TransferLines:
    """The no-terminal rendering: throttled ``label  45% of 8.9 MB`` lines."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit
        self._throttles: dict[str, PercentThrottle] = {}

    def __call__(self, label: str, done: int, total: int, unit: str = "bytes") -> None:
        if total <= 0:
            return
        done = max(0, min(done, total))
        pct = done * 100 // total
        small = unit == "bytes" and total < SMALL_TRANSFER
        throttle = self._throttles.setdefault(label, PercentThrottle())
        if (not small or done >= total) and throttle.due(pct):
            size = f" of {megabytes(total)}" if unit == "bytes" else ""
            self._emit(f"{label}  {pct}%{size}")
        if done >= total:
            self._throttles.pop(label, None)


class TransferRenderer:
    """Rich bars on a terminal, :class:`TransferLines` otherwise."""

    def __init__(self, console: Console, emit_line: Callable[[str], None]) -> None:
        self._console = console
        self._lines = TransferLines(emit_line)
        self._live_console: Console | None = None
        self._progress: Progress | None = None
        self._tasks: dict[str, TaskID] = {}

    @property
    def active(self) -> bool:
        return self._progress is not None

    def print(self, text: str) -> None:
        """A progress line while a bar is live: Rich puts it above the bar."""
        if self._progress is not None:
            self._progress.console.print(text)
        else:
            self._console.print(text)

    def __call__(self, label: str, done: int, total: int, unit: str = "bytes") -> None:
        if not self._console.is_terminal:
            self._lines(label, done, total, unit)
            return
        if total <= 0:
            return
        done = max(0, min(done, total))
        progress = self._start()
        detail = f"{megabytes(done)} / {megabytes(total)}" if unit == "bytes" else ""
        task = self._tasks.get(label)
        if task is None:
            task = progress.add_task(label, total=total, detail=detail)
            self._tasks[label] = task
        progress.update(task, completed=done, detail=detail)
        if done >= total:
            del self._tasks[label]
            if not self._tasks:
                self.close()

    def _start(self) -> Progress:
        if self._progress is None:
            # Its own console on the same stream. The report's console sets
            # soft_wrap (its messages arrive pre-wrapped), but a live display
            # must fit and wrap to the width to redraw over itself; with
            # soft_wrap each refresh piled up on one line in a real terminal.
            base = self._console
            self._live_console = Console(
                file=base.file,
                force_terminal=True,
                no_color=base.no_color,
                color_system=base.color_system,  # type: ignore[arg-type]
                markup=False,
                highlight=False,
                emoji=False,
                soft_wrap=False,
            )
            self._progress = Progress(
                # markup=False for the reason console.py gives: our labels start
                # with "[lock]"/"[sdk]", which Rich would read as style tags.
                TextColumn(
                    "{task.description}",
                    markup=False,
                    # Capped, so a long label is cut short instead of pushing
                    # the percentage and size off a narrow terminal; the bar
                    # takes whatever is left.
                    table_column=Column(
                        no_wrap=True, overflow="ellipsis", max_width=40
                    ),
                ),
                BarColumn(bar_width=None, table_column=Column(ratio=1)),
                TaskProgressColumn(),
                TextColumn("{task.fields[detail]}", markup=False),
                TimeRemainingColumn(),
                console=self._live_console,
                expand=True,
            )
            self._progress.start()
        return self._progress

    def close(self) -> None:
        """Stop the live display; finished bars stay on screen as a record."""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._live_console = None
            self._tasks.clear()
