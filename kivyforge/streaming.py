"""Run a slow tool and show what it is doing (issues #74 and #84).

pip, Gradle and sdkmanager all do long downloads. Captured whole, they look
like a hang; passed through raw, they are either silent (Gradle, pip when not
on a terminal) or a wall of carriage-return redraws (sdkmanager). This runs the
tool, hands each output segment to a parser that decides what is worth a line,
and reports "still working" when nothing has been shown for a while, so a slow
step and a stuck one look different.
"""

from __future__ import annotations

import io
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

# Segments are split on \r as well as \n: sdkmanager redraws its bar with \r.
_SEGMENT_END = re.compile(rb"[\r\n]+")


def run_streaming(
    cmd: Sequence[str],
    *,
    on_segment: Callable[[str], bool],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    on_quiet: Callable[[float], None] | None = None,
    quiet_sec: float = 30.0,
) -> tuple[int, str]:
    """Run ``cmd`` to completion, feeding its output to ``on_segment`` live.

    stdout and stderr are merged. ``on_segment`` returns whether it showed
    anything; ``on_quiet(elapsed)`` is called each time ``quiet_sec`` passes
    with nothing shown. Returns the exit status and the whole output, for the
    caller's error message.
    """
    proc = subprocess.Popen(
        list(cmd),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    segments: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        # Binary pipe (no text=), so this is a BufferedReader: read1 returns
        # whatever has arrived instead of waiting for a full buffer.
        stream = cast(io.BufferedReader, proc.stdout)
        pending = b""
        while chunk := stream.read1(65536):
            parts = _SEGMENT_END.split(pending + chunk)
            pending = parts.pop()
            for part in parts:
                if part.strip():
                    segments.put(part.decode("utf-8", errors="replace"))
        if pending.strip():
            segments.put(pending.decode("utf-8", errors="replace"))
        segments.put(None)

    threading.Thread(target=pump, daemon=True).start()
    seen: list[str] = []
    start = last_shown = time.monotonic()
    while True:
        try:
            segment = segments.get(timeout=1.0)
        except queue.Empty:
            segment = ""
        if segment is None:
            break
        if segment:
            seen.append(segment)
            if on_segment(segment):
                last_shown = time.monotonic()
        now = time.monotonic()
        if on_quiet is not None and now - last_shown >= quiet_sec:
            on_quiet(now - start)
            last_shown = now
    return proc.wait(), "\n".join(seen)


def elapsed(seconds: float) -> str:
    """``95.0`` -> ``"1m 35s"``; ``40.0`` -> ``"40s"``."""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"
