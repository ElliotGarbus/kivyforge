"""Hand a child process kivyforge's stderr (build-package-output-proposal §4.2).

A build tool's transcript is progress, so it belongs on stderr -- and it gets
there by giving the child our stderr *descriptor*, not by reading its lines and
re-printing them. Passing the descriptor delivers the bytes exactly as the tool
wrote them; a text-mode pump re-encodes them for the console and can silently
mangle anything outside that code page.

The one catch is that a real descriptor is not always there: Click's
``CliRunner`` and pytest's capture replace ``sys.stderr`` with an in-memory
stream. Then, and only then, a byte pump copies the child's output into
whatever ``sys.stderr`` currently is.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager


def _real_fileno(stream) -> int | None:
    try:
        return stream.fileno()
    except (AttributeError, OSError, ValueError):
        return None


@contextmanager
def stderr_for_child() -> Iterator[int]:
    """Yield a descriptor to pass as a child's ``stdout``/``stderr``.

    Use it around the whole ``subprocess.run`` call: in the fallback case the
    pump drains on exit, so the child's output has fully arrived by then.
    """
    # Our own buffered lines must land before the child starts writing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass

    target = sys.stderr
    fd = _real_fileno(target)
    if fd is not None:
        yield fd
        return

    read_fd, write_fd = os.pipe()
    pump = threading.Thread(target=_pump, args=(read_fd, target), daemon=True)
    pump.start()
    try:
        yield write_fd
    finally:
        # The child's copy closed when it exited; closing ours sends EOF.
        os.close(write_fd)
        pump.join()
        os.close(read_fd)


def _pump(read_fd: int, target) -> None:
    binary = getattr(target, "buffer", None)
    while chunk := os.read(read_fd, 65536):
        if binary is not None:
            binary.write(chunk)
            binary.flush()
        else:
            target.write(chunk.decode("utf-8", errors="replace"))
            target.flush()
