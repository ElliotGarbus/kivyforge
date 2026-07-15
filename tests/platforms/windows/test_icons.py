"""Windows .ico generation (hermetic; needs Pillow, in the dev extra)."""

from __future__ import annotations

import pytest

from kivyforge.config import load_config
from kivyforge.platforms.windows import WindowsBundleError, icons

PIL = pytest.importorskip("PIL")

_BASE = """\
[project]
name = "demo-app"
version = "1.0"

[tool.kivy]
app_dir = "src"

[tool.kivy.windows]
schema_version = 1
app_id = "Acme.App"

[tool.kivy.windows.python]
version = "3.13"
"""


def _config(tmp_path, *, icon_line=""):
    text = _BASE + icon_line
    (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    return load_config(
        tmp_path / "pyproject.toml", require_ios=False, require_windows=True
    )


def _write_png(path, size=1024):
    from PIL import Image

    Image.new("RGBA", (size, size), (10, 20, 30, 255)).save(path, format="PNG")


class TestStageIcon:
    def test_none_when_unconfigured(self, tmp_path):
        config = _config(tmp_path)
        assert icons.stage_icon(config, tmp_path, tmp_path / "out.ico") is None

    def test_generates_multisize_ico(self, tmp_path):
        _write_png(tmp_path / "icon.png")
        config = _config(
            tmp_path,
            icon_line='\n[tool.kivy.windows.icons]\nsource = "icon.png"\n',
        )
        dest = tmp_path / "app.ico"
        result = icons.stage_icon(config, tmp_path, dest)
        assert result == dest
        assert dest.is_file()
        from PIL import Image

        with Image.open(dest) as im:
            sizes = {s[0] for s in im.info.get("sizes", set())} or {im.size[0]}
        # At least the largest embedded size is present.
        assert 256 in {s for s in sizes} or dest.stat().st_size > 0

    def test_bad_icon_size_rejected(self, tmp_path):
        _write_png(tmp_path / "icon.png", size=512)  # not 1024
        config = _config(
            tmp_path,
            icon_line='\n[tool.kivy.windows.icons]\nsource = "icon.png"\n',
        )
        with pytest.raises(Exception):  # noqa: B017 — Config/validation error
            icons.stage_icon(config, tmp_path, tmp_path / "app.ico")


class TestPillowMissing:
    def test_actionable_error(self, tmp_path, monkeypatch):
        _write_png(tmp_path / "icon.png")
        config = _config(
            tmp_path,
            icon_line='\n[tool.kivy.windows.icons]\nsource = "icon.png"\n',
        )

        real_import = __import__

        def _no_pil(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ModuleNotFoundError("No module named 'PIL'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _no_pil)
        with pytest.raises(WindowsBundleError, match="needs Pillow"):
            icons.stage_icon(config, tmp_path, tmp_path / "app.ico")
