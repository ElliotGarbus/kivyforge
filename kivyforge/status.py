"""Structured result types for ``kivyforge status`` (roadmap item 3).

``status`` used to be five backends each calling ``click.echo`` on strings they
had already formatted -- ``"out of date (run `kivyforge lock -p linux`)"`` was a
single value, with the state, the remediation and the presentation fused. Nothing
could consume that but a terminal.

The backends now gather state and return it; ``cli/status.py`` renders it, either
as the human report or as a ``--json`` envelope. Presentation lives in the
``render`` methods here so the two renderers cannot drift, in the same style as
``doctor``'s :class:`~kivyforge.doctor.CheckResult`.

Three duplications collapse into this module on the way: ``_humanize``,
``_lock_state`` and ``_build_state`` existed four times each, once per desktop
backend, character-identical.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

#: Width of the label column in the human report, e.g. ``"Python:     3.13.14"``.
#: Every backend already used 12 -- this just names it.
LABEL_WIDTH = 12

#: Width of the label column for the indented per-artifact lines.
ARTIFACT_LABEL_WIDTH = 20


class LockState(Enum):
    """Whether ``pylock.<platform>.toml`` exists and matches ``pyproject.toml``.

    ``MISSING`` and ``UNREADABLE`` are kept apart from ``OUT_OF_DATE`` even
    though all three are fixed by re-locking: they are different situations, and
    a corrupt lock in particular is worth knowing about rather than silently
    treating as stale.
    """

    MISSING = "missing"
    UNREADABLE = "unreadable"
    IN_SYNC = "in sync"
    OUT_OF_DATE = "out of date"


@dataclass(frozen=True)
class LockStatus:
    state: LockState
    #: The command that fixes a non-``IN_SYNC`` state, without backticks, e.g.
    #: ``kivyforge lock -p linux``. Empty means "do not suggest anything", which
    #: is what Android has always done.
    relock_command: str = ""

    @property
    def in_sync(self) -> bool:
        return self.state is LockState.IN_SYNC

    def render(self) -> str:
        if self.in_sync or not self.relock_command:
            return self.state.value
        return f"{self.state.value} (run `{self.relock_command}`)"

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "state": self.state.value,
            "in_sync": self.in_sync,
        }
        if self.relock_command:
            payload["relock_command"] = self.relock_command
        return payload


@dataclass(frozen=True)
class BuildArtifact:
    """One thing a build produces, and whether it is there.

    *label* distinguishes artifacts on platforms that produce several (iOS builds
    for simulator and device; Android produces a debug APK, a release APK and an
    AAB). Platforms with a single artifact leave it empty, which is what tells
    the renderer to put the state on the ``Build:`` line itself rather than
    opening an indented list.
    """

    path: Path
    label: str = ""
    #: Modification time in epoch seconds, or ``None`` when the artifact does not
    #: exist. Deliberately not a bool plus a timestamp: two fields that must
    #: agree are two fields that can disagree.
    mtime: float | None = None

    @classmethod
    def probe(cls, path: Path, label: str = "") -> BuildArtifact:
        """Build one by looking at the filesystem.

        Tolerates a path that vanishes between the existence check and the
        ``stat`` -- a build running in another window is entirely plausible, and
        ``status`` is read-only enough that it should never be the thing that
        raises.
        """
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        return cls(path=path, label=label, mtime=mtime)

    @property
    def built(self) -> bool:
        return self.mtime is not None

    def render(self, *, now: float | None = None) -> str:
        if self.mtime is None:
            return "not built"
        now = time.time() if now is None else now
        return f"last built {humanize_age(now - self.mtime)}"

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "built": self.built,
            # Reported even when absent: it tells an agent where the artifact
            # *would* be, which is most of the value (agent-friendliness point
            # 2). Posix separators so the value does not change shape by host.
            "path": self.path.as_posix(),
        }
        if self.label:
            payload["label"] = self.label
        if self.mtime is not None:
            payload["mtime"] = self.mtime
        return payload


@dataclass(frozen=True)
class StatusReport:
    """Everything ``status`` knows, for one platform."""

    platform: str
    app_name: str
    #: The platform's own identifier for the app: bundle ID on Apple platforms,
    #: application ID on Android, app ID on Linux and Windows. One field because
    #: all five render it the same way and no consumer needs to know which
    #: flavour of identifier it is.
    app_id: str
    python_version: str
    lock: LockStatus
    artifacts: tuple[BuildArtifact, ...] = ()
    #: Ordered platform-specific rows, rendered between ``Python:`` and
    #: ``Lock:``. Android uses this for its Kivy generation and ABI list; a
    #: shared field beats either a lowest-common-denominator report or an
    #: Android-shaped one that four platforms leave blank.
    extra: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "app": {"name": self.app_name, "id": self.app_id},
            "python": self.python_version,
            "lock": self.lock.as_dict(),
            "artifacts": [a.as_dict() for a in self.artifacts],
            "extra": dict(self.extra),
        }


def humanize_age(seconds: float) -> str:
    """A coarse relative age: ``just now``, ``3 minutes ago``, ``2 days ago``.

    Coarse on purpose -- the question ``status`` answers is "is this build stale
    enough to distrust", and minutes are plenty for that.
    """
    seconds = int(seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = seconds // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"
