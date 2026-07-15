"""Windows-safe artifact naming (windows-spec).

The launcher ``<name>.exe`` and the packaged ``dist/windows`` folder name are
derived from ``[tool.kivy].display_name`` through :func:`windows_safe_name`,
which strips/replaces characters illegal in Windows filenames, avoids the
reserved DOS device names, and drops trailing dots/spaces (which Windows
silently removes). It is a pure helper so it is trivially unit-testable.
"""

from __future__ import annotations

import re

# Characters that are illegal in a Windows filename component, plus control
# characters (0x00–0x1F). Backslash and forward slash are path separators.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Reserved DOS device names (case-insensitive). A component whose stem (the part
# before the first dot) is one of these is illegal even with an extension
# (``NUL.txt`` is still reserved).
_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def windows_safe_name(display_name: str, *, fallback: str = "App") -> str:
    """Return a Windows-filesystem-safe base name derived from ``display_name``.

    Illegal characters become spaces (so ``"My|App"`` reads as ``"My App"``),
    runs of whitespace collapse to a single space, and leading/trailing spaces
    and trailing dots are removed. If the stem collides with a reserved device
    name it is suffixed with ``_``. Returns ``fallback`` when nothing usable
    remains (e.g. a name made entirely of illegal characters).
    """
    cleaned = _ILLEGAL.sub(" ", display_name)
    # Collapse internal whitespace runs and strip the ends.
    cleaned = " ".join(cleaned.split())
    # Windows silently drops trailing dots and spaces from names.
    cleaned = cleaned.rstrip(" .")
    if not cleaned:
        return fallback
    stem = cleaned.split(".", 1)[0]
    if stem.upper() in _RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned
