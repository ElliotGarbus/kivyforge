"""Generate the splash-screen resources (android/01 §splash, android/04).

The splash model is the platform's: *a centered icon on a background*, driven
entirely by ``windowSplashScreen*`` theme attributes with no runtime dependency
and no code in the activity. Two layers of resources come out of one config:

- ``values-v31/`` carries the real attributes. On Android 12+ the OS draws the
  system splash from them, so an ``AnimatedVectorDrawable`` source animates and
  ``animation_duration``/``branding`` mean what they say.
- The base theme's ``android:windowBackground`` gets a generated layer-list of
  the same background + icon. That is what fills the gap below API 31 — where no
  system splash exists at all — and, on every API level, what the window shows
  between the splash handing off and Kivy drawing its first frame. Without it
  that handoff cuts to a blank window, which for a cold start (unpack the bundle,
  boot CPython) is seconds of apparent hang.

**Icon sizing** follows the platform spec: the icon drawable is 288dp with the
inner two thirds guaranteed visible, or 240dp/160dp when ``icon_background``
puts a colored disc behind it. A raster source is scaled into that inner box on
a transparent canvas, so a plain square PNG is not clipped by the circular mask
the system splash applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kivyforge.config.model import AndroidConfig

# The dp buckets a generated raster drawable is emitted for.
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}

# Platform spec: canvas dp -> guaranteed-visible inner dp.
ICON_CANVAS_DP = 288
ICON_INNER_DP = 192
# With a colored disc behind the icon the canvas shrinks.
ICON_CANVAS_WITH_BACKGROUND_DP = 240
ICON_INNER_WITH_BACKGROUND_DP = 160
# The platform's maximum branding-image box.
BRANDING_MAX_DP = (200, 80)

# windowSplashScreen* are API 31 attributes; AAPT resolves attribute names
# against the compile SDK regardless of which values-* folder they sit in.
SPLASH_MIN_COMPILE_SDK = 31

DEFAULT_BACKGROUND = "#ffffff"

ICON_DRAWABLE = "kf_splash_icon"
BRANDING_DRAWABLE = "kf_splash_branding"
WINDOW_DRAWABLE = "kf_splash"
BACKGROUND_COLOR = "kf_splash_background"
ICON_BACKGROUND_COLOR = "kf_splash_icon_background"


class SplashError(Exception):
    """The configured splash resources could not be generated."""


@dataclass(frozen=True)
class SplashTheme:
    """What the generated app theme has to say about the splash.

    Empty when no splash is configured, in which case the theme is emitted
    exactly as it was before splash support existed.
    """

    window_background: str | None = None
    v31_items: tuple[tuple[str, str], ...] = ()

    @property
    def configured(self) -> bool:
        return self.window_background is not None


def write_splash(res: Path, android: AndroidConfig, project_root: Path) -> SplashTheme:
    """Write the splash resources under *res*; return the theme contribution."""
    splash = android.splash
    if not splash.source:
        return SplashTheme()
    if android.compile_sdk < SPLASH_MIN_COMPILE_SDK:
        raise SplashError(
            "[tool.kivy.android.splash] needs compile_sdk >= "
            f"{SPLASH_MIN_COMPILE_SDK} (windowSplashScreen* are API "
            f"{SPLASH_MIN_COMPILE_SDK} attributes); this project compiles "
            f"against android-{android.compile_sdk}.\n"
            "  Raise [tool.kivy.android].compile_sdk, or drop the "
            "[tool.kivy.android.splash] table."
        )

    background = splash.background or DEFAULT_BACKGROUND
    icon_background = splash.icon_background
    canvas_dp, inner_dp = (
        (ICON_CANVAS_WITH_BACKGROUND_DP, ICON_INNER_WITH_BACKGROUND_DP)
        if icon_background
        else (ICON_CANVAS_DP, ICON_INNER_DP)
    )

    _write_colors(res, background=background, icon_background=icon_background)
    animated = _write_icon(
        res,
        project_root / splash.source,
        canvas_dp=canvas_dp,
        inner_dp=inner_dp,
    )
    if splash.branding:
        _write_branding(res, project_root / splash.branding)
    _write_window_drawable(res)

    items = [
        ("android:windowSplashScreenBackground", f"@color/{BACKGROUND_COLOR}"),
        ("android:windowSplashScreenAnimatedIcon", f"@drawable/{ICON_DRAWABLE}"),
    ]
    if icon_background:
        items.append(
            (
                "android:windowSplashScreenIconBackgroundColor",
                f"@color/{ICON_BACKGROUND_COLOR}",
            )
        )
    # Duration only drives an AnimatedVectorDrawable; emitting it for a static
    # PNG would delay every launch for nothing.
    if splash.animation_duration is not None and animated:
        items.append(
            (
                "android:windowSplashScreenAnimationDuration",
                str(splash.animation_duration),
            )
        )
    if splash.branding:
        items.append(
            (
                "android:windowSplashScreenBrandingImage",
                f"@drawable/{BRANDING_DRAWABLE}",
            )
        )
    return SplashTheme(
        window_background=f"@drawable/{WINDOW_DRAWABLE}", v31_items=tuple(items)
    )


def window_drawable_xml() -> str:
    """The ``windowBackground`` layer-list: background color + centered icon."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<layer-list xmlns:android="http://schemas.android.com/apk/res/android">\n'
        f'    <item android:drawable="@color/{BACKGROUND_COLOR}" />\n'
        '    <item android:gravity="center">\n'
        f'        <bitmap android:src="@drawable/{ICON_DRAWABLE}" '
        'android:gravity="center" />\n'
        "    </item>\n"
        "</layer-list>\n"
    )


def vector_window_drawable_xml() -> str:
    """The same layer-list for a vector icon (``<bitmap>`` needs a raster)."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<layer-list xmlns:android="http://schemas.android.com/apk/res/android">\n'
        f'    <item android:drawable="@color/{BACKGROUND_COLOR}" />\n'
        f'    <item android:drawable="@drawable/{ICON_DRAWABLE}" '
        'android:gravity="center" />\n'
        "</layer-list>\n"
    )


def _write_window_drawable(res: Path) -> None:
    drawable = res / "drawable"
    drawable.mkdir(parents=True, exist_ok=True)
    vector = (drawable / f"{ICON_DRAWABLE}.xml").is_file()
    xml = vector_window_drawable_xml() if vector else window_drawable_xml()
    _write(drawable / f"{WINDOW_DRAWABLE}.xml", xml)


def _write_colors(res: Path, *, background: str, icon_background: str | None) -> None:
    lines = [f'    <color name="{BACKGROUND_COLOR}">{background}</color>']
    if icon_background:
        lines.append(
            f'    <color name="{ICON_BACKGROUND_COLOR}">{icon_background}</color>'
        )
    values = res / "values"
    values.mkdir(parents=True, exist_ok=True)
    _write(
        values / "kf_splash.xml",
        "<resources>\n" + "\n".join(lines) + "\n</resources>\n",
    )


def _write_icon(res: Path, source: Path, *, canvas_dp: int, inner_dp: int) -> bool:
    """Emit the splash icon; return True when it is an animatable vector."""
    if not source.is_file():
        raise SplashError(
            f"[tool.kivy.android.splash].source not found: {source}\n"
            "  Expected a PNG, or an AnimatedVectorDrawable XML for an "
            "animated splash."
        )
    if source.suffix.lower() == ".xml":
        # A vector/AnimatedVectorDrawable is density-independent and the
        # platform animates it as-is; passing it through Pillow would destroy
        # exactly the property that makes it worth using.
        drawable = res / "drawable"
        drawable.mkdir(parents=True, exist_ok=True)
        _write(drawable / f"{ICON_DRAWABLE}.xml", _read_vector(source))
        return True

    image = _open(source)
    for bucket, scale in DENSITIES.items():
        target = res / f"drawable-{bucket}"
        target.mkdir(parents=True, exist_ok=True)
        canvas = round(canvas_dp * scale)
        inner = round(inner_dp * scale)
        _centered(image, canvas=canvas, inner=inner).save(
            target / f"{ICON_DRAWABLE}.png", format="PNG"
        )
    return False


def _write_branding(res: Path, source: Path) -> None:
    if not source.is_file():
        raise SplashError(f"[tool.kivy.android.splash].branding not found: {source}")
    image = _open(source)
    max_w, max_h = BRANDING_MAX_DP
    for bucket, scale in DENSITIES.items():
        target = res / f"drawable-{bucket}"
        target.mkdir(parents=True, exist_ok=True)
        _contain(image, round(max_w * scale), round(max_h * scale)).save(
            target / f"{BRANDING_DRAWABLE}.png", format="PNG"
        )


def _read_vector(source: Path) -> str:
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise SplashError(f"cannot read splash source {source}: {exc}") from exc
    if "<animated-vector" not in text and "<vector" not in text:
        raise SplashError(
            f"[tool.kivy.android.splash].source {source.name} is XML but is "
            "neither a <vector> nor an <animated-vector> drawable; AAPT would "
            "reject it.\n"
            "  Use a PNG for a static splash, or an AnimatedVectorDrawable "
            "for an animated one."
        )
    return text


def _centered(image, *, canvas: int, inner: int):
    """*image* scaled to fit *inner*, centered on a transparent *canvas* square."""
    from PIL import Image

    layer = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    fitted = _contain(image, inner, inner)
    layer.paste(
        fitted,
        ((canvas - fitted.width) // 2, (canvas - fitted.height) // 2),
    )
    return layer


def _contain(image, max_w: int, max_h: int):
    """*image* scaled to fit inside the box, preserving its aspect ratio."""
    from PIL import Image

    scale = min(max_w / image.width, max_h / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def _open(path: Path):
    image_module = _pillow()
    try:
        return image_module.open(path).convert("RGBA")
    except OSError as exc:
        raise SplashError(f"cannot read splash image {path}: {exc}") from exc


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _pillow():
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise SplashError(
            "generating the splash resources needs Pillow, which is not "
            "installed.\n"
            "  Install the Android extra: pip install 'kivyforge[android]'\n"
            "  (or use an AnimatedVectorDrawable XML source, which needs no "
            "image processing, or drop [tool.kivy.android.splash])."
        ) from exc
    return Image
