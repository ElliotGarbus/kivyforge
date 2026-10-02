"""The published Android toolchain table says what toolchain.py pins.

The page is hand-written and the pins move with releases; the JDK row said
"17 or later" while the pinned Gradle could not run on anything past 23, which
is how a Mac with Android Studio's bundled JDK 25 got a green doctor and a
failed build.
"""

from __future__ import annotations

import pathlib

import pytest

from kivyforge.platforms.android import toolchain

PAGE = (
    pathlib.Path(__file__).parents[3]
    / "docs"
    / "guides"
    / "guides"
    / "android"
    / "supported-versions.md"
)


def _row(tool: str) -> str:
    rows = [
        line
        for line in PAGE.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| {tool} |")
    ]
    assert len(rows) == 1, f"expected one '{tool}' row in {PAGE.name}"
    return rows[0]


@pytest.mark.parametrize(
    ("tool", "pinned"),
    [
        ("JDK", f"{toolchain.MIN_JDK} to {toolchain.MAX_JDK}"),
        ("Android NDK", toolchain.NDK_VERSION),
        ("CMake", toolchain.CMAKE_VERSION),
        ("Android Gradle Plugin", toolchain.AGP_VERSION),
        ("Gradle", toolchain.GRADLE_VERSION),
    ],
)
def test_the_table_states_the_pinned_version(tool, pinned):
    assert pinned in _row(tool)


def test_the_jdk_ceiling_was_checked_for_this_gradle():
    """Bumping Gradle moves the newest JDK it runs on; this fails until someone
    reads Gradle's compatibility matrix and updates MAX_JDK to match."""
    assert (toolchain.GRADLE_VERSION, toolchain.MAX_JDK) == ("8.11.1", 23)


def test_no_other_guide_restates_the_jdk_range():
    """The range lives in the supported-versions table; other pages link to it,
    so a Gradle bump has one page to edit, and that page is tested above."""
    jdk_range = f"{toolchain.MIN_JDK} to {toolchain.MAX_JDK}"
    guides = PAGE.parents[2]
    restated = [
        str(page.relative_to(guides))
        for page in guides.rglob("*.md")
        if page != PAGE and jdk_range in page.read_text(encoding="utf-8")
    ]
    assert restated == []
