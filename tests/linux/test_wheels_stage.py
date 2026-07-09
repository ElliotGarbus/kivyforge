"""Linux wheel selection + unpacking (hermetic)."""

from __future__ import annotations

import zipfile

import pytest

from kivyforge.linux import AppDirError, wheels_stage
from kivyforge.lock.model import LockedPackage, LockedWheel


def _wheel_zip(path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def _pkg(name, wheels):
    return LockedPackage(name=name, version="1.0", wheels=tuple(wheels))


class TestSelectWheel:
    def test_prefers_pure_python(self):
        pure = LockedWheel(name="a-1.0-py3-none-any.whl", url="u", sha256="s")
        native = LockedWheel(
            name="a-1.0-cp315-cp315-manylinux_2_17_x86_64.whl", url="u2", sha256="s2"
        )
        assert wheels_stage._select_wheel(_pkg("a", [native, pure]), "x86_64") is pure

    def test_picks_manylinux_for_arch(self):
        native = LockedWheel(
            name="a-1.0-cp315-cp315-manylinux2014_x86_64.whl", url="u", sha256="s"
        )
        assert wheels_stage._select_wheel(_pkg("a", [native]), "x86_64") is native

    def test_compound_tag_covers(self):
        native = LockedWheel(
            name="a-1.0-cp315-cp315-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
            url="u",
            sha256="s",
        )
        assert wheels_stage._select_wheel(_pkg("a", [native]), "x86_64") is native

    def test_no_covering_wheel_fails(self):
        musl = LockedWheel(
            name="a-1.0-cp315-cp315-musllinux_1_1_x86_64.whl", url="u", sha256="s"
        )
        with pytest.raises(AppDirError, match="no wheel for arch x86_64"):
            wheels_stage._select_wheel(_pkg("a", [musl]), "x86_64")


class TestUnpack:
    def test_normalizes_data_dir(self, tmp_path):
        wheel = tmp_path / "a-1.0-py3-none-any.whl"
        _wheel_zip(
            wheel,
            {
                "pkg/__init__.py": "x",
                "a-1.0.data/purelib/extra/mod.py": "y",
            },
        )
        target = tmp_path / "lib"
        target.mkdir()
        wheels_stage._unpack(wheel, target)
        assert (target / "pkg" / "__init__.py").exists()
        assert (target / "extra" / "mod.py").read_text() == "y"
        assert not list(target.glob("*.data"))

    def test_rejects_path_traversal(self, tmp_path):
        wheel = tmp_path / "evil.whl"
        _wheel_zip(wheel, {"../escape.py": "x"})
        target = tmp_path / "lib"
        target.mkdir()
        with pytest.raises(AppDirError, match="unsafe path in wheel"):
            wheels_stage._unpack(wheel, target)


class TestStageWheels:
    def test_unpacks_all(self, tmp_path, monkeypatch):
        w1 = tmp_path / "a-1.0-py3-none-any.whl"
        w2 = tmp_path / "b-1.0-cp315-cp315-manylinux_2_17_x86_64.whl"
        _wheel_zip(w1, {"a/__init__.py": "x"})
        _wheel_zip(w2, {"b/__init__.py": "y", "b/_ext.so": "bin"})
        fetched = {
            "a-1.0-py3-none-any.whl": w1,
            "b-1.0-cp315-cp315-manylinux_2_17_x86_64.whl": w2,
        }
        monkeypatch.setattr(
            wheels_stage, "_fetch", lambda wheel, *a, **k: fetched[wheel.name]
        )
        packages = (
            _pkg("a", [LockedWheel(name=w1.name, url="u", sha256="s")]),
            _pkg("b", [LockedWheel(name=w2.name, url="u", sha256="s")]),
        )
        lib = tmp_path / "appdir" / "usr" / "lib"
        wheels_stage.stage_wheels(packages, "x86_64", lib, project_root=tmp_path)
        assert (lib / "a" / "__init__.py").exists()
        assert (lib / "b" / "_ext.so").exists()
