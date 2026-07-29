"""Wheel selection + unpacking + per-arch merge (hermetic)."""

from __future__ import annotations

import zipfile

import pytest

from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.platforms.macos import AppBundleError, wheels_stage


def _wheel(name: str) -> LockedWheel:
    return LockedWheel(name=name, url=f"https://e/{name}", sha256="a" * 64)


def _pkg(name, wheels):
    return LockedPackage(name=name, version="1.0", wheels=tuple(wheels))


class TestSelectWheel:
    def test_pure_python(self):
        w = _wheel("foo-1.0-py3-none-any.whl")
        assert wheels_stage._select_wheel(_pkg("foo", [w]), "arm64") is w

    def test_universal2_satisfies_arm64(self):
        # A universal2 wheel *contains* arm64, so it is a valid pick.
        w = _wheel("foo-1.0-cp314-cp314-macosx_11_0_universal2.whl")
        assert wheels_stage._select_wheel(_pkg("foo", [w]), "arm64") is w

    def test_thin_arm64(self):
        w = _wheel("foo-1.0-cp314-cp314-macosx_11_0_arm64.whl")
        assert wheels_stage._select_wheel(_pkg("foo", [w]), "arm64") is w

    def test_intel_only_fails(self):
        intel = _wheel("foo-1.0-cp314-cp314-macosx_10_13_x86_64.whl")
        with pytest.raises(AppBundleError, match="no arm64 wheel"):
            wheels_stage._select_wheel(_pkg("foo", [intel]), "arm64")


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
