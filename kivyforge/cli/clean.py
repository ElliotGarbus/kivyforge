"""``kivyforge clean`` — remove generated artifacts (spec 05)."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from ..artifacts.cache import ArtifactCache
from ..config import ConfigError, load_config
from ._common import PYPROJECT_NAME, ToolchainError


@click.command()
@click.option(
    "--cache",
    "flush_cache",
    is_flag=True,
    help="Also flush the artifact download cache.",
)
@click.option(
    "--project-only",
    is_flag=True,
    default=False,
    help="Only the generated project artifacts, not the artifact cache (default).",
)
def clean(flush_cache: bool, project_only: bool) -> None:
    """Remove generated artifacts in the project folder."""
    cwd = Path.cwd()
    pyproject = cwd / PYPROJECT_NAME

    if pyproject.is_file():
        try:
            # A desktop-only project has no [tool.kivy.ios] overlay; clean must
            # work for any target, so it requires no platform overlay at all.
            config = load_config(pyproject, require_ios=False)
        except ConfigError as exc:
            raise ToolchainError(exc.format()) from exc
        # Every platform's generated staging/output trees: iOS <app>-ios/,
        # macOS build/macos/, Linux build/linux/ + dist/linux/, and Windows
        # build/windows/ + dist/windows/.
        targets = [
            cwd / f"{config.app_slug}-ios",
            cwd / f"{config.app_slug}-android",
            cwd / "build" / "macos",
            cwd / "build" / "linux",
            cwd / "dist" / "linux",
            cwd / "build" / "windows",
            cwd / "dist" / "windows",
        ]
        removed = [t for t in targets if _remove(t)]
        # Drop build/ and dist/ if emptied so no stray husks are left behind.
        for parent in (cwd / "build", cwd / "dist"):
            _remove_if_empty(parent)
        if removed:
            for t in removed:
                click.echo(f"Removed {t.relative_to(cwd).as_posix()}/")
        else:
            click.echo("Nothing to clean (no generated artifacts found).")
    elif not flush_cache:
        raise ToolchainError(
            f"no {PYPROJECT_NAME} found in the current directory.\n"
            "  Run clean from your project directory, or pass --cache to flush "
            "only the global artifact cache."
        )

    if flush_cache:
        cache = ArtifactCache()
        cache.clear()
        click.echo("Flushed the artifact download cache.")


def _remove(path: Path) -> bool:
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def _remove_if_empty(path: Path) -> None:
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()
