"""Turn a streamed ``pip --progress-bar raw`` run into progress (#84, #88).

Every pip-based lock resolver (Android, iOS, and the desktop wheel+runtime
engine) runs pip through ``kivyforge.streaming.run_streaming`` and hands each
output segment to a ``PipProgress``: a ``Downloading`` line names the file, and
the ``Progress N of M`` lines that follow become a byte bar on a terminal or
throttled lines in a log (``docs/design/dev/download-progress-output.md``).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ..streaming import elapsed

#: pip's arguments for machine-readable byte counts, even when not on a terminal.
PROGRESS_ARGS = ("--progress-bar", "raw")

_DOWNLOADING = re.compile(r"^\s*Downloading (\S+)(?: \(([^)]+)\))?")
_PROGRESS = re.compile(r"^Progress (\d+) of (\d+)$")


class PipProgress:
    """Turn ``pip --progress-bar raw`` output into transfer events."""

    def __init__(
        self,
        label: str,
        on_progress: Callable[[str], None] | None,
        on_transfer: Callable[[str, int, int, str], None] | None,
    ) -> None:
        self._label = label
        self._on_progress = on_progress
        self._on_transfer = on_transfer
        self._current = ""

    def __call__(self, segment: str) -> bool:
        line = segment.strip()
        downloading = _DOWNLOADING.match(line)
        if downloading:
            self._current = f"[lock] {self._label}: {short_name(downloading.group(1))}"
            return False
        progress = _PROGRESS.match(line)
        if progress and self._current and self._on_transfer is not None:
            done, total = int(progress.group(1)), int(progress.group(2))
            self._on_transfer(self._current, done, total, "bytes")
            return True
        return False

    def quiet(self, seconds: float) -> None:
        if self._on_progress is not None:
            self._on_progress(
                f"[lock] {self._label}: still resolving ({elapsed(seconds)})"
            )


def short_name(url: str) -> str:
    """``.../Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl`` -> ``Kivy-2.3.1``.

    The ABI or slice is already in the label, and the full filename does not
    fit beside a bar in a narrow terminal.
    """
    filename = url.rsplit("/", 1)[-1]
    if filename.endswith(".whl"):
        return "-".join(filename.split("-")[:2])
    return filename


def without_progress(transcript: str) -> str:
    """pip's output for an error message, minus the raw byte-count lines."""
    return "\n".join(
        line for line in transcript.splitlines() if not _PROGRESS.match(line.strip())
    )
