"""Bundle assembly + arch resolution (staging/signing faked)."""

from __future__ import annotations

import plistlib
from pathlib import Path

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
    "archs=['arm64']\n"
    "[tool.kivy.macos.python]\nversion='3.14.5'\n"
)


def _config():
    return load_config_from_text(_PYPROJECT, require_ios=False, require_macos=True)


def _lock(archs=("arm64",), native_binaries=()):
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


class TestResolveAssemblyArch:
    def test_none_returns_the_locked_arch(self):
        assert bundle.resolve_assembly_arch(("arm64",), None) == "arm64"

    def test_explicit_locked_arch(self):
        assert bundle.resolve_assembly_arch(("arm64",), "arm64") == "arm64"

    def test_empty_lock_errors(self):
        with pytest.raises(AppBundleError, match="covers no architectures"):
            bundle.resolve_assembly_arch((), None)

    def test_arch_not_in_lock_errors(self):
        with pytest.raises(AppBundleError, match="not in the lock"):
            bundle.resolve_assembly_arch(("arm64",), "x86_64")


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

    def fake_runtime(runtime, arch, home, **k):
        home.mkdir(parents=True, exist_ok=True)
        (home / "bin").mkdir()
        (home / "bin" / "python3").write_text("x")
        calls["runtime"].append(arch)
        calls["order"].append("runtime")
        return home

    def fake_wheels(packages, arch, lib, **k):
        lib.mkdir(parents=True, exist_ok=True)
        calls["wheels"].append(arch)
        calls["order"].append("wheels")

    def fake_native(lock, resources, **k):
        calls["native"].append(tuple(b.name for b in lock.native_binaries))
        calls["order"].append("native")

    def fake_launcher(dest, *, entry_point, arch):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\xcf\xfa\xed\xfe")  # Mach-O magic placeholder
        calls["launcher"] = (entry_point, arch)

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


class TestByteCompileResolution:
    """``byte_compile``/``strip_source`` (macos-spec §build_settings).

    ``select_compiler`` is stubbed here (it has its own tests in
    tests/bundle/test_pycompile.py); the interesting behavior at this layer is
    the tri-state resolution, the degrade-vs-error split, and — the
    macOS-specific wrinkle — that it runs before ad-hoc signing.
    """

    def _config(self, extra: str = ""):
        text = _PYPROJECT.replace(
            "[tool.kivy.macos.python]", extra + "\n[tool.kivy.macos.python]"
        )
        return load_config_from_text(text, require_ios=False, require_macos=True)

    def _resolve(self, config, *, release=True):
        return bundle._resolve_byte_compile(
            config,
            staged_interpreter=Path("unused"),
            target_arch="arm64",
            python_version="3.14.5",
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
            "[tool.kivy.macos.build_settings]\nbyte_compile = false\n"
        )
        assert self._resolve(config) == (None, False)

    def test_strip_source_is_ignored_without_byte_compile(self, monkeypatch):
        self._select(monkeypatch, ("staged-python",))
        config = self._config(
            "[tool.kivy.macos.build_settings]\n"
            "byte_compile = false\nstrip_source = true\n"
        )
        assert self._resolve(config) == (None, False)

    def test_true_compiles_for_dev_build_too(self, monkeypatch):
        self._select(monkeypatch, ("staged-python",))
        config = self._config(
            "[tool.kivy.macos.build_settings]\n"
            "byte_compile = true\nstrip_source = false\n"
        )
        assert self._resolve(config, release=False) == (("staged-python",), False)

    def test_default_degrades_when_no_compiler_found(self, monkeypatch, capsys):
        self._select(monkeypatch, None)
        assert self._resolve(self._config()) == (None, False)
        out = capsys.readouterr().out
        assert "not byte-compiling" in out
        # The notice must say how to fix it, not just what happened.
        assert "Fix: install a final CPython" in out

    def test_explicit_true_fails_when_no_compiler_found(self, monkeypatch):
        self._select(monkeypatch, None)
        config = self._config("[tool.kivy.macos.build_settings]\nbyte_compile = true\n")
        with pytest.raises(AppBundleError, match="byte_compile = true"):
            self._resolve(config)

    def test_the_choice_reaches_the_bundle_before_signing(
        self, tmp_path, faked, monkeypatch
    ):
        root = _project(tmp_path)
        monkeypatch.setattr(bundle, "select_compiler", lambda **kw: ())
        calls = []

        def fake_byte_compile(trees, **kw):
            faked["order"].append("byte_compile")
            calls.append((trees, kw))

        def fake_sign(app):
            faked["order"].append("sign")
            faked["sign"].append(app)
            return 1

        monkeypatch.setattr(bundle, "byte_compile", fake_byte_compile)
        monkeypatch.setattr(bundle, "sign_bundle_adhoc", fake_sign)

        bundle.build_app_bundle(
            _config(),
            _lock(),
            root,
            staging_dir=tmp_path / "out",
            release=True,
            echo=lambda *a: None,
        )
        assert calls
        trees, kw = calls[0]
        assert [t.parts[-1] for t in trees] == ["app", "lib"]
        assert kw["strip_source"] is True
        assert faked["order"].index("byte_compile") < faked["order"].index("sign")


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
        # The bundle is ad-hoc signed once (on the temp tree, before the swap).
        assert len(faked["sign"]) == 1

    def test_arch_passed_to_stagers(self, tmp_path, faked):
        root = _project(tmp_path)
        bundle.build_app_bundle(
            _config(),
            _lock(),
            root,
            arch="arm64",
            staging_dir=tmp_path / "out",
            echo=lambda *a: None,
        )
        assert faked["runtime"] == ["arm64"]
        assert faked["wheels"] == ["arm64"]

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

    def test_failed_build_preserves_previous_app(self, tmp_path, faked, monkeypatch):
        # A build that fails mid-assembly must leave the previous, working .app
        # untouched (write-in-place) and never leave a half-written temp behind.
        root = _project(tmp_path)
        out = tmp_path / "out"
        app = bundle.build_app_bundle(
            _config(), _lock(), root, staging_dir=out, echo=lambda *a: None
        )
        (app / "SENTINEL").write_text("prev")

        def boom(*a, **k):
            raise AppBundleError("simulated wheel-staging failure")

        monkeypatch.setattr(bundle, "stage_wheels", boom)
        with pytest.raises(AppBundleError, match="simulated wheel-staging failure"):
            bundle.build_app_bundle(
                _config(), _lock(), root, staging_dir=out, echo=lambda *a: None
            )

        assert (app / "SENTINEL").read_text() == "prev"
        # No leaked .<name>.app.tmp-* work tree beside the preserved bundle.
        assert [p.name for p in out.iterdir()] == ["My App.app"]

    def test_signing_failure_preserves_previous_app(self, tmp_path, faked, monkeypatch):
        # Signing runs on the temp tree before the swap, so a codesign failure
        # rolls back to the previous good .app rather than displacing it.
        root = _project(tmp_path)
        out = tmp_path / "out"
        app = bundle.build_app_bundle(
            _config(), _lock(), root, staging_dir=out, echo=lambda *a: None
        )
        (app / "SENTINEL").write_text("prev")

        def boom(_app):
            raise AppBundleError("simulated codesign failure")

        monkeypatch.setattr(bundle, "sign_bundle_adhoc", boom)
        with pytest.raises(AppBundleError, match="simulated codesign failure"):
            bundle.build_app_bundle(
                _config(), _lock(), root, staging_dir=out, echo=lambda *a: None
            )

        assert (app / "SENTINEL").read_text() == "prev"
        assert [p.name for p in out.iterdir()] == ["My App.app"]

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
