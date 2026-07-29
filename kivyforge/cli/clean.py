"""``kivyforge clean`` — remove generated artifacts (spec 05)."""

from __future__ import annotations

import os
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
    help="Also flush the artifact download cache and the generated Android "
    "project's own Gradle cache.",
)
@click.option(
    "--cache-all",
    "flush_cache_all",
    is_flag=True,
    help="--cache, plus the shared ~/.gradle caches (affects every project on "
    "this machine; the next build re-downloads Gradle's dependencies).",
)
@click.option(
    "--project-only",
    is_flag=True,
    default=False,
    help="Only the generated project artifacts, not the artifact cache (default).",
)
def clean(flush_cache: bool, flush_cache_all: bool, project_only: bool) -> None:
    """Remove generated artifacts in the project folder."""
    cwd = Path.cwd()
    pyproject = cwd / PYPROJECT_NAME
    if flush_cache_all and project_only:
        raise ToolchainError(
            "--project-only and --cache-all contradict each other; pass one."
        )
    flush_cache = flush_cache or flush_cache_all

    if pyproject.is_file():
        try:
            # A desktop-only project has no [tool.kivy.ios] overlay; clean must
            # work for any target, so it requires no platform overlay at all.
            config = load_config(pyproject, require_ios=False)
        except ConfigError as exc:
            raise ToolchainError(exc.format()) from exc
        android_project = cwd / f"{config.app_slug}-android"
        # Always before the removal below: a live Gradle daemon holds handles
        # under app/build, which makes rmtree fail outright on Windows.
        _stop_gradle_daemon(android_project)
        # Every platform's generated staging/output trees: iOS <app>-ios/,
        # macOS build/macos/, Linux build/linux/ + dist/linux/, and Windows
        # build/windows/ + dist/windows/.
        targets = [
            cwd / f"{config.app_slug}-ios",
            android_project,
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
    if flush_cache_all:
        _flush_shared_gradle(cwd)


def _stop_gradle_daemon(android_project: Path) -> None:
    if not android_project.is_dir():
        return
    from ..platforms.android.gradlew import stop_gradle_daemon

    if stop_gradle_daemon(android_project):
        click.echo("Stopped the project's Gradle daemon(s).")


def _flush_shared_gradle(cwd: Path) -> None:
    """Clear the shared ``~/.gradle`` caches ``--cache`` deliberately spares.

    Only the cache subtrees, not all of ``~/.gradle``: the wrapper distributions
    and any ``gradle.properties`` there are configuration, and blowing them away
    would cost every project on the machine a re-download for no benefit.
    """
    gradle_home = Path(
        os.environ.get("GRADLE_USER_HOME") or (Path.home() / ".gradle")
    ).expanduser()
    if gradle_home == cwd or not gradle_home.is_dir():
        return
    removed = [
        sub.name
        for sub in (gradle_home / "caches", gradle_home / "daemon")
        if _remove(sub)
    ]
    if removed:
        click.echo(f"Flushed shared Gradle {', '.join(removed)} under {gradle_home}.")
    else:
        click.echo(f"No shared Gradle caches to flush under {gradle_home}.")


def _remove(path: Path) -> bool:
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def _remove_if_empty(path: Path) -> None:
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()
