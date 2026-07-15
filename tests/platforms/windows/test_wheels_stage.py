"""Windows no-pip wheel-scheme installer (hermetic, host-agnostic)."""

from __future__ import annotations

import zipfile

import pytest

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.verify import sha256_file
from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.platforms.windows import WindowsBundleError, wheels_stage


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
            name="a-1.0-cp313-cp313-win_amd64.whl", url="u2", sha256="s2"
        )
        assert wheels_stage._select_wheel(_pkg("a", [native, pure]), "amd64") is pure

    def test_picks_win_amd64(self):
        native = LockedWheel(
            name="a-1.0-cp313-cp313-win_amd64.whl", url="u", sha256="s"
        )
        assert wheels_stage._select_wheel(_pkg("a", [native]), "amd64") is native

    def test_no_covering_wheel_fails(self):
        win32 = LockedWheel(name="a-1.0-cp313-cp313-win32.whl", url="u", sha256="s")
        with pytest.raises(WindowsBundleError, match="no wheel for arch amd64"):
            wheels_stage._select_wheel(_pkg("a", [win32]), "amd64")


class TestInstallSchemes:
    def _prefix(self, tmp_path):
        prefix = tmp_path / "python"
        (prefix / "Lib" / "site-packages").mkdir(parents=True)
        return prefix

    def test_package_root_to_site_packages(self, tmp_path):
        prefix = self._prefix(tmp_path)
        wheel = tmp_path / "a-1.0-py3-none-any.whl"
        _wheel_zip(wheel, {"pkg/__init__.py": "x", "a-1.0.dist-info/METADATA": "m"})
        wheels_stage._install(wheel, prefix, prefix / "Lib" / "site-packages")
        sp = prefix / "Lib" / "site-packages"
        assert (sp / "pkg" / "__init__.py").read_text() == "x"
        assert (sp / "a-1.0.dist-info" / "METADATA").exists()

    def test_data_data_lands_at_prefix_root(self, tmp_path):
        """The load-bearing invariant: .data/data/share/<dep>/bin survives."""
        prefix = self._prefix(tmp_path)
        wheel = tmp_path / "kivy_deps_sdl2-1.0-cp313-cp313-win_amd64.whl"
        _wheel_zip(
            wheel,
            {
                "kivy_deps/__init__.py": "x",
                "kivy_deps.sdl2-1.0.data/data/share/sdl2/bin/SDL2.dll": "DLL",
            },
        )
        wheels_stage._install(wheel, prefix, prefix / "Lib" / "site-packages")
        assert (prefix / "share" / "sdl2" / "bin" / "SDL2.dll").read_text() == "DLL"
        # It must NOT be left inside site-packages.
        assert not list((prefix / "Lib" / "site-packages").glob("*.data"))

    def test_purelib_platlib_to_site_packages(self, tmp_path):
        prefix = self._prefix(tmp_path)
        wheel = tmp_path / "a-1.0-py3-none-any.whl"
        _wheel_zip(
            wheel,
            {
                "a-1.0.data/purelib/purefile.py": "p",
                "a-1.0.data/platlib/_ext.pyd": "b",
            },
        )
        wheels_stage._install(wheel, prefix, prefix / "Lib" / "site-packages")
        sp = prefix / "Lib" / "site-packages"
        assert (sp / "purefile.py").read_text() == "p"
        assert (sp / "_ext.pyd").read_text() == "b"

    def test_scripts_and_headers_routed(self, tmp_path):
        prefix = self._prefix(tmp_path)
        wheel = tmp_path / "a-1.0-py3-none-any.whl"
        _wheel_zip(
            wheel,
            {
                "a-1.0.data/scripts/tool.exe": "s",
                "a-1.0.data/headers/a.h": "h",
            },
        )
        wheels_stage._install(wheel, prefix, prefix / "Lib" / "site-packages")
        assert (prefix / "Scripts" / "tool.exe").read_text() == "s"
        assert (prefix / "Include" / "a.h").read_text() == "h"

    def test_unknown_scheme_not_dropped(self, tmp_path):
        prefix = self._prefix(tmp_path)
        wheel = tmp_path / "a-1.0-py3-none-any.whl"
        _wheel_zip(wheel, {"a-1.0.data/weird/thing.txt": "t"})
        wheels_stage._install(wheel, prefix, prefix / "Lib" / "site-packages")
        assert (prefix / "weird" / "thing.txt").read_text() == "t"

    def test_rejects_path_traversal(self, tmp_path):
        prefix = self._prefix(tmp_path)
        wheel = tmp_path / "evil.whl"
        _wheel_zip(wheel, {"../escape.py": "x"})
        with pytest.raises(WindowsBundleError, match="unsafe path in wheel"):
            wheels_stage._install(wheel, prefix, prefix / "Lib" / "site-packages")


class TestStageWheels:
    def test_installs_all_and_preserves_existing_site_packages(
        self, tmp_path, monkeypatch
    ):
        prefix = tmp_path / "python"
        sp = prefix / "Lib" / "site-packages"
        sp.mkdir(parents=True)
        (sp / "pip").mkdir()  # a runtime-bundled package that must survive
        (sp / "pip" / "__init__.py").write_text("pip")

        w1 = tmp_path / "a-1.0-py3-none-any.whl"
        w2 = tmp_path / "b-1.0-cp313-cp313-win_amd64.whl"
        _wheel_zip(w1, {"a/__init__.py": "x"})
        _wheel_zip(w2, {"b/__init__.py": "y", "b/_ext.pyd": "bin"})
        fetched = {w1.name: w1, w2.name: w2}
        monkeypatch.setattr(
            wheels_stage, "_fetch", lambda wheel, *a, **k: fetched[wheel.name]
        )
        packages = (
            _pkg("a", [LockedWheel(name=w1.name, url="u", sha256="s")]),
            _pkg("b", [LockedWheel(name=w2.name, url="u", sha256="s")]),
        )
        wheels_stage.stage_wheels(packages, "amd64", prefix, project_root=tmp_path)
        assert (sp / "a" / "__init__.py").exists()
        assert (sp / "b" / "_ext.pyd").exists()
        assert (sp / "pip" / "__init__.py").read_text() == "pip"

    def test_vendored_path_wheel_used_end_to_end(self, tmp_path):
        prefix = tmp_path / "python"
        (prefix / "Lib" / "site-packages").mkdir(parents=True)
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        vendored = wheels_dir / "a-1.0-py3-none-any.whl"
        _wheel_zip(vendored, {"a/__init__.py": "vendored"})
        pkg = _pkg(
            "a",
            [
                LockedWheel(
                    name=vendored.name,
                    path="wheels/a-1.0-py3-none-any.whl",
                    sha256=sha256_file(vendored),
                )
            ],
        )
        wheels_stage.stage_wheels(
            (pkg,),
            "amd64",
            prefix,
            project_root=tmp_path,
            cache=ArtifactCache(tmp_path / "cache"),
        )
        assert (
            prefix / "Lib" / "site-packages" / "a" / "__init__.py"
        ).read_text() == "vendored"


class TestFetch:
    def test_download_error_wrapped(self, tmp_path):
        wheel = LockedWheel(name="a.whl", path="/etc/passwd", sha256="0" * 64)
        with pytest.raises(WindowsBundleError):
            wheels_stage._fetch(
                wheel, tmp_path, ArtifactCache(tmp_path / "cache"), False
            )
