"""icns generation drives sips + iconutil (tools faked)."""

from __future__ import annotations

import struct
import subprocess

import pytest

from kivyforge.platforms.macos import AppBundleError, icns
from kivyforge.report import diagnostics, exit_codes


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


def test_run_missing_tool_is_toolchain_missing(monkeypatch):
    """A missing ``sips``/``iconutil`` classifies like every other macOS tool.

    Regression for the build/package output work: this helper used to
    pre-check with ``shutil.which`` and raise a bare ``AppBundleError``, which
    defaulted to ``KF-ERROR``/exit 1 instead of ``KF-TOOLCHAIN-MISSING``/exit 3
    — the only macOS spawn site the four commits missed (found by hand on
    2026-09-16, ``build-package-output-mac-findings.md``).
    """

    def boom(*a, **k):
        raise FileNotFoundError("nope")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(AppBundleError, match="not found") as excinfo:
        icns._run(["sips", "-z"])
    assert excinfo.value.code == diagnostics.TOOLCHAIN_MISSING
    assert excinfo.value.exit_code == exit_codes.ENVIRONMENT_ERROR
    assert excinfo.value.context == {"tool": "sips"}


def test_run_unusable_tool_is_toolchain_unusable(monkeypatch):
    def boom(*a, **k):
        raise PermissionError("not executable")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(AppBundleError, match="unusable") as excinfo:
        icns._run(["sips", "-z"])
    assert excinfo.value.code == diagnostics.TOOLCHAIN_UNUSABLE
    assert excinfo.value.exit_code == exit_codes.ENVIRONMENT_ERROR
