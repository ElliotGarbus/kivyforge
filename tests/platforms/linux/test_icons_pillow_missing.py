"""The missing-Pillow error path for Linux icon generation.

``test_icons.py`` skips its whole module when Pillow is absent, so it can never
exercise the ``_pillow()`` failure. Here we simulate Pillow being uninstalled
(regardless of whether it is actually present) by poisoning ``sys.modules`` so
``from PIL import Image`` raises ``ModuleNotFoundError``, and assert the
actionable ``AppDirError`` surfaces both directly and through ``stage_icons``.
"""

from __future__ import annotations

import sys

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.linux import AppDirError, icons

_BASE = (
    "[project]\nname='myapp'\nversion='1.0.0'\nrequires-python='>=3.15'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
    "[tool.kivy.linux.icons]\nsource='assets/icon.png'\n"
    "[tool.kivy.linux.python]\nversion='3.15.0'\n"
)


@pytest.fixture
def no_pillow(monkeypatch):
    """Make ``from PIL import Image`` raise ModuleNotFoundError."""
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)


def test_pillow_helper_raises_with_hint(no_pillow):
    with pytest.raises(AppDirError, match="Pillow"):
        icons._pillow()
    # The message points at the install extra.
    try:
        icons._pillow()
    except AppDirError as exc:
        assert "kivyforge[linux]" in str(exc)


def test_stage_icons_missing_pillow_with_source(no_pillow, tmp_path):
    # A valid 1024x1024 source so validation passes and we reach _open -> _pillow.
    src = tmp_path / "assets" / "icon.png"
    src.parent.mkdir(parents=True)
    src.write_bytes(icons._solid_png(1024, (10, 20, 30, 255)))
    cfg = load_config_from_text(_BASE, require_ios=False, require_linux=True)
    appdir = tmp_path / "app.AppDir"
    appdir.mkdir()
    with pytest.raises(AppDirError, match="Pillow"):
        icons.stage_icons(cfg, tmp_path, appdir)
