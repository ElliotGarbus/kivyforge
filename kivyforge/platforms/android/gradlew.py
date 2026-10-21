"""Invoke the generated project's Gradle wrapper (android/06)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from kivyforge.build_outcome import BuildEvents
from kivyforge.cli._common import PROGRESS_ONLY_EVENTS, ToolchainError
from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.failures import spawn_failure
from kivyforge.report.streams import stderr_for_child
from kivyforge.report.verbosity import command_line, current_verbosity

#: What ``-v`` adds to every Gradle run, then ``-vv`` (verbose-output-proposal
#: §3.2). Both only add output, so they are safe on every task, release included.
_VERBOSE_FLAGS = ("--stacktrace", "--info")

#: How the generated signing block reads its passwords at Gradle time
#: (``signing.signing_config_gradle``).
_GETENV = re.compile(r"System\.getenv\('([^']+)'\)")


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


def gradle_flags(verbosity: int) -> list[str]:
    """Gradle's flags for a ``-v`` count: none, ``--stacktrace``, then ``--info``."""
    return list(_VERBOSE_FLAGS[: max(verbosity, 0)])


def _rerun_lines(project_dir: Path, cmd: list[str], tasks: list[str]) -> list[str]:
    """Where Gradle runs and the exact command, for a user to rerun it by hand.

    The wrapper is shown relative to that folder, the way it is typed there.
    """
    wrapper = (".\\" if os.name == "nt" else "./") + Path(cmd[0]).name
    lines = [
        f"[gradle] in {project_dir}",
        f"[gradle] {command_line([wrapper, *cmd[1:]])}",
    ]
    names = _signing_env_vars(project_dir) if _is_release(tasks) else []
    if names:
        lines.append(
            f"[gradle] release signing reads {', '.join(names)} from the "
            "environment; set them before rerunning this by hand."
        )
    return lines


def _is_release(tasks: list[str]) -> bool:
    return any("Release" in task for task in tasks)


def _signing_env_vars(project_dir: Path) -> list[str]:
    """The variables the generated signing block reads -- names, never values."""
    try:
        text = (project_dir / "app" / "build.gradle").read_text(encoding="utf-8")
    except OSError:
        return []
    return list(dict.fromkeys(_GETENV.findall(text)))


def run_gradle(
    project_dir: Path,
    tasks: list[str],
    *,
    env_overrides: dict[str, str] | None = None,
    events: BuildEvents | None = None,
) -> None:
    """Run *tasks* with the generated project's wrapper; raise ``GradleError``.

    The running verb's ``-v`` level (:func:`current_verbosity`) adds Gradle's
    own detail flags, and from level 1 the command is printed before it runs.
    """
    script = project_dir / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not script.is_file():
        raise GradleError(
            f"no Gradle wrapper at {script}; run `kivyforge build` to "
            "(re)generate the project."
        )
    _require_jdk()
    events = events or PROGRESS_ONLY_EVENTS
    _install_missing_sdk_packages(events)
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    verbosity = current_verbosity()
    cmd = [str(script), "--console=plain", *gradle_flags(verbosity), *tasks]
    rerun = _rerun_lines(project_dir, cmd, tasks) if verbosity else []
    for line in rerun:
        events.on_progress(line)
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
        # Gradle's own advice, "Run with --stacktrace", is one a kivyforge user
        # cannot follow; this says what they can do instead. At -v the command
        # is repeated, since by now it has scrolled far off the screen.
        if rerun:
            steps = "\n".join(f"    {line.removeprefix('[gradle] ')}" for line in rerun)
            hint = f"  To rerun it by hand:\n{steps}"
        else:
            hint = "  For a stack trace, rerun with -v (or set KIVYFORGE_VERBOSE=1)."
        raise GradleError(
            f"Gradle failed (exit {proc.returncode}) running: {' '.join(tasks)}\n"
            f"  See the Gradle output above; `kivyforge doctor -p android` "
            f"checks the JDK/SDK/NDK prerequisites.\n{hint}",
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
