"""Bundle assembly + arch resolution (staging/signing faked)."""

from __future__ import annotations

import plistlib

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.macos import AppBundleError, bundle

_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.2.0'\nrequires-python='>=3.14'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\n"
    "archs=['arm64','x86_64']\n"
    "[tool.kivy.macos.python]\nversion='3.14.5'\n"
)


def _config():
    return load_config_from_text(_PYPROJECT, require_ios=False, require_macos=True)


def _lock(archs=("arm64", "x86_64"), native_binaries=()):
    return WheelRuntimeLock(
        platform="macos",
        requires_python=">=3.14",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.14.5",
            artifacts=tuple(
                RuntimeArtifact(arch=a, url=f"https://e/{a}", sha256="x") for a in archs
            ),
        ),
        archs=archs,
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256="0" * 64,
        tool_kivyforge_schema_version=1,
        native_binaries=native_binaries,
    )


class TestResolveAssemblyArchs:
    def test_none_returns_full_locked_set(self):
        assert bundle.resolve_assembly_archs(("arm64", "x86_64"), None) == (
            "arm64",
            "x86_64",
        )

    def test_single_arch_subset(self):
        assert bundle.resolve_assembly_archs(("arm64", "x86_64"), "arm64") == ("arm64",)

    def test_universal2_requires_two(self):
        with pytest.raises(AppBundleError, match="needs a lock covering both"):
            bundle.resolve_assembly_archs(("arm64",), "universal2")

    def test_universal2_ok_with_two(self):
        assert bundle.resolve_assembly_archs(("arm64", "x86_64"), "universal2") == (
            "arm64",
            "x86_64",
        )

    def test_arch_not_in_lock_errors(self):
        with pytest.raises(AppBundleError, match="not in the lock"):
            bundle.resolve_assembly_archs(("arm64",), "x86_64")


@pytest.fixture
def faked(monkeypatch):
    """Replace the heavy staging/signing steps with recorders."""
    calls = {
        "runtime": [],
        "wheels": [],
        "native": [],
        "sign": [],
        "icns": [],
        "launcher": None,
        "order": [],
    }

    def fake_runtime(runtime, archs, home, **k):
        home.mkdir(parents=True, exist_ok=True)
        (home / "bin").mkdir()
        (home / "bin" / "python3").write_text("x")
        calls["runtime"].append(tuple(archs))
        calls["order"].append("runtime")
        return home

    def fake_wheels(packages, archs, lib, **k):
        lib.mkdir(parents=True, exist_ok=True)
        calls["wheels"].append(tuple(archs))
        calls["order"].append("wheels")

    def fake_native(lock, resources, **k):
        calls["native"].append(tuple(b.name for b in lock.native_binaries))
        calls["order"].append("native")

    def fake_launcher(dest, *, entry_point, archs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\xcf\xfa\xed\xfe")  # Mach-O magic placeholder
        calls["launcher"] = (entry_point, tuple(archs))

    monkeypatch.setattr(bundle, "stage_runtime", fake_runtime)
    monkeypatch.setattr(bundle, "stage_wheels", fake_wheels)
    monkeypatch.setattr(bundle, "stage_native_binaries", fake_native)
    monkeypatch.setattr(bundle, "build_launcher", fake_launcher)
    monkeypatch.setattr(
        bundle, "sign_bundle_adhoc", lambda app: calls["sign"].append(app) or 1
    )
    monkeypatch.setattr(
        bundle, "generate_icns", lambda src, dst: calls["icns"].append((src, dst))
    )
    return calls


def _project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    return tmp_path


class TestBuildAppBundle:
    def test_assembles_layout_and_plist(self, tmp_path, faked):
        root = _project(tmp_path)
        app = bundle.build_app_bundle(
            _config(), _lock(), root, staging_dir=tmp_path / "out", echo=lambda *a: None
        )
        assert app.name == "My App.app"
        contents = app / "Contents"
        assert (contents / "MacOS" / "myapp").exists()
        assert (contents / "Resources" / "app" / "main.py").exists()
        assert (contents / "Resources" / "python" / "bin" / "python3").exists()
        plist = plistlib.loads((contents / "Info.plist").read_bytes())
        assert plist["CFBundleIdentifier"] == "org.example.myapp"
        assert faked["sign"] == [app]

    def test_arch_subset_passed_to_stagers(self, tmp_path, faked):
        root = _project(tmp_path)
        bundle.build_app_bundle(
            _config(),
            _lock(),
            root,
            arch="arm64",
            staging_dir=tmp_path / "out",
            echo=lambda *a: None,
        )
        assert faked["runtime"] == [("arm64",)]
        assert faked["wheels"] == [("arm64",)]

    def test_native_binaries_staged_after_wheels(self, tmp_path, faked):
        from kivyforge.lock.wheelruntime.model import LockedNativeBinary

        root = _project(tmp_path)
        lock = _lock(
            native_binaries=(LockedNativeBinary("roll", "1.0", "a" * 64, path="p"),)
        )
        bundle.build_app_bundle(
            _config(), lock, root, staging_dir=tmp_path / "out", echo=lambda *a: None
        )
        assert faked["native"] == [("roll",)]
        assert faked["order"].index("native") > faked["order"].index("wheels")

    def test_native_binaries_skipped_when_empty(self, tmp_path, faked):
        root = _project(tmp_path)
        bundle.build_app_bundle(
            _config(), _lock(), root, staging_dir=tmp_path / "out", echo=lambda *a: None
        )
        assert faked["native"] == []

    def test_no_sign(self, tmp_path, faked):
        root = _project(tmp_path)
        bundle.build_app_bundle(
            _config(),
            _lock(),
            root,
            sign=False,
            staging_dir=tmp_path / "out",
            echo=lambda *a: None,
        )
        assert faked["sign"] == []

    def test_missing_entry_point_fails(self, tmp_path, faked):
        (tmp_path / "src").mkdir()  # no main.py
        with pytest.raises(AppBundleError, match="entry point main.py not found"):
            bundle.build_app_bundle(
                _config(),
                _lock(),
                tmp_path,
                staging_dir=tmp_path / "o",
                echo=lambda *a: None,
            )

    def test_missing_app_dir_fails(self, tmp_path, faked):
        with pytest.raises(AppBundleError, match="not\\s+a directory"):
            bundle.build_app_bundle(
                _config(),
                _lock(),
                tmp_path,
                staging_dir=tmp_path / "o",
                echo=lambda *a: None,
            )

    def test_icon_generated_when_configured(self, tmp_path, faked):
        root = _project(tmp_path)
        (root / "assets").mkdir()
        (root / "assets" / "icon.png").write_bytes(b"\x89PNG")
        cfg = load_config_from_text(
            _PYPROJECT.replace(
                "[tool.kivy.macos.python]",
                "[tool.kivy.macos.icons]\nsource='assets/icon.png'\n"
                "[tool.kivy.macos.python]",
            ),
            require_ios=False,
            require_macos=True,
        )
        app = bundle.build_app_bundle(
            cfg, _lock(), root, staging_dir=tmp_path / "out", echo=lambda *a: None
        )
        assert faked["icns"]
        plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        assert plist["CFBundleIconFile"] == "myapp.icns"
