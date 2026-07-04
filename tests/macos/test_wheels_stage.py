"""Wheel selection + unpacking + per-arch merge (hermetic)."""

from __future__ import annotations

import zipfile

import pytest

from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.macos import AppBundleError, wheels_stage


def _wheel(name: str) -> LockedWheel:
    return LockedWheel(name=name, url=f"https://e/{name}", sha256="a" * 64)


def _pkg(name, wheels):
    return LockedPackage(name=name, version="1.0", wheels=tuple(wheels))


class TestSelectWheels:
    def test_pure_python_single(self):
        w = _wheel("foo-1.0-py3-none-any.whl")
        base, extra = wheels_stage._select_wheels(_pkg("foo", [w]), ("arm64",))
        assert base is w
        assert extra == []

    def test_universal2_single(self):
        w = _wheel("foo-1.0-cp314-cp314-macosx_11_0_universal2.whl")
        base, extra = wheels_stage._select_wheels(_pkg("foo", [w]), ("arm64", "x86_64"))
        assert base is w
        assert extra == []

    def test_per_arch_base_plus_extras(self):
        arm = _wheel("foo-1.0-cp314-cp314-macosx_11_0_arm64.whl")
        intel = _wheel("foo-1.0-cp314-cp314-macosx_10_13_x86_64.whl")
        base, extra = wheels_stage._select_wheels(
            _pkg("foo", [arm, intel]), ("arm64", "x86_64")
        )
        assert base is arm
        assert extra == [intel]

    def test_missing_arch_fails(self):
        arm = _wheel("foo-1.0-cp314-cp314-macosx_11_0_arm64.whl")
        with pytest.raises(AppBundleError, match="no wheel for arch"):
            wheels_stage._select_wheels(_pkg("foo", [arm]), ("arm64", "x86_64"))


def _make_wheel(path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


class TestUnpack:
    def test_extracts_and_normalizes_data_dir(self, tmp_path):
        wheel = tmp_path / "foo.whl"
        _make_wheel(
            wheel,
            {
                "foo/__init__.py": b"x = 1\n",
                "foo-1.0.data/purelib/foo/extra.py": b"y = 2\n",
                "foo-1.0.data/scripts/tool": b"#!/bin/sh\n",
            },
        )
        target = tmp_path / "lib"
        target.mkdir()
        wheels_stage._unpack(wheel, target)
        assert (target / "foo" / "__init__.py").exists()
        # purelib content is lifted to the site-packages root.
        assert (target / "foo" / "extra.py").exists()
        # the .data dir itself is removed after normalization.
        assert not list(target.glob("*.data"))

    def test_rejects_path_traversal(self, tmp_path):
        wheel = tmp_path / "evil.whl"
        with zipfile.ZipFile(wheel, "w") as zf:
            zf.writestr("../escape.py", b"nope")
        target = tmp_path / "lib"
        target.mkdir()
        with pytest.raises(AppBundleError, match="unsafe path"):
            wheels_stage._unpack(wheel, target)


class TestMergeWheelBinaries:
    def test_lipo_merges_matching_macho(self, tmp_path, monkeypatch):
        import struct

        # A per-arch wheel shipping a fake Mach-O .so.
        wheel = tmp_path / "foo-x86.whl"
        _make_wheel(
            wheel,
            {"foo/_c.so": struct.pack(">I", 0xFEEDFACF) + b"intel"},
        )
        lib = tmp_path / "lib"
        (lib / "foo").mkdir(parents=True)
        (lib / "foo" / "_c.so").write_bytes(struct.pack(">I", 0xFEEDFACF) + b"arm")

        calls = []

        def fake_lipo(inputs, output):
            calls.append((list(inputs), output))
            output.write_bytes(b"fat")

        monkeypatch.setattr(wheels_stage, "lipo_create", fake_lipo)
        wheels_stage._merge_wheel_binaries(wheel, lib)

        assert len(calls) == 1
        assert (lib / "foo" / "_c.so").read_bytes() == b"fat"

    def test_copies_arch_only_extension(self, tmp_path, monkeypatch):
        import struct

        wheel = tmp_path / "foo-x86.whl"
        _make_wheel(wheel, {"foo/only_intel.so": struct.pack(">I", 0xFEEDFACF)})
        lib = tmp_path / "lib"
        (lib / "foo").mkdir(parents=True)  # no counterpart present

        monkeypatch.setattr(
            wheels_stage, "lipo_create", lambda *a: pytest.fail("should not lipo")
        )
        wheels_stage._merge_wheel_binaries(wheel, lib)
        assert (lib / "foo" / "only_intel.so").exists()
