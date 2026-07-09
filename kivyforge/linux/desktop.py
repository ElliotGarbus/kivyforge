"""Generate the freedesktop ``.desktop`` entry for the AppDir (linux-spec).

The Linux analog of the macOS ``Info.plist``: kivyforge owns the entry, built
from ``[project]`` + ``[tool.kivy]`` + ``[tool.kivy.linux]``. ``Exec=AppRun %f``
and ``StartupWMClass=<app_id>`` (matched by the ``AppRun`` launcher's SDL
WM_CLASS env) so the running window groups under the app's own icon. The
generated file must pass ``desktop-file-validate`` (also a ``doctor`` check).
"""

from __future__ import annotations

from pathlib import Path

from ..config.model import Config


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
