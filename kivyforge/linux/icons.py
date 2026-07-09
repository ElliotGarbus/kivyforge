"""Generate the AppDir icon set (linux-spec).

Linux has no guaranteed host icon tool (the macOS ``sips``/``iconutil`` analog),
so when the project supplies ``[tool.kivy.linux.icons].source`` (a 1024×1024
PNG, validated like iOS/macOS) kivyforge resizes it with
[Pillow](https://python-pillow.org/) — the optional ``kivyforge[linux]`` extra —
into the freedesktop **hicolor** size set plus the root ``<app_id>.png``.

When no source is configured, a plain generated default icon is written instead
(using only the standard library) so ``appimagetool`` — which requires the icon
its ``.desktop`` ``Icon=`` key names — always has one to embed.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from ..config.model import Config
from ..project.icon import validate_icon_source
from . import AppDirError

# freedesktop hicolor sizes to emit. The root AppDir icon is the 256px render.
HICOLOR_SIZES = (16, 32, 48, 64, 128, 256, 512)
ROOT_ICON_SIZE = 256

# The default icon's fill (a neutral slate), used when no source is configured.
_DEFAULT_RGBA = (45, 52, 64, 255)


def stage_icons(config: Config, project_root: Path, appdir: Path) -> bool:
    """Write the icon set into *appdir*; return ``True`` if a *user* icon was used.

    With no configured source a generated default icon is written (returns
    ``False``) so the AppDir always carries the root ``<app_id>.png`` that
    ``appimagetool`` requires.
    """
    app_id = config.linux_required.app_id
    source = config.linux_required.icons.source
    if not source:
        _write_default(appdir, app_id)
        return False

    src = (project_root / source).resolve()
    validate_icon_source(src)
    image = _open(src)
    apps_root = appdir / "usr" / "share" / "icons" / "hicolor"
    for size in HICOLOR_SIZES:
        dest = apps_root / f"{size}x{size}" / "apps" / f"{app_id}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        _resize(image, size).save(dest, format="PNG")

    _resize(image, ROOT_ICON_SIZE).save(appdir / f"{app_id}.png", format="PNG")
    return True


def _write_default(appdir: Path, app_id: str) -> None:
    """Emit a plain solid-colour root + 256px hicolor icon (no Pillow needed)."""
    png = _solid_png(ROOT_ICON_SIZE, _DEFAULT_RGBA)
    (appdir / f"{app_id}.png").write_bytes(png)
    hicolor = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    hicolor.mkdir(parents=True, exist_ok=True)
    (hicolor / f"{app_id}.png").write_bytes(png)


def _solid_png(size: int, rgba: tuple[int, int, int, int]) -> bytes:
    """A minimal valid 8-bit RGBA PNG filled with a single colour."""
    pixel = bytes(rgba)
    row = b"\x00" + pixel * size  # per-scanline filter byte (0) + pixels
    idat = zlib.compress(row * size, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def _open(src: Path):
    image_module = _pillow()
    try:
        return image_module.open(src).convert("RGBA")
    except OSError as exc:
        raise AppDirError(f"cannot read app icon {src}: {exc}") from exc


def _resize(image, size: int):
    from PIL import Image

    return image.resize((size, size), Image.LANCZOS)


def _pillow():
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise AppDirError(
            "generating Linux icons needs Pillow, which is not installed.\n"
            "  Install the Linux extra: pip install 'kivyforge[linux]'\n"
            "  (or unset [tool.kivy.linux.icons].source to build without an icon)."
        ) from exc
    return Image
