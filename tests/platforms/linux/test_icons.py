"""Icon set generation (Pillow-backed)."""

from __future__ import annotations

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.icon import IconSourceError
from kivyforge.platforms.linux import icons

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

_BASE = (
    "[project]\nname='myapp'\nversion='1.0.0'\nrequires-python='>=3.15'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
    "{icons}"
    "[tool.kivy.linux.python]\nversion='3.15.0'\n"
)


def _config(icons_block=""):
    return load_config_from_text(
        _BASE.format(icons=icons_block), require_ios=False, require_linux=True
    )


def _write_png(path, size=(1024, 1024)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (10, 20, 30, 255)).save(path, format="PNG")


class TestStageIcons:
    def test_unset_source_writes_default(self, tmp_path):
        appdir = tmp_path / "app.AppDir"
        appdir.mkdir()
        assert icons.stage_icons(_config(), tmp_path, appdir) is False
        root = appdir / "org.example.myapp.png"
        assert root.exists()
        # A valid PNG at the AppImage root icon size.
        assert Image.open(root).size == (icons.ROOT_ICON_SIZE, icons.ROOT_ICON_SIZE)
        assert (
            appdir / "usr/share/icons/hicolor/256x256/apps/org.example.myapp.png"
        ).exists()
        # .DirIcon is written for folder-artifact consumers, matching the root.
        diricon = appdir / ".DirIcon"
        assert diricon.exists()
        assert diricon.read_bytes() == root.read_bytes()

    def test_generates_hicolor_and_root(self, tmp_path):
        _write_png(tmp_path / "assets" / "icon.png")
        cfg = _config("[tool.kivy.linux.icons]\nsource='assets/icon.png'\n")
        appdir = tmp_path / "app.AppDir"
        appdir.mkdir()
        assert icons.stage_icons(cfg, tmp_path, appdir) is True
        root = appdir / "org.example.myapp.png"
        assert root.exists()
        assert Image.open(root).size == (icons.ROOT_ICON_SIZE, icons.ROOT_ICON_SIZE)
        diricon = appdir / ".DirIcon"
        assert diricon.exists()
        assert diricon.read_bytes() == root.read_bytes()
        for size in icons.HICOLOR_SIZES:
            icon = (
                appdir
                / "usr"
                / "share"
                / "icons"
                / "hicolor"
                / f"{size}x{size}"
                / "apps"
                / "org.example.myapp.png"
            )
            assert icon.exists()
            assert Image.open(icon).size == (size, size)

    def test_bad_size_rejected(self, tmp_path):
        _write_png(tmp_path / "assets" / "icon.png", size=(512, 512))
        cfg = _config("[tool.kivy.linux.icons]\nsource='assets/icon.png'\n")
        appdir = tmp_path / "app.AppDir"
        appdir.mkdir()
        with pytest.raises(IconSourceError):
            icons.stage_icons(cfg, tmp_path, appdir)
