"""Invoke the generated project's Gradle wrapper (android/06)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from kivyforge.build_outcome import BuildEvents
from kivyforge.cli._common import PROGRESS_ONLY_EVENTS, ToolchainError
from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.failures import spawn_failure
from kivyforge.report.streams import stderr_for_child


class GradleError(Exception):
    """Gradle could not do the job. ``returncode`` is set only if Gradle ran."""

    def __init__(self, message: str, *, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


def _install_missing_sdk_packages(events: BuildEvents) -> None:
    """Install a missing pinned NDK/CMake visibly, before AGP does it silently."""
    from .doctor import RealAndroidProbe
    from .sdk_packages import ensure_sdk_packages

    ensure_sdk_packages(
        RealAndroidProbe().sdk_root(),
        on_progress=events.on_progress,
        on_transfer=events.on_transfer,
    )


def run_gradle(
    project_dir: Path,
    tasks: list[str],
    *,
    env_overrides: dict[str, str] | None = None,
    events: BuildEvents | None = None,
) -> None:
    script = project_dir / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not script.is_file():
        raise GradleError(
            f"no Gradle wrapper at {script}; run `kivyforge build` to "
            "(re)generate the project."
        )
    _require_jdk()
    _install_missing_sdk_packages(events or PROGRESS_ONLY_EVENTS)
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    cmd = [str(script), "--console=plain", *tasks]
    # Gradle's transcript is progress: it goes to our stderr, so stdout stays
    # the command's product (and a --json document stays parseable).
    try:
        with stderr_for_child() as err:
            proc = subprocess.run(
                cmd,
                cwd=project_dir,
                env=env,
                stdout=err,
                stderr=err,
                stdin=subprocess.DEVNULL,
            )
    except OSError as exc:
        # The wrapper exists (checked above) but could not be started: no exec
        # bit, a noexec mount, no shell. Otherwise a traceback with no envelope.
        raise ToolchainError(
            f"could not run the Gradle wrapper {script.name}: {exc}.\n"
            "  Fix: make it executable, or re-run `kivyforge build -p android` "
            "to regenerate it.",
            **spawn_failure(script.name, exc),
        ) from exc
    if proc.returncode != 0:
        raise GradleError(
            f"Gradle failed (exit {proc.returncode}) running: {' '.join(tasks)}\n"
            f"  See the Gradle output above; `kivyforge doctor -p android` "
            f"checks the JDK/SDK/NDK prerequisites.",
            returncode=proc.returncode,
        )


def _require_jdk() -> None:
    """Refuse to start Gradle without a ``java``, or on a JRE.

    Checked before Gradle rather than left to it: a daemon started on a JRE
    outlives the failed build and remembers that the Java at that path cannot
    compile, so once a JDK is installed at the same path (as Debian's
    ``-jdk-headless`` package does) the next build still fails until the daemon
    is stopped.
    """
    from .doctor import RealAndroidProbe, missing_jdk_tool

    missing = missing_jdk_tool(RealAndroidProbe())
    if missing is None:
        return
    tool, result = missing
    raise ToolchainError(
        f"{result.detail}.\n  Fix: {result.hint}",
        code=diagnostics.TOOLCHAIN_MISSING,
        exit_code=exit_codes.ENVIRONMENT_ERROR,
        context={"tool": tool},
    )


def stop_gradle_daemon(project_dir: Path) -> bool:
    """Best-effort ``gradlew --stop``; returns whether the wrapper ran.

    `clean` needs this before removing ``<app>-android/``: a live daemon keeps
    file handles open under ``app/build``, which makes the removal fail outright
    on Windows. Every failure mode here is benign — no wrapper, no JDK, no
    daemon — so this reports rather than raises.
    """
    script = project_dir / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not script.is_file():
        return False
    try:
        subprocess.run(
            [str(script), "--console=plain", "--stop"],
            cwd=project_dir,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True
