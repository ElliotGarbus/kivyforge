"""Launcher-icon generation (android/01 §icons, android/04 §resources).

The generated manifest names ``@mipmap/ic_launcher`` unconditionally, so the
regression these tests guard is a build that emits *no* icon for that name:
AAPT then fails the entire project ("resource mipmap/ic_launcher not found"),
which is exactly what a configured icon source used to cause.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.android.generate.manifest import generate_manifest
from kivyforge.platforms.android.generate.project import (
    ProjectGenError,
    write_resources,
)
from kivyforge.platforms.android.icons import (
    ADAPTIVE_SIZES,
    LEGACY_SIZES,
    IconError,
    adaptive_icon_xml,
    write_icons,
)

Image = pytest.importorskip("PIL.Image", reason="icon generation needs Pillow")

BASE = """
[project]
name = "iconapp"
version = "1.0.0"
dependencies = ["pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.example.iconapp"

[tool.kivy.android.python]
version = "3.14.6"
"""


def _config(extra: str = ""):
    text = BASE.replace(
        "[tool.kivy.android.python]", extra + "\n[tool.kivy.android.python]"
    )
    config = load_config_from_text(text, require_ios=False, require_android=True)
    return config, config.android_required


def _source(path, *, size: int = 1024, color=(200, 30, 40, 255)):
    Image.new("RGBA", (size, size), color).save(path, format="PNG")
    return path


class TestConfiguredSource:
    def _generate(self, tmp_path, extra_icons: str = ""):
        config, android = _config(
            "[tool.kivy.android.icons]\nsource = 'icon.png'\n" + extra_icons
        )
        _source(tmp_path / "icon.png")
        res = tmp_path / "res"
        used = write_icons(res, config, android, tmp_path)
        return res, used

    def test_every_density_gets_a_launcher_icon(self, tmp_path):
        res, used = self._generate(tmp_path)
        assert used is True
        for bucket, size in LEGACY_SIZES.items():
            icon = res / f"mipmap-{bucket}" / "ic_launcher.png"
            assert icon.is_file(), bucket
            assert Image.open(icon).size == (size, size)

    def test_adaptive_layers_and_drawable_emitted(self, tmp_path):
        res, _ = self._generate(tmp_path)
        for bucket, size in ADAPTIVE_SIZES.items():
            layer = res / f"mipmap-{bucket}" / "ic_launcher_foreground.png"
            assert Image.open(layer).size == (size, size)
        xml = (res / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text()
        root = ET.fromstring(xml)
        assert root.tag == "adaptive-icon"
        # The round variant must resolve too: the manifest names roundIcon.
        assert (res / "mipmap-anydpi-v26" / "ic_launcher_round.xml").is_file()
        assert (res / "mipmap-mdpi" / "ic_launcher_round.png").is_file()

    def test_foreground_artwork_stays_inside_the_safe_zone(self, tmp_path):
        """A launcher mask crops the outer ring of the 108dp layer, so artwork
        scaled edge to edge loses ~28% of itself; the corners must be clear."""
        res, _ = self._generate(tmp_path)
        layer = Image.open(res / "mipmap-xxxhdpi" / "ic_launcher_foreground.png")
        assert layer.getpixel((0, 0))[3] == 0  # transparent corner
        center = layer.size[0] // 2
        assert layer.getpixel((center, center))[3] == 255

    def test_hex_background_becomes_a_color_resource(self, tmp_path):
        res, _ = self._generate(tmp_path, "background = '#123456'\n")
        values = (res / "values" / "ic_launcher_background.xml").read_text()
        assert "#123456" in values
        xml = (res / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text()
        assert "@color/ic_launcher_background" in xml
        assert not (res / "mipmap-mdpi" / "ic_launcher_background.png").exists()

    def test_image_background_becomes_a_mipmap(self, tmp_path):
        config, android = _config(
            "[tool.kivy.android.icons]\nsource = 'icon.png'\nbackground = 'bg.png'\n"
        )
        _source(tmp_path / "icon.png")
        _source(tmp_path / "bg.png", color=(0, 0, 255, 255))
        res = tmp_path / "res"
        write_icons(res, config, android, tmp_path)
        assert (res / "mipmap-mdpi" / "ic_launcher_background.png").is_file()
        xml = (res / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text()
        assert "@mipmap/ic_launcher_background" in xml

    def test_monochrome_layer_emitted(self, tmp_path):
        config, android = _config(
            "[tool.kivy.android.icons]\nsource = 'icon.png'\nmonochrome = 'mono.png'\n"
        )
        _source(tmp_path / "icon.png")
        _source(tmp_path / "mono.png", color=(255, 255, 255, 255))
        res = tmp_path / "res"
        write_icons(res, config, android, tmp_path)
        assert (res / "mipmap-mdpi" / "ic_launcher_monochrome.png").is_file()
        assert (
            "monochrome" in (res / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text()
        )

    def test_monochrome_below_api_33_is_actionable(self, tmp_path):
        config, android = _config(
            "target_sdk = 32\ncompile_sdk = 32\n"
            "[tool.kivy.android.icons]\nsource = 'icon.png'\n"
            "monochrome = 'mono.png'\n"
        )
        _source(tmp_path / "icon.png")
        _source(tmp_path / "mono.png")
        with pytest.raises(IconError, match="compile_sdk"):
            write_icons(tmp_path / "res", config, android, tmp_path)

    def test_wrong_sized_source_is_rejected(self, tmp_path):
        config, android = _config("[tool.kivy.android.icons]\nsource = 'icon.png'\n")
        _source(tmp_path / "icon.png", size=512)
        with pytest.raises(IconError, match="512x512"):
            write_icons(tmp_path / "res", config, android, tmp_path)


class TestGeneratedProject:
    def test_manifest_icon_reference_always_resolves(self, tmp_path):
        """The end-to-end invariant: whatever the manifest names, the resources
        provide. This is the check the icon blocker would have failed."""
        for extra in ("", "[tool.kivy.android.icons]\nsource = 'icon.png'\n"):
            config, android = _config(extra)
            _source(tmp_path / "icon.png")
            dest = tmp_path / ("with" if extra else "without")
            write_resources(dest, config, android, project_root=tmp_path)
            res = dest / "app" / "src" / "main" / "res"
            manifest = generate_manifest(android, orientation=("portrait",))
            app = ET.fromstring(manifest).find("application")
            ns = "{http://schemas.android.com/apk/res/android}"
            for attr in ("icon", "roundIcon"):
                value = app.get(f"{ns}{attr}")
                if value is None:
                    continue
                name = value.split("/")[-1]
                assert list(res.glob(f"mipmap-*/{name}.*")), (extra, value)

    def test_icon_failure_surfaces_as_a_generator_error(self, tmp_path):
        """A missing/invalid source must fail generation with the actionable
        message, not escape as a bare imaging error."""
        config, android = _config("[tool.kivy.android.icons]\nsource = 'icon.png'\n")
        with pytest.raises(ProjectGenError, match="icon not found"):
            write_resources(tmp_path / "out", config, android, project_root=tmp_path)


class TestAdaptiveXml:
    def test_color_background_without_monochrome(self):
        xml = adaptive_icon_xml(background_is_color=True, monochrome=False)
        assert "@color/ic_launcher_background" in xml
        assert "monochrome" not in xml
        ET.fromstring(xml)  # well-formed

    def test_image_background_with_monochrome(self):
        xml = adaptive_icon_xml(background_is_color=False, monochrome=True)
        assert "@mipmap/ic_launcher_background" in xml
        assert "@mipmap/ic_launcher_monochrome" in xml
        ET.fromstring(xml)
