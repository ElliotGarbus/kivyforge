"""Find imports of the kivy-ios ``ios`` module (``KF-IOS-LEGACY-IOS-MODULE``).

kivy-ios apps ``import ios``; kivyforge does not provide that module, because
Kivy 3 and the standard library already carry every replacement
(``docs/design/dev/ios-module-proposal.md``). An app that still imports it
fails on the device with a bare ``ModuleNotFoundError``, after a build that
could have said why. This is the static scan behind the warning that
``kivyforge build -p ios`` and ``kivyforge doctor -p ios`` give instead.

A warning, not an error: the import may be guarded and the app run fine.
Dependencies are not scanned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Where the migration guide lives in the repository. A path rather than a URL
#: because the site origin is deliberately not recorded in the source.
GUIDE = "docs/guides/guides/ios/ios-module.md"

#: ``import ios``, ``from ios import ...``, ``from ios.x import ...``, and the
#: same indented, which is how the usual ``if platform == "ios":`` guard looks.
#: A comma also ends the name, so ``import ios, sys`` is found; a match inside a
#: string or a comment is a false positive the warning tolerates.
_IMPORT = re.compile(r"^\s*(import|from)\s+ios([\s.,]|$)")

#: Locations named in a message before it says "and N more".
_SHOWN = 3


@dataclass(frozen=True)
class LegacyIosImports:
    """The files under ``app_dir`` that import the module, first line of each."""

    #: ``(posix path relative to the project root, line number)``, sorted.
    hits: tuple[tuple[str, int], ...]

    @property
    def message(self) -> str:
        """What the build warning and the doctor detail say."""
        shown = ", ".join(f"{path}:{line}" for path, line in self.hits[:_SHOWN])
        more = len(self.hits) - _SHOWN
        if more > 0:
            shown += f" and {more} more"
        verb = "imports" if len(self.hits) == 1 else "import"
        return (
            f"{shown} {verb} the kivy-ios `ios` module, which kivyforge does not "
            "provide"
        )

    @property
    def hint(self) -> str:
        return (
            f"Kivy 3 and the standard library replace it; see {GUIDE} for the "
            "mapping and a web view recipe."
        )

    @property
    def context(self) -> dict[str, str]:
        path, line = self.hits[0]
        return {"file": path, "line": str(line), "files": str(len(self.hits))}


def find_legacy_ios_imports(
    app_dir: Path, project_root: Path
) -> LegacyIosImports | None:
    """Scan every ``.py`` under *app_dir*; ``None`` when there is nothing to say.

    Quiet when *app_dir* has its own ``ios.py`` or ``ios/``: the import is then
    the app's module, not kivy-ios's.
    """
    if not app_dir.is_dir():
        return None
    if (app_dir / "ios.py").is_file() or (app_dir / "ios").is_dir():
        return None
    root = project_root.resolve()
    hits: list[tuple[str, int]] = []
    for source in sorted(app_dir.rglob("*.py")):
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # unreadable is not evidence of an import
        for number, line in enumerate(text.splitlines(), start=1):
            if _IMPORT.match(line):
                try:
                    shown = source.resolve().relative_to(root).as_posix()
                except ValueError:
                    shown = source.as_posix()
                hits.append((shown, number))
                break
    return LegacyIosImports(tuple(hits)) if hits else None
