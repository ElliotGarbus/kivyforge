"""``kivyforge clean`` — remove generated artifacts (spec 05).

``--json`` reports what was actually removed rather than what was asked for:
the target list is fixed, but which of those trees existed is the answer, and a
consumer deciding whether a rebuild is needed cannot derive it from the flags.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import click

from ..artifacts.cache import ArtifactCache
from ..config import ConfigError, load_config
from ..report import Report
from ._common import PYPROJECT_NAME, ToolchainError
from ._output import output_options, reporting


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
@output_options
def clean(
    flush_cache: bool,
    flush_cache_all: bool,
    project_only: bool,
    json_out: bool,
    no_color: bool,
) -> None:
    """Remove generated artifacts in the project folder."""
    with reporting("clean", json_out=json_out, no_color=no_color) as report:
        cwd = Path.cwd()
        pyproject = cwd / PYPROJECT_NAME
        if flush_cache_all and project_only:
            raise ToolchainError(
                "--project-only and --cache-all contradict each other; pass one."
            )
        flush_cache = flush_cache or flush_cache_all
        # Recorded before anything is deleted, so a removal that fails half way
        # still reports the trees it had already removed.
        removed: list[str] = []
        report.record(removed=removed, cache_flushed=False, gradle_caches=[])

        if pyproject.is_file():
            try:
                # A desktop-only project has no [tool.kivy.ios] overlay; clean
                # must work for any target, so it requires no platform overlay.
                config = load_config(pyproject, require_ios=False)
            except ConfigError as exc:
                raise ToolchainError(exc.format()) from exc
            android_project = cwd / f"{config.app_slug}-android"
            # Always before the removal below: a live Gradle daemon holds handles
            # under app/build, which makes rmtree fail outright on Windows.
            _stop_gradle_daemon(report, android_project)
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
            for target in targets:
                if _remove(target):
                    removed.append(target.relative_to(cwd).as_posix())
                    report.record(removed=removed)
            # Drop build/ and dist/ if emptied so no stray husks are left behind.
            for parent in (cwd / "build", cwd / "dist"):
                _remove_if_empty(parent)
            if removed:
                for path in removed:
                    report.line(f"Removed {path}/")
            else:
                report.line("Nothing to clean (no generated artifacts found).")
        elif not flush_cache:
            raise ToolchainError(
                f"no {PYPROJECT_NAME} found in the current directory.\n"
                "  Run clean from your project directory, or pass --cache to flush "
                "only the global artifact cache."
            )

        gradle_caches: list[str] = []
        if flush_cache:
            ArtifactCache().clear()
            report.record(cache_flushed=True)
            report.line("Flushed the artifact download cache.")
        if flush_cache_all:
            gradle_caches = _flush_shared_gradle(report, cwd)
            report.record(gradle_caches=gradle_caches)

        report.emit(
            ok=True,
            data={
                "removed": removed,
                "cache_flushed": flush_cache,
                "gradle_caches": gradle_caches,
            },
        )


def _stop_gradle_daemon(report: Report, android_project: Path) -> None:
    if not android_project.is_dir():
        return
    from ..platforms.android.gradlew import stop_gradle_daemon

    if stop_gradle_daemon(android_project):
        # Progress: stopping the daemon is a precondition of the removal, not
        # one of the things `clean` was asked to produce.
        report.progress("Stopped the project's Gradle daemon(s).")


def _flush_shared_gradle(report: Report, cwd: Path) -> list[str]:
    """Clear the shared ``~/.gradle`` caches ``--cache`` deliberately spares.

    Only the cache subtrees, not all of ``~/.gradle``: the wrapper distributions
    and any ``gradle.properties`` there are configuration, and blowing them away
    would cost every project on the machine a re-download for no benefit.
    """
    gradle_home = Path(
        os.environ.get("GRADLE_USER_HOME") or (Path.home() / ".gradle")
    ).expanduser()
    if gradle_home == cwd or not gradle_home.is_dir():
        return []
    removed = [
        sub.name
        for sub in (gradle_home / "caches", gradle_home / "daemon")
        if _remove(sub)
    ]
    if removed:
        report.line(f"Flushed shared Gradle {', '.join(removed)} under {gradle_home}.")
    else:
        report.line(f"No shared Gradle caches to flush under {gradle_home}.")
    return removed


def _remove(path: Path) -> bool:
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def _remove_if_empty(path: Path) -> None:
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()
