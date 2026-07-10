"""Generate the freedesktop ``.desktop`` entry for the AppDir (linux-spec).

The Linux analog of the macOS ``Info.plist``: kivyforge owns the entry, built
from ``[project]`` + ``[tool.kivy]`` + ``[tool.kivy.linux]``. ``Exec=AppRun %f``
and ``StartupWMClass=<app_id>`` (matched by the ``AppRun`` launcher's SDL
WM_CLASS env) so the running window groups under the app's own icon. The
generated file must pass ``desktop-file-validate`` (also a ``doctor`` check).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from kivyforge.config.model import Config

from . import AppDirError


def render_desktop_entry(config: Config) -> str:
    """The ``.desktop`` file contents for *config* (pure/testable)."""
    linux = config.linux_required
    categories = "".join(f"{c};" for c in linux.desktop.categories)
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={config.display_name}",
    ]
    if config.project.description:
        lines.append(f"Comment={config.project.description}")
    lines += [
        "Exec=AppRun %f",
        f"Icon={linux.app_id}",
        f"Categories={categories}",
        f"StartupWMClass={linux.app_id}",
        "Terminal=false",
    ]
    return "\n".join(lines) + "\n"


def write_desktop_entry(config: Config, dest: Path) -> None:
    """Write ``<app_id>.desktop`` for *config* at *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_desktop_entry(config), encoding="utf-8")


def validate_desktop_file(dest: Path) -> None:
    """Run ``desktop-file-validate`` on *dest*; hard-fail on validation errors.

    The generated ``.desktop`` must pass ``desktop-file-validate`` (linux-spec):
    an invalid entry produces an AppImage that launches but fails desktop
    integration (menu/search/icon association). ``desktop-file-validate`` (from
    ``desktop-file-utils``) is optional on the build host — when it isn't
    installed we can't run it, so we skip (config-time category validation still
    guards the common typo). When it *is* installed, any reported error is a hard
    failure.
    """
    tool = shutil.which("desktop-file-validate")
    if tool is None:
        return
    try:
        proc = subprocess.run([tool, str(dest)], capture_output=True, text=True)
    except (OSError, ValueError):
        return
    if proc.returncode != 0:
        detail = (proc.stdout + proc.stderr).strip() or "validation failed"
        raise AppDirError(
            f"generated {dest.name} failed desktop-file-validate:\n{detail}\n"
            "  Fix [tool.kivy.linux.desktop] / [project] metadata and rebuild."
        )
