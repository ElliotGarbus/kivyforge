"""Platform-neutral doctor checks shared by every backend (spec 05).

These checks are pure functions over an injectable :class:`Probe` and make no
assumptions about the target platform, so iOS, macOS, and Linux all reuse them.
Platform-specific checks live in ``platforms/<os>/doctor.py``.
"""

from __future__ import annotations

from pathlib import Path

from ..config.model import Config
from ..lock.resolver import MIN_PIP_VERSION, version_str
from .probe import Probe
from .result import CheckResult, Status

SKIP_NOTE = "no pyproject.toml found in current directory"


def lock_parse_fail(platform: str, exc: Exception) -> CheckResult:
    """A FAIL result for an unreadable ``pylock.<platform>.toml``."""
    return CheckResult(
        f"pylock.{platform}.toml",
        Status.FAIL,
        f"failed to parse: {exc}",
        hint=f"Regenerate it with `kivyforge lock -p {platform}`.",
    )


def _ver_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_pip_version(probe: Probe) -> CheckResult:
    """pip >= 24.3 is required to match PEP 730 iOS platform tags at lock time."""
    minimum = version_str(MIN_PIP_VERSION)
    version = probe.pip_version()
    if version is None:
        return CheckResult(
            "pip version",
            Status.WARN,
            "could not determine pip version",
            hint="ensure pip is available: `python -m ensurepip --upgrade`.",
        )
    if _ver_tuple(version) < MIN_PIP_VERSION:
        return CheckResult(
            "pip version",
            Status.FAIL,
            f"{version} (need >= {minimum})",
            hint=(
                "pip < 24.3 cannot match iOS platform tags (PEP 730); "
                "upgrade with `python -m pip install -U pip`."
            ),
        )
    return CheckResult("pip version", Status.PASS, version)


def check_kivyforge_version(
    probe: Probe, current: str, *, offline: bool
) -> CheckResult:
    if offline:
        return CheckResult("kivyforge version", Status.PASS, f"{current} (offline)")
    latest = probe.latest_kivyforge_version()
    if latest and _ver_tuple(latest) > _ver_tuple(current):
        return CheckResult(
            "kivyforge version",
            Status.WARN,
            f"{current} (latest {latest})",
            hint="upgrade with `pip install -U kivyforge`.",
        )
    return CheckResult("kivyforge version", Status.PASS, current)


def check_app_dir(config: Config, project_root: Path) -> CheckResult:
    """``app_dir`` must resolve to an existing directory — it carries the app's
    Python source into the bundle. Config validation only checks the *string*
    (relative, non-empty, etc.), not that it exists on disk; a missing one would
    otherwise build an app with no code (caught at build time, but reported here
    first).
    """
    app_dir = config.kivy.app_dir
    path = project_root / app_dir
    if not path.is_dir():
        return CheckResult(
            "App source directory",
            Status.FAIL,
            f"app_dir {app_dir!r} not found",
            hint="create the directory or fix [tool.kivy].app_dir; it must "
            "point at your app's Python source.",
        )
    return CheckResult("App source directory", Status.PASS, app_dir)
