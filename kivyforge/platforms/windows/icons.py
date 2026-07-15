"""Generate the Windows app icon (windows-spec).

When the project supplies ``[tool.kivy.windows.icons].source`` (a 1024×1024 PNG,
validated like the other platforms) kivyforge renders it into a multi-resolution
Windows ``.ico`` (256/48/32/16 px) with [Pillow](https://python-pillow.org/) —
the optional ``kivyforge[windows]`` extra. The ``.ico`` is then patched into the
launcher's resources with ``rcedit`` at assembly time.

Unlike Linux (whose ``appimagetool`` requires an icon and so always gets a
generated default), Windows needs none: an app with no configured icon simply
keeps the executable's default shell icon, and Pillow is only needed when an
icon *is* configured.
"""

from __future__ import annotations

from pathlib import Path

from kivyforge.config.icons import validate_icon_source
from kivyforge.config.model import Config

from . import WindowsBundleError

# Sizes embedded in the .ico, largest first (Windows picks per display context).
ICO_SIZES = (256, 48, 32, 16)


def stage_icon(config: Config, project_root: Path, dest: Path) -> Path | None:
    """Render the app ``.ico`` at *dest*; return it, or ``None`` if unconfigured.

    ``None`` means no ``[tool.kivy.windows.icons].source`` was set, and the
    launcher keeps its default icon (no ``rcedit --set-icon``).
    """
    source = config.windows_required.icons.source
    if not source:
        return None

    src = (project_root / source).resolve()
    validate_icon_source(src)
    image = _open(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Pillow writes every requested size into one .ico from the largest render.
    image.save(dest, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    return dest


def _open(src: Path):
    image_module = _pillow()
    try:
        return image_module.open(src).convert("RGBA")
    except OSError as exc:
        raise WindowsBundleError(f"cannot read app icon {src}: {exc}") from exc


def _pillow():
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise WindowsBundleError(
            "generating the Windows icon needs Pillow, which is not installed.\n"
            "  Install the Windows extra: pip install 'kivyforge[windows]'\n"
            "  (or unset [tool.kivy.windows.icons].source to build without an icon)."
        ) from exc
    return Image
