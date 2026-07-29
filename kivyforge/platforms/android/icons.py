"""Generate the launcher-icon resources (android/01 §icons, android/04).

The generated manifest always names ``@mipmap/ic_launcher``, so *something* must
exist at that resource name in every build or AAPT fails the whole project. Two
paths lead there:

- **No configured source** — a plain generated default icon (standard library
  only, no Pillow), so a freshly-``init``-ed project builds out of the box.
- **A configured 1024x1024 source** — the full **adaptive icon** set, resized
  with [Pillow](https://python-pillow.org/) (the optional ``kivyforge[android]``
  extra): a per-density legacy ``ic_launcher`` for API 24/25 launchers, the
  ``mipmap-anydpi-v26`` adaptive-icon pair for API 26+, and the round variants.

**Safe zone.** An adaptive icon's outer ring is cropped by whatever mask the
launcher applies: only the central 66 of 108 dp is guaranteed visible. The
source artwork is therefore scaled *into* that safe zone on a transparent
canvas rather than filling the layer edge to edge, which is what keeps a
1024x1024 source — the one thing the docs ask for — from being cropped.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from kivyforge.config.icons import IconSourceError, validate_icon_source
from kivyforge.config.model import AndroidConfig, Config

# Launcher-icon densities: dpi bucket -> px for a 48dp legacy icon.
LEGACY_SIZES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}
# The same buckets for a 108dp adaptive-icon layer.
ADAPTIVE_SIZES = {
    "mdpi": 108,
    "hdpi": 162,
    "xhdpi": 216,
    "xxhdpi": 324,
    "xxxhdpi": 432,
}
# Of the 108dp layer, the central 66dp is the guaranteed-visible safe zone.
SAFE_ZONE_RATIO = 66 / 108
# <monochrome> in an adaptive icon is an API 33 attribute; AAPT rejects it when
# compiling against anything older.
MONOCHROME_MIN_COMPILE_SDK = 33

DEFAULT_BACKGROUND = "#ffffff"
# The generated default icon's fill (a Kivy-ish blue-grey).
_DEFAULT_RGBA = (52, 73, 94, 255)


class IconError(Exception):
    """The configured icon set could not be generated."""


def write_icons(
    res: Path, config: Config, android: AndroidConfig, project_root: Path
) -> bool:
    """Write the icon resources under *res*; return ``True`` if a source was used."""
    icons = android.icons
    if not icons.source:
        _write_default(res)
        return False

    source = _open(project_root / icons.source)
    background = icons.background or DEFAULT_BACKGROUND
    if not background.startswith("#"):
        background_image = _open(project_root / background)
    else:
        background_image = None
        _write_background_color(res, background)
    monochrome = _open(project_root / icons.monochrome) if icons.monochrome else None
    if monochrome is not None and android.compile_sdk < MONOCHROME_MIN_COMPILE_SDK:
        raise IconError(
            "[tool.kivy.android.icons].monochrome needs compile_sdk >= "
            f"{MONOCHROME_MIN_COMPILE_SDK} (the themed-icon <monochrome> layer "
            f"is an API {MONOCHROME_MIN_COMPILE_SDK} attribute); this project "
            f"compiles against android-{android.compile_sdk}.\n"
            "  Raise [tool.kivy.android].compile_sdk, or drop the monochrome "
            "layer."
        )

    for bucket, size in LEGACY_SIZES.items():
        mipmap = res / f"mipmap-{bucket}"
        mipmap.mkdir(parents=True, exist_ok=True)
        legacy = _fit(source, size)
        _save(legacy, mipmap / "ic_launcher.png")
        _save(_circular(legacy), mipmap / "ic_launcher_round.png")

    for bucket, size in ADAPTIVE_SIZES.items():
        mipmap = res / f"mipmap-{bucket}"
        mipmap.mkdir(parents=True, exist_ok=True)
        _save(_safe_zone_layer(source, size), mipmap / "ic_launcher_foreground.png")
        if background_image is not None:
            _save(_fit(background_image, size), mipmap / "ic_launcher_background.png")
        if monochrome is not None:
            _save(
                _safe_zone_layer(monochrome, size),
                mipmap / "ic_launcher_monochrome.png",
            )

    anydpi = res / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    xml = adaptive_icon_xml(
        background_is_color=background_image is None,
        monochrome=monochrome is not None,
    )
    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        (anydpi / name).write_text(xml, encoding="utf-8", newline="\n")
    return True


def adaptive_icon_xml(*, background_is_color: bool, monochrome: bool) -> str:
    """The ``mipmap-anydpi-v26`` adaptive-icon drawable (pure/testable)."""
    background = (
        "@color/ic_launcher_background"
        if background_is_color
        else "@mipmap/ic_launcher_background"
    )
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">',
        f'    <background android:drawable="{background}" />',
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />',
    ]
    if monochrome:
        lines.append(
            '    <monochrome android:drawable="@mipmap/ic_launcher_monochrome" />'
        )
    lines.append("</adaptive-icon>")
    return "\n".join(lines) + "\n"


def _write_background_color(res: Path, color: str) -> None:
    values = res / "values"
    values.mkdir(parents=True, exist_ok=True)
    (values / "ic_launcher_background.xml").write_text(
        "<resources>\n"
        f'    <color name="ic_launcher_background">{color}</color>\n'
        "</resources>\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_default(res: Path) -> None:
    """Emit the one density AAPT needs for @mipmap/ic_launcher to resolve."""
    mipmap = res / "mipmap-mdpi"
    mipmap.mkdir(parents=True, exist_ok=True)
    (mipmap / "ic_launcher.png").write_bytes(
        default_icon_png(LEGACY_SIZES["mdpi"], _DEFAULT_RGBA)
    )


def default_icon_png(size: int, rgba: tuple[int, int, int, int]) -> bytes:
    """A valid solid-colour 8-bit RGBA PNG, built without any imaging library."""
    row = b"\x00" + bytes(rgba) * size  # per-scanline filter byte (0) + pixels

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * size, 9))
        + chunk(b"IEND", b"")
    )


def _open(path: Path):
    try:
        validate_icon_source(path)
    except IconSourceError as exc:
        raise IconError(str(exc)) from exc
    image_module = _pillow()
    try:
        return image_module.open(path).convert("RGBA")
    except OSError as exc:
        raise IconError(f"cannot read icon layer {path}: {exc}") from exc


def _fit(image, size: int):
    from PIL import Image

    return image.resize((size, size), Image.LANCZOS)


def _safe_zone_layer(image, size: int):
    """*image* scaled into the adaptive safe zone, centered on transparency."""
    from PIL import Image

    inner = max(1, round(size * SAFE_ZONE_RATIO))
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = (size - inner) // 2
    layer.paste(_fit(image, inner), (offset, offset))
    return layer


def _circular(image):
    """The legacy round-icon variant: *image* masked to a centered circle."""
    from PIL import Image, ImageDraw

    size = image.size[0]
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return out


def _save(image, dest: Path) -> None:
    image.save(dest, format="PNG")


def _pillow():
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise IconError(
            "generating the Android adaptive icon needs Pillow, which is not "
            "installed.\n"
            "  Install the Android extra: pip install 'kivyforge[android]'\n"
            "  (or unset [tool.kivy.android.icons].source to build with the "
            "default launcher icon)."
        ) from exc
    return Image
