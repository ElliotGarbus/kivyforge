"""The four ways this example calls the SwiftBridge shim. iOS only.

Rubicon-ObjC, pure Python on top of ``ctypes``, looks the shim's classes up
by their ``@objc(...)`` names and calls them. Each demo reports through
``log``, a callable that takes one string, so the UI in ``main.py`` can show
it. The Swift side of each demo is in ``swift-shims/Sources/SwiftBridge/``.
"""

from __future__ import annotations

from ctypes import byref

from kivy.clock import Clock
from rubicon.objc import NSObject, ObjCClass, ObjCInstance, ObjCProtocol, objc_method
from rubicon.objc import py_from_ns as to_py
from rubicon.objc.runtime import objc_id
from rubicon.objc.types import NSInteger

# Looked up by their @objc(...) runtime names.
Notebook = ObjCClass("SBNotebook")
Work = ObjCClass("SBWork")
Metronome = ObjCClass("SBMetronome")

PRIME_LIMIT = 10_000_000  # a few seconds of work, long enough to cancel
METRONOME_TICKS = 6


# --- 1 and 2: an object with state, and collections ----------------------


def notebook_demo(log) -> None:
    notebook = Notebook.alloc().initWithTitle("Groceries")
    notebook.author = "Kivy"  # a Swift var, set as an attribute
    notebook.addNote("apples and pears")
    count = notebook.addNotes(["more apples", "bread"])
    # A returned NSString formats and compares like a str; str() makes one.
    log(f"{notebook.title} by {notebook.author}: {count} notes")
    log(f"notes: {to_py(notebook.notes)}")
    log(f"wordCounts(): {to_py(notebook.wordCounts())}")
    log(f"summary(): {to_py(notebook.summary())}")

    # A plain dict converts correctly; no wrapper needed.
    keys = notebook.applyOptions({"author": "Swift", "keepLast": 2})
    log(f"applyOptions: got {to_py(keys)}; author is now {notebook.author}")
    log(f"notes kept: {to_py(notebook.notes)}")

    # A throwing method takes a pointer to an NSError variable, and returns
    # None when it throws.
    error = objc_id()
    first = notebook.noteAtIndex(0, error=byref(error))
    log(f"noteAtIndex 0: {str(first)!r}")
    missing = notebook.noteAtIndex(10, error=byref(error))
    reason = ObjCInstance(error).localizedDescription if error else None
    log(f"noteAtIndex 10: {missing!r}, because {reason}")


# --- 3: async work, through a completion handler or a polled Job --------


def on_kivy_thread(func, *args) -> None:
    """Run ``func(*args)`` on Kivy's thread. Clock.schedule_once is thread-safe."""
    Clock.schedule_once(lambda _dt: func(*args), 0)


def notification_settings(log) -> None:
    # Swift calls this on one of its own threads. A block argument arrives
    # as a bare objc_id pointer, whatever its annotation says.
    def done(settings: objc_id) -> None:
        result = to_py(ObjCInstance(settings))
        on_kivy_thread(log, f"notification settings: done, result {result}")

    Work.notificationSettingsWithCompletionHandler(done)


def failing_work(log) -> None:
    # A throwing async method's handler takes the result and an error; one of
    # them is a null pointer, which is false.
    def done(result: objc_id, error: objc_id) -> None:
        if error:
            message = f"failed, {ObjCInstance(error).localizedDescription}"
        else:
            message = f"done, result {to_py(ObjCInstance(result))}"
        on_kivy_thread(log, f"failing work: {message}")

    Work.failingWorkWithCompletionHandler(done)


class JobWatcher:
    """Polls an SBJob until it finishes. Used for work that reports progress
    and can be cancelled, which a completion handler cannot do."""

    # Kivy's Clock holds a bound method weakly; keep each watcher until its
    # job finishes.
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
        state = str(self.job.state)
        if state == "done":
            self.log(f"{self.label}: done, result {to_py(self.job.result)}")
        else:
            self.log(f"{self.label}: {state}")
        JobWatcher._active.discard(self)
        if self.on_done is not None:
            self.on_done(self)
        return False  # stop polling


def count_primes(log, on_done=None) -> JobWatcher:
    job = Work.countPrimesBelow(PRIME_LIMIT)
    return JobWatcher("count primes", job, log, on_done)


# --- 4: a Swift protocol implemented in Python ---------------------------


class MetronomeListener(NSObject, protocols=[ObjCProtocol("SBMetronomeDelegate")]):
    """Implements SBMetronomeDelegate as a real Objective-C class.

    Objective-C class names are global to the process, so this class can be
    defined only once: keep it at module level. An exception raised here is
    printed and ignored, and Swift reads zero, false or nil.
    """

    @objc_method
    def metronome_didTick_(self, metronome, count: NSInteger) -> None:
        self.log(f"tick {count}")

    @objc_method
    def metronome_didStopWithSummary_(self, metronome, summary) -> None:
        self.log(f"metronome stopped: {to_py(summary)}")

    # Swift reads the return value and stops after this tick on False.
    @objc_method
    def metronome_shouldContinueAfter_(self, metronome, count: NSInteger) -> bool:
        return count < METRONOME_TICKS


class MetronomeDemo:
    """One Metronome and one listener for the life of the app.

    The Metronome's delegate is weak and Rubicon-ObjC does not keep the
    listener alive for it, so this object holds the reference.
    """

    def __init__(self, log) -> None:
        self.listener = MetronomeListener.alloc().init()
        self.listener.log = log  # a Python attribute on an Objective-C object
        self.metronome = Metronome.alloc().init()
        self.metronome.interval = 0.5
        self.metronome.delegate = self.listener

    @property
    def running(self) -> bool:
        return bool(self.metronome.isRunning)

    def toggle(self) -> None:
        if self.running:
            self.metronome.stop()
        else:
            self.metronome.start()
