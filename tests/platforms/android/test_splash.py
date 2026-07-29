"""Splash-screen generation (android/01 §splash, android/04 §resources).

The splash is entirely resources: theme attributes the OS reads on API 31+, and
a ``windowBackground`` drawable that covers the gap below 31 and the handoff
above it. So the things worth pinning are that the two layers agree, that every
resource the theme names actually exists (AAPT fails the project otherwise), and
that no Maven dependency crept back in.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.android.generate.project import (
    ProjectGenError,
    write_resources,
)
from kivyforge.platforms.android.splash import (
    DENSITIES,
    ICON_CANVAS_DP,
    ICON_CANVAS_WITH_BACKGROUND_DP,
    SplashError,
    write_splash,
)

Image = pytest.importorskip("PIL.Image", reason="splash generation needs Pillow")

BASE = """
[project]
name = "splashapp"
version = "1.0.0"
dependencies = ["pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.example.splashapp"

[tool.kivy.android.python]
version = "3.14.6"
"""

ANIMATED_VECTOR = """<?xml version="1.0" encoding="utf-8"?>
<animated-vector xmlns:android="http://schemas.android.com/apk/res/android">
</animated-vector>
"""


def _config(extra: str = ""):
    text = BASE.replace(
        "[tool.kivy.android.python]", extra + "\n[tool.kivy.android.python]"
    )
    config = load_config_from_text(text, require_ios=False, require_android=True)
    return config, config.android_required


def _png(path, *, size=(512, 512), color=(10, 120, 200, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path, format="PNG")
    return path


class TestNoSplash:
    def test_nothing_generated(self, tmp_path):
        config, android = _config()
        theme = write_splash(tmp_path / "res", android, tmp_path)
        assert not theme.configured
        assert theme.v31_items == ()

    def test_theme_is_untouched(self, tmp_path):
        config, android = _config()
        write_resources(tmp_path, config, android, project_root=tmp_path)
        res = tmp_path / "app" / "src" / "main" / "res"
        styles = (res / "values" / "styles.xml").read_text()
        assert f'parent="{android.base_theme}" />' in styles
        assert not (res / "values-v31").exists()


class TestGeneratedSplash:
    def test_icon_emitted_for_every_density(self, tmp_path):
        _png(tmp_path / "assets" / "splash.png")
        config, android = _config(
            "[tool.kivy.android.splash]\nsource = 'assets/splash.png'\n"
        )
        res = tmp_path / "res"
        write_splash(res, android, tmp_path)
        for bucket, scale in DENSITIES.items():
            icon = res / f"drawable-{bucket}" / "kf_splash_icon.png"
            assert icon.is_file(), bucket
            assert Image.open(icon).size == (
                round(ICON_CANVAS_DP * scale),
                round(ICON_CANVAS_DP * scale),
            )

    def test_artwork_stays_inside_the_visible_inner_box(self, tmp_path):
        """The system splash masks the icon to a circle; artwork drawn to the
        canvas edge would be clipped."""
        _png(tmp_path / "splash.png")
        config, android = _config("[tool.kivy.android.splash]\nsource = 'splash.png'\n")
        res = tmp_path / "res"
        write_splash(res, android, tmp_path)
        icon = Image.open(res / "drawable-mdpi" / "kf_splash_icon.png")
        # The outer ring must be fully transparent.
        assert icon.getpixel((0, 0))[3] == 0
        assert icon.getpixel((icon.width - 1, 0))[3] == 0
        assert icon.getpixel((icon.width // 2, icon.height // 2))[3] == 255

    def test_icon_background_shrinks_the_canvas(self, tmp_path):
        """With a colored disc behind it the platform's canvas is 240dp, not
        288dp, and artwork sized for the larger one would overflow the disc."""
        _png(tmp_path / "splash.png")
        config, android = _config(
            "[tool.kivy.android.splash]\n"
            "source = 'splash.png'\n"
            "icon_background = '#ffffff'\n"
        )
        res = tmp_path / "res"
        theme = write_splash(res, android, tmp_path)
        icon = Image.open(res / "drawable-mdpi" / "kf_splash_icon.png")
        assert icon.size == (ICON_CANVAS_WITH_BACKGROUND_DP,) * 2
        assert (
            "android:windowSplashScreenIconBackgroundColor",
            "@color/kf_splash_icon_background",
        ) in theme.v31_items

    def test_background_color_becomes_a_color_resource(self, tmp_path):
        _png(tmp_path / "splash.png")
        config, android = _config(
            "[tool.kivy.android.splash]\n"
            "source = 'splash.png'\n"
            "background = '#102030'\n"
        )
        res = tmp_path / "res"
        write_splash(res, android, tmp_path)
        colors = (res / "values" / "kf_splash.xml").read_text()
        assert 'name="kf_splash_background">#102030<' in colors

    def test_default_background_when_unset(self, tmp_path):
        _png(tmp_path / "splash.png")
        config, android = _config("[tool.kivy.android.splash]\nsource = 'splash.png'\n")
        res = tmp_path / "res"
        write_splash(res, android, tmp_path)
        assert "#ffffff" in (res / "values" / "kf_splash.xml").read_text()

    def test_window_background_layers_color_under_the_icon(self, tmp_path):
        """This drawable is the splash below API 31 and the post-handoff window
        above it, so it has to carry both the color and the icon."""
        _png(tmp_path / "splash.png")
        config, android = _config("[tool.kivy.android.splash]\nsource = 'splash.png'\n")
        res = tmp_path / "res"
        write_splash(res, android, tmp_path)
        root = ET.parse(res / "drawable" / "kf_splash.xml").getroot()
        assert root.tag == "layer-list"
        items = list(root)
        assert len(items) == 2
        ns = "{http://schemas.android.com/apk/res/android}"
        assert items[0].get(f"{ns}drawable") == "@color/kf_splash_background"
        assert items[1].get(f"{ns}gravity") == "center"

    def test_animated_vector_passes_through_unresized(self, tmp_path):
        """A vector is density-independent and the platform animates it as-is;
        rasterizing it would destroy the only reason to use one."""
        (tmp_path / "splash.xml").write_text(ANIMATED_VECTOR, encoding="utf-8")
        config, android = _config(
            "[tool.kivy.android.splash]\n"
            "source = 'splash.xml'\n"
            "animation_duration = 750\n"
        )
        res = tmp_path / "res"
        theme = write_splash(res, android, tmp_path)
        assert (res / "drawable" / "kf_splash_icon.xml").read_text() == ANIMATED_VECTOR
        assert not list(res.glob("drawable-*/kf_splash_icon.png"))
        assert (
            "android:windowSplashScreenAnimationDuration",
            "750",
        ) in theme.v31_items

    def test_duration_is_dropped_for_a_static_icon(self, tmp_path):
        """Documented as ignored for a PNG; emitting it would delay every launch
        for an animation that does not exist."""
        _png(tmp_path / "splash.png")
        config, android = _config(
            "[tool.kivy.android.splash]\n"
            "source = 'splash.png'\n"
            "animation_duration = 900\n"
        )
        theme = write_splash(tmp_path / "res", android, tmp_path)
        assert not any(
            name.endswith("AnimationDuration") for name, _ in theme.v31_items
        )

    def test_branding_image_is_emitted_within_the_platform_box(self, tmp_path):
        _png(tmp_path / "splash.png")
        _png(tmp_path / "brand.png", size=(800, 200))
        config, android = _config(
            "[tool.kivy.android.splash]\n"
            "source = 'splash.png'\n"
            "branding = 'brand.png'\n"
        )
        res = tmp_path / "res"
        theme = write_splash(res, android, tmp_path)
        brand = Image.open(res / "drawable-mdpi" / "kf_splash_branding.png")
        assert brand.width <= 200 and brand.height <= 80
        # Aspect preserved: a 4:1 source fits the 200x80 box on width.
        assert brand.size == (200, 50)
        assert (
            "android:windowSplashScreenBrandingImage",
            "@drawable/kf_splash_branding",
        ) in theme.v31_items


class TestThemeEmission:
    def _resources(self, tmp_path, extra: str):
        _png(tmp_path / "splash.png")
        config, android = _config(extra)
        write_resources(tmp_path, config, android, project_root=tmp_path)
        return tmp_path / "app" / "src" / "main" / "res", android

    def test_base_theme_gets_the_window_background_only(self, tmp_path):
        """windowSplashScreen* are API 31 attributes; naming them in the default
        values/ folder would apply them where they mean nothing."""
        res, android = self._resources(
            tmp_path, "[tool.kivy.android.splash]\nsource = 'splash.png'\n"
        )
        styles = (res / "values" / "styles.xml").read_text()
        assert "android:windowBackground" in styles
        assert "windowSplashScreen" not in styles

    def test_v31_theme_carries_the_platform_attributes(self, tmp_path):
        res, android = self._resources(
            tmp_path, "[tool.kivy.android.splash]\nsource = 'splash.png'\n"
        )
        styles = (res / "values-v31" / "styles.xml").read_text()
        assert f'parent="{android.base_theme}"' in styles
        assert "android:windowSplashScreenBackground" in styles
        assert "android:windowSplashScreenAnimatedIcon" in styles
        # A values-v31 resource replaces the base one wholesale, so the override
        # has to repeat what the base theme said too.
        assert "android:windowBackground" in styles

    def test_every_named_resource_exists(self, tmp_path):
        """A theme naming a missing drawable/color fails the whole AAPT run."""
        _png(tmp_path / "splash.png")
        _png(tmp_path / "brand.png", size=(400, 100))
        config, android = _config(
            "[tool.kivy.android.splash]\n"
            "source = 'splash.png'\n"
            "background = '#000000'\n"
            "icon_background = '#ffffff'\n"
            "branding = 'brand.png'\n"
        )
        write_resources(tmp_path, config, android, project_root=tmp_path)
        res = tmp_path / "app" / "src" / "main" / "res"
        styles = (res / "values-v31" / "styles.xml").read_text()
        colors = (res / "values" / "kf_splash.xml").read_text()
        for ref in ("@color/kf_splash_background", "@color/kf_splash_icon_background"):
            assert ref in styles
            assert f'name="{ref.split("/")[1]}"' in colors
        assert (res / "drawable" / "kf_splash.xml").is_file()
        for bucket in DENSITIES:
            assert (res / f"drawable-{bucket}" / "kf_splash_icon.png").is_file()
            assert (res / f"drawable-{bucket}" / "kf_splash_branding.png").is_file()


class TestFailures:
    def test_missing_source_is_actionable(self, tmp_path):
        config, android = _config("[tool.kivy.android.splash]\nsource = 'nope.png'\n")
        with pytest.raises(SplashError, match="source not found"):
            write_splash(tmp_path / "res", android, tmp_path)

    def test_missing_branding_is_actionable(self, tmp_path):
        _png(tmp_path / "splash.png")
        config, android = _config(
            "[tool.kivy.android.splash]\nsource = 'splash.png'\nbranding = 'nope.png'\n"
        )
        with pytest.raises(SplashError, match="branding not found"):
            write_splash(tmp_path / "res", android, tmp_path)

    def test_xml_that_is_not_a_drawable_is_rejected(self, tmp_path):
        (tmp_path / "splash.xml").write_text("<resources/>\n", encoding="utf-8")
        config, android = _config("[tool.kivy.android.splash]\nsource = 'splash.xml'\n")
        with pytest.raises(SplashError, match="neither a <vector>"):
            write_splash(tmp_path / "res", android, tmp_path)

    def test_old_compile_sdk_is_rejected_with_a_way_out(self, tmp_path):
        _png(tmp_path / "splash.png")
        config, android = _config(
            "compile_sdk = 30\n"
            "target_sdk = 30\n"
            "[tool.kivy.android.splash]\n"
            "source = 'splash.png'\n"
        )
        with pytest.raises(SplashError, match="compile_sdk >= 31"):
            write_splash(tmp_path / "res", android, tmp_path)

    def test_failure_surfaces_as_a_generator_error(self, tmp_path):
        config, android = _config("[tool.kivy.android.splash]\nsource = 'nope.png'\n")
        with pytest.raises(ProjectGenError, match="source not found"):
            write_resources(tmp_path, config, android, project_root=tmp_path)
