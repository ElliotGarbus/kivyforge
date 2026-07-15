"""Windows onedir assembly orchestration (hermetic; stages are faked)."""

from __future__ import annotations

import pytest

from kivyforge.config import load_config
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.windows import WindowsBundleError, bundle
from kivyforge.platforms.windows import launcher as L

_PYPROJECT = """\
[project]
name = "demo-app"
version = "1.2.3"

[tool.kivy]
app_dir = "src"
entry_point = "main"
display_name = "My App"

[tool.kivy.windows]
schema_version = 1
app_id = "Acme.MyApp"

[tool.kivy.windows.python]
version = "3.13"
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("# entry\n", encoding="utf-8")
    config = load_config(
        tmp_path / "pyproject.toml", require_ios=False, require_windows=True
    )
    return tmp_path, config


def _lock(archs=("amd64",), packages=(), native=()):
    return WheelRuntimeLock(
        platform="windows",
        requires_python=">=3.13",
        packages=tuple(packages),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.13.14",
            artifacts=(
                RuntimeArtifact(arch="amd64", url="https://e/x.tar.gz", sha256="x"),
            ),
            floor=None,
        ),
        archs=archs,
        kivyforge_version="0.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256="0" * 64,
        tool_kivyforge_schema_version=1,
        native_binaries=native,
    )


@pytest.fixture
def fake_stages(monkeypatch, tmp_path):
    """Fake the network stages: materialize a plausible python\\ tree + launcher."""

    def _fake_runtime(runtime, arch, home, **kw):
        (home / "Lib" / "site-packages").mkdir(parents=True)
        (home / "python.exe").write_bytes(b"MZ")
        return home

    def _fake_wheels(packages, arch, prefix, **kw):
        # Simulate a kivy_deps payload landing at the prefix root.
        share = prefix / "share" / "sdl2" / "bin"
        share.mkdir(parents=True, exist_ok=True)
        (share / "SDL2.dll").write_bytes(b"DLL")

    monkeypatch.setattr(bundle, "stage_runtime", _fake_runtime)
    monkeypatch.setattr(bundle, "stage_wheels", _fake_wheels)

    vendored = tmp_path / "vendored-launcher.exe"
    vendored.write_bytes(b"MZ-launcher")
    monkeypatch.setattr(L, "vendored_launcher", lambda: vendored)
    patches = []
    monkeypatch.setattr(
        L, "patch_resources", lambda exe, patch, **kw: patches.append((exe, patch))
    )
    return patches


class TestBuildOnedir:
    def test_full_layout(self, project, fake_stages):
        root, config = project
        result = bundle.build_onedir(config, _lock(), root, echo=lambda *a, **k: None)
        assert result == root / "build" / "windows" / "My App"
        assert (result / "python" / "python.exe").exists()
        assert (result / "python" / "share" / "sdl2" / "bin" / "SDL2.dll").exists()
        assert (result / "app" / "main.py").exists()
        assert (result / "_kivyforge_bootstrap.py").exists()
        assert (result / "My App.exe").read_bytes() == b"MZ-launcher"

    def test_resource_patch_from_metadata(self, project, fake_stages):
        root, config = project
        bundle.build_onedir(config, _lock(), root, echo=lambda *a, **k: None)
        assert len(fake_stages) == 1
        _exe, patch = fake_stages[0]
        assert patch.product_name == "My App"
        assert patch.product_version_string == "1.2.3"

    def test_no_bin_dir_when_no_native(self, project, fake_stages):
        root, config = project
        result = bundle.build_onedir(config, _lock(), root, echo=lambda *a, **k: None)
        assert not (result / "bin").exists()

    def test_native_binaries_staged(self, project, fake_stages, monkeypatch):
        root, config = project
        staged = {}

        def _fake_native(lock, work, arch, **kw):
            (work / "bin").mkdir(exist_ok=True)
            (work / "bin" / "helper.exe").write_bytes(b"MZ")
            staged["called"] = True

        monkeypatch.setattr(bundle, "stage_native_binaries", _fake_native)
        from kivyforge.lock.wheelruntime.model import LockedNativeBinary

        native = (
            LockedNativeBinary(
                name="helper", version="1.0", url="https://e/h.exe", sha256="s"
            ),
        )
        result = bundle.build_onedir(
            config, _lock(native=native), root, echo=lambda *a, **k: None
        )
        assert staged.get("called")
        assert (result / "bin" / "helper.exe").exists()

    def test_atomic_swap_preserves_previous_on_failure(
        self, project, fake_stages, monkeypatch
    ):
        root, config = project
        # First successful build.
        result = bundle.build_onedir(config, _lock(), root, echo=lambda *a, **k: None)
        marker = result / "python" / "python.exe"
        assert marker.exists()

        # Second build fails mid-assembly; the previous bundle must survive.
        def _boom(*a, **k):
            raise WindowsBundleError("boom")

        monkeypatch.setattr(bundle, "stage_wheels", _boom)
        with pytest.raises(WindowsBundleError, match="boom"):
            bundle.build_onedir(config, _lock(), root, echo=lambda *a, **k: None)
        assert marker.exists()  # untouched
        # No leftover temp dirs.
        assert not list((root / "build" / "windows").glob(".My App.tmp-*"))

    def test_missing_entry_point_fails(self, project, fake_stages):
        root, config = project
        (root / "src" / "main.py").unlink()
        with pytest.raises(WindowsBundleError, match="entry point main.py not found"):
            bundle.build_onedir(config, _lock(), root, echo=lambda *a, **k: None)


class TestResolveAssemblyArch:
    def test_default_first(self):
        assert bundle.resolve_assembly_arch(("amd64",), None) == "amd64"

    def test_explicit_uncovered_fails(self):
        with pytest.raises(WindowsBundleError, match="not in the lock"):
            bundle.resolve_assembly_arch(("amd64",), "arm64")

    def test_empty_lock_fails(self):
        with pytest.raises(WindowsBundleError, match="covers no architectures"):
            bundle.resolve_assembly_arch((), None)
