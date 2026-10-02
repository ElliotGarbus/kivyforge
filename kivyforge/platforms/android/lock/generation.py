"""Which ``kivy_generation`` a resolved Kivy version belongs to.

``kivy_generation`` is declared, not derived: the resolver never sees it, so a
``kivy`` requirement that resolves to the other major leaves the two disagreeing.
``lock`` and ``doctor`` both report that, from this one rule.
"""

from __future__ import annotations

from packaging.version import InvalidVersion, Version


def expected_generation(kivy_version: str) -> int | None:
    """``2`` for Kivy < 3.0 (SDL2), ``3`` for Kivy >= 3.0 (SDL3); ``None`` if unparseable."""
    try:
        # ``.major`` reads only the release segment's leading number, so a
        # pre-release like "3.0.0.dev202606221936" still counts as major 3 --
        # a direct ``Version(...) >= Version("3.0")`` comparison would not:
        # PEP 440 dev-releases sort *before* their final release, so that
        # comparison is False for every Kivy 3.0 dev build.
        return 3 if Version(kivy_version).major >= 3 else 2
    except InvalidVersion:
        return None


def mismatch_hint(declared: int, expected: int) -> str:
    """How to bring ``kivy_generation`` and the ``kivy`` requirement back in line."""
    if expected == 2:
        return (
            f"kivy_generation = {declared} does not choose the Kivy version; "
            "[project].dependencies does. Require Kivy 3.0 there (pip skips "
            'pre-releases, so use e.g. "kivy>=3.0.0.dev0,<4" and an index that '
            "hosts it), or set kivy_generation = 2."
        )
    return (
        f"kivy_generation = {declared} does not choose the Kivy version; "
        "[project].dependencies does. Set kivy_generation = 3 to match, or pin "
        'kivy below 3 (e.g. "kivy<3").'
    )
