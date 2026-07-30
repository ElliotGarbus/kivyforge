"""AppDir assembly + arch resolution (stages faked)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.linux import AppDirError, bundle

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

    def fake_apprun(dest, *, entry_point, app_id, has_native_binaries=False):
        dest.write_text("#!/bin/sh\n")
        dest.chmod(0o755)
        calls["apprun"] = (entry_point, app_id)

    def fake_desktop(config, dest):
        dest.write_text("[Desktop Entry]\n")
        calls["desktop"] = dest

    def fake_validate_desktop(dest):
        calls["validated"] = dest

    monkeypatch.setattr(bundle, "stage_runtime", fake_runtime)
    monkeypatch.setattr(bundle, "stage_wheels", fake_wheels)
    monkeypatch.setattr(bundle, "stage_icons", fake_icons)
    monkeypatch.setattr(bundle, "build_apprun", fake_apprun)
    monkeypatch.setattr(bundle, "write_desktop_entry", fake_desktop)
    monkeypatch.setattr(bundle, "validate_desktop_file", fake_validate_desktop)
    return calls


def _project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    return tmp_path


class TestByteCompileResolution:
    """``byte_compile``/``strip_source`` (linux-spec §build_settings).

    ``select_compiler`` is stubbed here (it has its own tests in
    tests/bundle/test_pycompile.py); the interesting behavior at this layer is
    the tri-state resolution and the degrade-vs-error split.
    """

    def _config(self, extra: str = ""):
        text = _PYPROJECT.replace(
            "[tool.kivy.linux.python]", extra + "\n[tool.kivy.linux.python]"
        )
        return _config(text)

    def _resolve(self, config, *, release=True):
        return bundle._resolve_byte_compile(
            config,
            staged_interpreter=Path("unused"),
            target_arch="x86_64",
            python_version="3.15.0",
            release=release,
        )

    def _select(self, monkeypatch, result):
        monkeypatch.setattr(bundle, "select_compiler", lambda **kw: result)

    def test_release_default_compiles_and_strips(self, monkeypatch):
        self._select(monkeypatch, ("staged-python",))
        assert self._resolve(self._config()) == (("staged-python",), True)

    def test_dev_build_keeps_readable_sources(self, monkeypatch):
        self._select(monkeypatch, ("staged-python",))
        assert self._resolve(self._config(), release=False) == (None, False)

    def test_false_never_compiles(self, monkeypatch):
        self._select(monkeypatch, ("staged-python",))
        config = self._config(
            "[tool.kivy.linux.build_settings]\nbyte_compile = false\n"
        )
        assert self._resolve(config) == (None, False)

    def test_strip_source_is_ignored_without_byte_compile(self, monkeypatch):
        self._select(monkeypatch, ("staged-python",))
        config = self._config(
            "[tool.kivy.linux.build_settings]\n"
            "byte_compile = false\nstrip_source = true\n"
        )
        assert self._resolve(config) == (None, False)

    def test_true_compiles_for_dev_build_too(self, monkeypatch):
        self._select(monkeypatch, ("staged-python",))
        config = self._config(
            "[tool.kivy.linux.build_settings]\n"
            "byte_compile = true\nstrip_source = false\n"
        )
        assert self._resolve(config, release=False) == (("staged-python",), False)

    def test_default_degrades_when_no_compiler_found(self, monkeypatch, capsys):
        self._select(monkeypatch, None)
        assert self._resolve(self._config()) == (None, False)
        assert "not byte-compiling" in capsys.readouterr().out

    def test_explicit_true_fails_when_no_compiler_found(self, monkeypatch):
        self._select(monkeypatch, None)
        config = self._config("[tool.kivy.linux.build_settings]\nbyte_compile = true\n")
        with pytest.raises(AppDirError, match="byte_compile = true"):
            self._resolve(config)

    def test_the_choice_reaches_the_bundle(self, tmp_path, faked, monkeypatch):
        root = _project(tmp_path)
        monkeypatch.setattr(bundle, "select_compiler", lambda **kw: ())
        calls = []
        monkeypatch.setattr(
            bundle, "byte_compile", lambda trees, **kw: calls.append((trees, kw))
        )
        bundle.build_appdir(
            _config(),
            _lock(),
            root,
            staging_dir=tmp_path / "out",
            release=True,
            echo=lambda *a: None,
        )
        assert calls
        trees, kw = calls[0]
        assert [t.parts[-2:] for t in trees] == [("usr", "app"), ("usr", "lib")]
        assert kw["strip_source"] is True


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
        # The generated .desktop is validated during assembly (in the temp tree,
        # before the atomic swap-in).
        assert faked["validated"].name == "org.example.myapp.desktop"

    def test_dotted_entry_point_maps_to_nested_source(self, tmp_path, faked):
        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "start.py").write_text("print('hi')")
        text = _PYPROJECT.replace("entry_point='main'", "entry_point='pkg.start'")
        appdir = bundle.build_appdir(
            _config(text),
            _lock(),
            tmp_path,
            staging_dir=tmp_path / "out",
            echo=lambda *a: None,
        )
        assert (appdir / "usr" / "app" / "pkg" / "start.py").exists()
        assert faked["apprun"] == ("pkg.start", "org.example.myapp")

    def test_missing_dotted_entry_point_fails(self, tmp_path, faked):
        (tmp_path / "src").mkdir()  # no pkg/start.py
        text = _PYPROJECT.replace("entry_point='main'", "entry_point='pkg.start'")
        with pytest.raises(AppDirError, match="entry point pkg/start.py not found"):
            bundle.build_appdir(
                _config(text),
                _lock(),
                tmp_path,
                staging_dir=tmp_path / "o",
                echo=lambda *a: None,
            )

    def test_missing_entry_point_fails(self, tmp_path, faked):
        (tmp_path / "src").mkdir()  # no main.py
        with pytest.raises(AppDirError, match="entry point main.py not found"):
            bundle.build_appdir(
                _config(),
                _lock(),
                tmp_path,
                staging_dir=tmp_path / "o",
                echo=lambda *a: None,
            )

    def test_missing_app_dir_fails(self, tmp_path, faked):
        with pytest.raises(AppDirError, match="not\\s+a directory"):
            bundle.build_appdir(
                _config(),
                _lock(),
                tmp_path,
                staging_dir=tmp_path / "o",
                echo=lambda *a: None,
            )

    def test_failed_build_preserves_previous_appdir(self, tmp_path, faked, monkeypatch):
        root = _project(tmp_path)
        out = tmp_path / "out"
        appdir = bundle.build_appdir(
            _config(), _lock(), root, staging_dir=out, echo=lambda *a: None
        )
        marker = appdir / "usr" / "app" / "main.py"
        assert marker.exists()

        # A build that fails mid-assembly must leave the previous, working AppDir
        # intact and must not litter temp staging trees.
        def boom(*a, **k):
            raise AppDirError("simulated fetch failure")

        monkeypatch.setattr(bundle, "stage_runtime", boom)
        with pytest.raises(AppDirError, match="simulated fetch failure"):
            bundle.build_appdir(
                _config(), _lock(), root, staging_dir=out, echo=lambda *a: None
            )

        assert appdir.exists()
        assert marker.exists()
        assert not list(out.glob(f".{appdir.name}.tmp-*"))
