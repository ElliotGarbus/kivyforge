"""icns generation drives sips + iconutil (tools faked)."""

from __future__ import annotations

import struct

import pytest

from kivyforge.platforms.macos import AppBundleError, icns


def _png_1024(path):
    ihdr = struct.pack(">II", 1024, 1024)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + ihdr)


def test_generate_icns_invokes_tools(tmp_path, monkeypatch):
    src = tmp_path / "icon.png"
    _png_1024(src)
    ran = []
    monkeypatch.setattr(icns, "_run", lambda cmd: ran.append(cmd[0]))
    icns.generate_icns(src, tmp_path / "out" / "icon.icns")
    # 10 sips resizes + 1 iconutil
    assert ran.count("sips") == 10
    assert ran.count("iconutil") == 1


def test_generate_icns_rejects_bad_png(tmp_path, monkeypatch):
    src = tmp_path / "small.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 16, 16))
    monkeypatch.setattr(icns, "_run", lambda cmd: None)
    with pytest.raises(Exception, match="1024"):
        icns.generate_icns(src, tmp_path / "icon.icns")


def test_run_missing_tool(monkeypatch):
    monkeypatch.setattr(icns.shutil, "which", lambda name: None)
    with pytest.raises(AppBundleError, match="not found"):
        icns._run(["sips", "-z"])
