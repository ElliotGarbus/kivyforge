"""Invoke the generated project's Gradle wrapper (android/06)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GradleError(Exception):
    pass


def run_gradle(
    project_dir: Path,
    tasks: list[str],
    *,
    env_overrides: dict[str, str] | None = None,
) -> None:
    script = project_dir / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not script.is_file():
        raise GradleError(
            f"no Gradle wrapper at {script}; run `kivyforge build` to "
            "(re)generate the project."
        )
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    cmd = [str(script), "--console=plain", *tasks]
    proc = subprocess.run(cmd, cwd=project_dir, env=env, text=True)
    if proc.returncode != 0:
        raise GradleError(
            f"Gradle failed (exit {proc.returncode}) running: {' '.join(tasks)}\n"
            f"  See the Gradle output above; `kivyforge doctor -p android` "
            f"checks the JDK/SDK/NDK prerequisites."
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
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True
