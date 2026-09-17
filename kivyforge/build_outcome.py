"""What a ``build`` or ``package`` run produced (build-package-output-proposal §4.1).

Every backend already computed the path of the thing it built, and the layers
above threw it away because they returned ``None``. These types carry it out.

Two decisions are easy to undo by accident, so they are stated here:

* **Only what this invocation finalised is recorded.** A backend calls
  :meth:`OutcomeBuilder.add` at the moment a product exists and has been checked,
  never for a path that merely happens to be on disk -- a previous run's APK, or
  the artifact a rollback restored, is indistinguishable from a fresh one.
* **Printing a product line and recording an artifact are separate.** Nested
  flows print their intermediate products (``Built <app>`` inside ``package``)
  without recording them, by handing the inner call
  :meth:`BuildEvents.without_artifacts`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path


class ArtifactKind(Enum):
    """What shape a produced path is. Closed, for the reason ``LockState`` is."""

    APPIMAGE = "appimage"
    APK = "apk"
    AAB = "aab"
    APP = "app"  # .app bundle: macOS, and iOS simulator/device builds
    IPA = "ipa"
    FOLDER = "folder"  # Windows onedir, Linux AppDir
    PROJECT = "project"  # generated Xcode/Gradle project, not runnable


@dataclass(frozen=True)
class Artifact:
    #: Relative to the project root; rendered posix-style in ``as_dict``.
    path: Path
    kind: ArtifactKind

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path.as_posix(), "kind": self.kind.value}


@dataclass(frozen=True)
class BuildOutcome:
    artifacts: tuple[Artifact, ...]
    #: Human-only prose (distribution advice), rendered after the run and never
    #: part of the envelope -- excluded by construction rather than by memory.
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {"artifacts": [a.as_dict() for a in self.artifacts]}


@dataclass(frozen=True)
class BuildEvents:
    """The callbacks a backend reports through while it runs.

    ``on_line`` is product prose, ``on_progress`` everything else kivyforge says,
    ``on_artifact`` records without printing, and ``on_note`` attaches a
    success-path diagnostic code to text the backend has *already* printed -- a
    note never prints, so adding one cannot change human output.
    """

    on_line: Callable[[str], None]
    on_progress: Callable[[str], None]
    on_artifact: Callable[[Artifact], None]
    on_note: Callable[[str, str, Mapping[str, str] | None], None]

    def without_artifacts(self) -> BuildEvents:
        """Same output, nothing recorded: for a build nested inside ``package``."""
        return replace(self, on_artifact=discard_artifact)

    def note(
        self, code: str, message: str, context: Mapping[str, str] | None = None
    ) -> None:
        self.on_note(code, message, context)


class OutcomeBuilder:
    """Backend-side: the one place a product is both stored and announced."""

    def __init__(self, on_artifact: Callable[[Artifact], None]) -> None:
        self._on_artifact = on_artifact
        self._artifacts: list[Artifact] = []

    def add(self, path: Path, kind: ArtifactKind) -> Artifact:
        artifact = Artifact(path, kind)
        self._artifacts.append(artifact)
        self._on_artifact(artifact)
        return artifact

    def finish(self, *, notes: tuple[str, ...] = ()) -> BuildOutcome:
        return BuildOutcome(tuple(self._artifacts), notes)


def discard_artifact(artifact: Artifact) -> None:
    return None


def discard_note(
    code: str, message: str, context: Mapping[str, str] | None = None
) -> None:
    return None
