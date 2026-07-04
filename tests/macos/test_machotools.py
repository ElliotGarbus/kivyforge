"""Mach-O detection + tool wrappers (hermetic; Apple tools are faked)."""

from __future__ import annotations

import struct
import subprocess

import pytest

from kivyforge.macos import AppBundleError, machotools


def _write_magic(path, magic: int) -> None:
    path.write_bytes(struct.pack(">I", magic) + b"\x00\x00\x00\x00")


class TestIsMacho:
    def test_detects_macho_magics(self, tmp_path):
        for magic in (0xFEEDFACE, 0xFEEDFACF, 0xCAFEBABE, 0xCFFAEDFE):
            f = tmp_path / f"bin_{magic:x}"
            _write_magic(f, magic)
            assert machotools.is_macho(f)

    def test_rejects_text_short_and_dirs(self, tmp_path):
        text = tmp_path / "a.txt"
        text.write_text("hello world")
        assert not machotools.is_macho(text)

        short = tmp_path / "short"
        short.write_bytes(b"\x01\x02")
        assert not machotools.is_macho(short)

        assert not machotools.is_macho(tmp_path)

    def test_rejects_symlink(self, tmp_path):
        real = tmp_path / "real"
        _write_magic(real, 0xFEEDFACF)
        link = tmp_path / "link"
        link.symlink_to(real)
        assert not machotools.is_macho(link)


class TestToolWrappers:
    def test_lipo_create_requires_inputs(self):
        with pytest.raises(AppBundleError, match="no inputs"):
            machotools.lipo_create([], "/tmp/out")

    def test_run_missing_tool_is_actionable(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("nope")

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(AppBundleError, match="not found"):
            machotools.codesign_adhoc("/tmp/x")

    def test_run_nonzero_raises(self, monkeypatch):
        def fail(*a, **k):
            return subprocess.CompletedProcess(a[0], 1, "", "boom")

        monkeypatch.setattr(subprocess, "run", fail)
        with pytest.raises(AppBundleError, match="boom"):
            machotools.lipo_create(["/a", "/b"], "/out")

    def test_macho_arches_parses_lipo(self, monkeypatch):
        def ok(*a, **k):
            return subprocess.CompletedProcess(a[0], 0, "x86_64 arm64\n", "")

        monkeypatch.setattr(subprocess, "run", ok)
        assert machotools.macho_arches("/bin/x") == ("x86_64", "arm64")

    def test_macho_arches_empty_on_error(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "e"),
        )
        assert machotools.macho_arches("/bin/x") == ()

    def test_codesign_verify_bool(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""),
        )
        assert machotools.codesign_verify("/app") is True
