"""AppDir assembly + arch resolution (stages faked)."""

from __future__ import annotations

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.linux import AppDirError, bundle
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)

_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.2.0'\nrequires-python='>=3.15'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
    "[tool.kivy.linux.python]\nversion='3.15.0'\n"
)


def _config(text=_PYPROJECT):
    return load_config_from_text(text, require_ios=False, require_linux=True)


def _lock(archs=("x86_64",)):
    return WheelRuntimeLock(
        platform="linux",
        requires_python=">=3.15",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.15.0",
            artifacts=tuple(
                RuntimeArtifact(arch=a, url=f"https://e/{a}", sha256="x") for a in archs
            ),
            floor="2.17",
        ),
        archs=archs,
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256="0" * 64,
        tool_kivyforge_schema_version=1,
    )


class TestResolveAssemblyArch:
    def test_none_returns_locked(self):
        assert bundle.resolve_assembly_arch(("x86_64",), None) == "x86_64"

    def test_explicit_match(self):
        assert bundle.resolve_assembly_arch(("x86_64",), "x86_64") == "x86_64"

    def test_arch_not_in_lock_errors(self):
        with pytest.raises(AppDirError, match="not in the lock"):
            bundle.resolve_assembly_arch(("x86_64",), "aarch64")

    def test_empty_lock_errors(self):
        with pytest.raises(AppDirError, match="covers no architectures"):
            bundle.resolve_assembly_arch((), None)


@pytest.fixture
def faked(monkeypatch):
    """Replace the heavy stages with recorders."""
    calls = {"runtime": [], "wheels": [], "icons": [], "apprun": None, "desktop": None}

    def fake_runtime(runtime, arch, home, **k):
        home.mkdir(parents=True, exist_ok=True)
        (home / "bin").mkdir()
        (home / "bin" / "python3").write_text("x")
        calls["runtime"].append(arch)
        return home

    def fake_wheels(packages, arch, lib, **k):
        lib.mkdir(parents=True, exist_ok=True)
        calls["wheels"].append(arch)

    def fake_icons(config, project_root, appdir):
        calls["icons"].append(appdir)
        return False

    def fake_apprun(dest, *, entry_point, app_id):
        dest.write_text("#!/bin/sh\n")
        dest.chmod(0o755)
        calls["apprun"] = (entry_point, app_id)

    def fake_desktop(config, dest):
        dest.write_text("[Desktop Entry]\n")
        calls["desktop"] = dest

    monkeypatch.setattr(bundle, "stage_runtime", fake_runtime)
    monkeypatch.setattr(bundle, "stage_wheels", fake_wheels)
    monkeypatch.setattr(bundle, "stage_icons", fake_icons)
    monkeypatch.setattr(bundle, "build_apprun", fake_apprun)
    monkeypatch.setattr(bundle, "write_desktop_entry", fake_desktop)
    return calls


def _project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    return tmp_path


class TestBuildAppdir:
    def test_assembles_layout(self, tmp_path, faked):
        root = _project(tmp_path)
        appdir = bundle.build_appdir(
            _config(), _lock(), root, staging_dir=tmp_path / "out", echo=lambda *a: None
        )
        assert appdir.name == "My App.AppDir"
        assert (appdir / "AppRun").exists()
        assert (appdir / "org.example.myapp.desktop").exists()
        assert (appdir / "usr" / "app" / "main.py").exists()
        assert (appdir / "usr" / "python" / "bin" / "python3").exists()
        assert faked["runtime"] == ["x86_64"]
        assert faked["wheels"] == ["x86_64"]
        assert faked["apprun"] == ("main", "org.example.myapp")

    def test_missing_entry_point_fails(self, tmp_path, faked):
        (tmp_path / "src").mkdir()  # no main.py
        with pytest.raises(AppDirError, match="entry point main.py not found"):
            bundle.build_appdir(
                _config(), _lock(), tmp_path, staging_dir=tmp_path / "o",
                echo=lambda *a: None,
            )

    def test_missing_app_dir_fails(self, tmp_path, faked):
        with pytest.raises(AppDirError, match="not\\s+a directory"):
            bundle.build_appdir(
                _config(), _lock(), tmp_path, staging_dir=tmp_path / "o",
                echo=lambda *a: None,
            )
