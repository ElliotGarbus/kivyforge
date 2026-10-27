"""The four ways this example calls the SwiftBridge shim. iOS only.

Each demo reports through ``log``, a callable that takes one string, so the
UI in ``main.py`` can show it. The Swift side of each demo is in
``swift-shims/Sources/SwiftBridge/``.
"""

from __future__ import annotations

import traceback

from kivy.clock import Clock
from objc_convert import nsstr, to_py
from pyobjus import autoclass, objc_dict, protocol

# Looked up by their @objc(...) runtime names.
Notebook = autoclass("SBNotebook")
Work = autoclass("SBWork")
Metronome = autoclass("SBMetronome")

PRIME_LIMIT = 10_000_000  # a few seconds of work, long enough to cancel


# --- 1 and 2: an object with state, and collections ----------------------


def notebook_demo(log) -> None:
    notebook = Notebook.alloc().initWithTitle_("Groceries")
    notebook.author = "Kivy"  # a Swift var, set as an attribute
    notebook.addNote_("apples and pears")
    count = notebook.addNotes_(["more apples", "bread"])  # a flat list of str
    log(f"{nsstr(notebook.title)} by {nsstr(notebook.author)}: {count} notes")
    log(f"notes: {to_py(notebook.notes)}")
    log(f"wordCounts(): {to_py(notebook.wordCounts())}")
    log(f"summary(): {to_py(notebook.summary())}")

    # A dict argument goes through objc_dict(). A plain dict reaches Swift
    # with its keys and values swapped in pyobjus 1.2.5.
    keys = notebook.applyOptions_(objc_dict({"author": "Swift", "keepLast": 2}))
    log(f"applyOptions: got {to_py(keys)}; author is now {nsstr(notebook.author)}")
    log(f"notes kept: {to_py(notebook.notes)}")

    # A throwing method returns None when it throws.
    first = notebook.noteAtIndex_error_(0, None)
    missing = notebook.noteAtIndex_error_(10, None)
    log(f"noteAtIndex 0: {nsstr(first)!r}")
    log(f"noteAtIndex 10: {missing!r}, because {nsstr(notebook.lastError)}")


# --- 3: async work, polled from Kivy's Clock -----------------------------


class JobWatcher:
    """Polls an SBJob until it finishes, then reports its outcome."""

    # Kivy's Clock holds a bound method weakly, so a watcher nobody else
    # references would be collected and stop polling. Keep each one here
    # until its job finishes.
    _active: set[JobWatcher] = set()

    def __init__(self, label: str, job, log, on_done=None) -> None:
        self.label = label
        self.job = job
        self.log = log
        self.on_done = on_done
        self._last_tenth = -1
        JobWatcher._active.add(self)
        Clock.schedule_interval(self._poll, 0.1)

    def cancel(self) -> None:
        self.job.cancel()

    def _poll(self, _dt) -> bool:
        if not self.job.isFinished:
            tenth = int(self.job.progress * 10)
            if tenth != self._last_tenth and tenth > 0:
                self._last_tenth = tenth
                self.log(f"{self.label}: {tenth * 10}%")
            return True  # keep polling
        state = nsstr(self.job.state)
        if state == "done":
            self.log(f"{self.label}: done, result {to_py(self.job.result)}")
        elif state == "failed":
            self.log(f"{self.label}: failed, {nsstr(self.job.errorMessage)}")
        else:
            self.log(f"{self.label}: {state}")
        JobWatcher._active.discard(self)
        if self.on_done is not None:
            self.on_done(self)
        return False  # stop polling


def count_primes(log, on_done=None) -> JobWatcher:
    job = Work.countPrimesBelow_(PRIME_LIMIT)
    return JobWatcher("count primes", job, log, on_done)


def notification_settings(log) -> JobWatcher:
    return JobWatcher("notification settings", Work.notificationSettings(), log)


def failing_work(log) -> JobWatcher:
    return JobWatcher("failing work", Work.failingWork(), log)


# --- 4: a Swift protocol implemented in Python ---------------------------


class MetronomeListener:
    """Implements SBMetronomeDelegate.

    Every method catches its own exceptions: in pyobjus 1.2.5 an exception
    that escapes a delegate method is never cleared and later ends the app.
    The methods return nothing, because Swift would not see a return value.
    """

    def __init__(self, log) -> None:
        self.log = log

    @protocol("SBMetronomeDelegate")
    def metronome_didTick_(self, metronome, count) -> None:
        try:
            self.log(f"tick {count}")
        except Exception:
            traceback.print_exc()

    @protocol("SBMetronomeDelegate")
    def metronome_didStopWithSummary_(self, metronome, summary) -> None:
        try:
            self.log(f"metronome stopped: {to_py(summary)}")
        except Exception:
            traceback.print_exc()


class MetronomeDemo:
    """One Metronome and one listener for the life of the app.

    pyobjus keeps every Python delegate alive for good, so create the
    listener once and reuse it rather than making one per start.
    """

    def __init__(self, log) -> None:
        self.listener = MetronomeListener(log)
        self.metronome = Metronome.alloc().init()
        self.metronome.interval = 0.5
        self.metronome.maxTicks = 6
        self.metronome.delegate = self.listener

    @property
    def running(self) -> bool:
        return bool(self.metronome.isRunning)

    def toggle(self) -> None:
        if self.running:
            self.metronome.stop()
        else:
            self.metronome.start()
