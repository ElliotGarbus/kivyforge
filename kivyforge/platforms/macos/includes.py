"""``[[tool.kivy.macos.include_files]]``: user files in the ``.app`` (#170).

``dest`` is relative to ``Contents/`` and starts with ``Resources`` or
``SharedSupport`` (the loader enforces it). The bundle is assembled fresh in a
temporary tree each build, so staging is a copy into it before signing, with
no removal record and no build-phase wiring (include-files-proposal §4.5).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from kivyforge.artifacts import include_files
from kivyforge.artifacts.include_files import IncludeItem
from kivyforge.config.model import Config
from kivyforge.lock.model import LockedIncludeFile
from kivyforge.report.failures import reclassify

from . import AppBundleError

NATIVE_KEY = "[tool.kivy.macos.native.binaries]"


def reserved_check(exe: str) -> Callable[[IncludeItem], str | None]:
    """The message for an include that would land where the bundler writes."""
    owned = {
        "Resources/app": "where the bundler puts app_dir",
        "Resources/lib": "where the bundler installs the locked packages",
        "Resources/python": "where the bundler puts the Python runtime",
        f"Resources/{exe}.icns": ("the app icon; set it with [tool.kivy.macos.icons]"),
    }
    folded = {path.casefold(): (path, why) for path, why in owned.items()}

    def check(item: IncludeItem) -> str | None:
        head = "/".join(item.path.split("/")[:2]).casefold()
        hit = folded.get(head)
        if hit is None:
            return None
        path, why = hit
        return (
            f"include_files: {item.source} would land at Contents/{item.path}, "
            f"and Contents/{path} is {why}."
        )

    return check


def check_includes(
    config: Config,
    project_root: Path,
    pins: tuple[LockedIncludeFile, ...] | None,
) -> list[IncludeItem]:
    """Refuse a misplaced include, then any drift from *pins* (``None``: skip).

    Runs before assembly, so a bad include costs no runtime or wheel staging.
    """
    entries = config.macos_required.include_files
    if not entries:
        return []
    try:
        items = include_files.expand(entries, project_root)
        include_files.refuse_reserved(items, reserved_check(config.app_slug))
        include_files.refuse_unprocessed(items, native_key=NATIVE_KEY)
        if pins is not None:
            include_files.verify_pins(items, pins, platform="macos")
    except include_files.IncludeFilesError as exc:
        raise AppBundleError(str(exc), **reclassify(exc)) from exc
    return items


def stage_includes(items: list[IncludeItem], contents: Path) -> list[str]:
    """Copy *items* under ``Contents/``, dropping ``com.apple.quarantine``."""
    return include_files.copy_items(items, contents, copy=include_files.copy_fresh)


def verify_bundle(
    config: Config, project_root: Path, bundle: Path, *, artifact: str
) -> None:
    """Refuse a bundle that lacks an include or holds a different copy (exit 5).

    *bundle* is the ``.app`` on disk, which may still be the temporary
    assembly tree; *artifact* is the name the user knows it by.
    """
    entries = config.macos_required.include_files
    if not entries:
        return
    try:
        expected = include_files.expected_contents(
            include_files.expand(entries, project_root)
        )
        include_files.raise_for_mismatches(
            include_files.tree_mismatches(expected, bundle / "Contents"),
            artifact=artifact,
        )
    except include_files.IncludeFilesError as exc:
        raise AppBundleError(str(exc), **reclassify(exc)) from exc
