"""Hermetic build->package pipeline per desktop platform.

The per-platform ``test_cli_*`` suites drive the ``build``/``package`` verbs from
disk but stub the *whole* bundler, and the ``test_bundle`` suites exercise the
real bundler but bypass the verb layer. Neither connects the two, so verb/bundler
drift (e.g. a dist folder named from the wrong field) slips through both.

These tests wire the real chain together: a real ``pyproject.toml`` + on-disk
lock, driven through the CLI verbs into the *real* bundler orchestration, with
only the network/host-tool leaves faked (runtime + wheel staging, the compiled
launcher, signing, appimagetool). They assert the actually-assembled artifact
shape — the layout, the rendered manifests, and the packaged distributable's
name/location — so the modules are proven to fit together end to end.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.build import build
from kivyforge.cli.package import package
from kivyforge.lock.reader import compute_pyproject_sha256
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)


@pytest.fixture
def runner():
    return CliRunner()


def _write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text, encoding="utf-8")


def _write_app_sources(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# macOS                                                                       #
# --------------------------------------------------------------------------- #

_MACOS_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.0.0'\nrequires-python='>=3.14'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\n"
    "archs=['arm64','x86_64']\n"
    "[tool.kivy.macos.python]\nversion='3.14.5'\n"
)


def _macos_project(root: Path) -> None:
    _write(root, "pyproject.toml", _MACOS_PYPROJECT)
    _write_app_sources(root)
    lock = WheelRuntimeLock(
        platform="macos",
        requires_python=">=3.14",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.14.5",
            artifacts=(
                RuntimeArtifact(arch="arm64", url="https://e/a", sha256="x"),
                RuntimeArtifact(arch="x86_64", url="https://e/i", sha256="y"),
            ),
        ),
        archs=("arm64", "x86_64"),
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256=compute_pyproject_sha256(_MACOS_PYPROJECT),
        tool_kivyforge_schema_version=1,
    )
    from kivyforge.platforms.macos.lock import dumps

    _write(root, "pylock.macos.toml", dumps(lock))


@pytest.fixture
def macos_leaves(monkeypatch):
    """Fake only the network/host-tool leaves; the bundler orchestration is real."""
    from kivyforge.platforms.macos import bundle as macos_bundle
    from kivyforge.platforms.macos import cli as macos_cli

    def fake_runtime(runtime, archs, home, **k):
        (home / "bin").mkdir(parents=True)
        (home / "bin" / "python3").write_text("py")
        return home

    def fake_wheels(packages, archs, lib, **k):
        lib.mkdir(parents=True)

    def fake_launcher(dest, *, entry_point, archs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\xcf\xfa\xed\xfe")

    monkeypatch.setattr(macos_bundle, "stage_runtime", fake_runtime)
    monkeypatch.setattr(macos_bundle, "stage_wheels", fake_wheels)
    monkeypatch.setattr(macos_bundle, "build_launcher", fake_launcher)
    monkeypatch.setattr(macos_bundle, "sign_bundle_adhoc", lambda app: 1)
    monkeypatch.setattr(macos_cli, "_require_macos_host", lambda: None)


class TestMacosPipeline:
    def test_build_then_package(self, runner, tmp_path, macos_leaves):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            _macos_project(root)

            r = runner.invoke(build, ["-p", "macos"])
            assert r.exit_code == 0, r.output

            app = root / "build" / "macos" / "My App.app"
            contents = app / "Contents"
            assert (contents / "MacOS" / "myapp").exists()
            assert (contents / "Resources" / "app" / "main.py").exists()
            assert (contents / "Resources" / "python" / "bin" / "python3").exists()
            # The real Info.plist renderer ran through the verb -> bundler chain.
            plist = plistlib.loads((contents / "Info.plist").read_bytes())
            assert plist["CFBundleIdentifier"] == "org.example.myapp"
            assert plist["CFBundleExecutable"] == "myapp"

            r = runner.invoke(package, ["-p", "macos"])
            assert r.exit_code == 0, r.output
            assert "ad-hoc signed" in r.output
            assert app.exists()


# --------------------------------------------------------------------------- #
# Linux                                                                       #
# --------------------------------------------------------------------------- #

_LINUX_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.0.0'\nrequires-python='>=3.15'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
    "[tool.kivy.linux.python]\nversion='3.15.0'\n"
)


def _linux_project(root: Path) -> None:
    _write(root, "pyproject.toml", _LINUX_PYPROJECT)
    _write_app_sources(root)
    lock = WheelRuntimeLock(
        platform="linux",
        requires_python=">=3.15",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.15.0",
            artifacts=(RuntimeArtifact(arch="x86_64", url="https://e/a", sha256="x"),),
            floor="2.17",
        ),
        archs=("x86_64",),
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256=compute_pyproject_sha256(_LINUX_PYPROJECT),
        tool_kivyforge_schema_version=1,
    )
    from kivyforge.platforms.linux.lock import dumps

    _write(root, "pylock.linux.toml", dumps(lock))


@pytest.fixture
def linux_leaves(monkeypatch):
    """Fake network staging + appimagetool; AppRun/.desktop rendering stays real."""
    from kivyforge.platforms.linux import bundle as linux_bundle
    from kivyforge.platforms.linux import cli as linux_cli

    def fake_runtime(runtime, arch, home, **k):
        (home / "bin").mkdir(parents=True)
        (home / "bin" / "python3").write_text("py")
        return home

    def fake_wheels(packages, arch, lib, **k):
        lib.mkdir(parents=True)

    def fake_appimage(appdir, output, arch, **k):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("APPIMAGE")
        return output

    monkeypatch.setattr(linux_bundle, "stage_runtime", fake_runtime)
    monkeypatch.setattr(linux_bundle, "stage_wheels", fake_wheels)
    monkeypatch.setattr(linux_bundle, "stage_icons", lambda *a, **k: None)
    monkeypatch.setattr(linux_cli, "build_appimage", fake_appimage)
    monkeypatch.setattr(linux_cli, "_require_linux_host", lambda: None)


class TestLinuxPipeline:
    def test_build_then_package(self, runner, tmp_path, linux_leaves):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            _linux_project(root)

            r = runner.invoke(build, ["-p", "linux"])
            assert r.exit_code == 0, r.output

            appdir = root / "build" / "linux" / "My App.AppDir"
            assert (appdir / "usr" / "app" / "main.py").exists()
            assert (appdir / "usr" / "python" / "bin" / "python3").exists()
            # The real AppRun + .desktop renderers ran through the chain.
            apprun = appdir / "AppRun"
            assert apprun.is_file()
            assert (appdir / "org.example.myapp.desktop").is_file()

            r = runner.invoke(package, ["-p", "linux"])
            assert r.exit_code == 0, r.output
            # dist artifact named + placed by the real package flow.
            out = root / "dist" / "linux" / "myapp-1.0.0-x86_64.AppImage"
            assert out.exists()


# --------------------------------------------------------------------------- #
# Windows                                                                     #
# --------------------------------------------------------------------------- #

_WINDOWS_PYPROJECT = (
    "[project]\nname='demo-app'\nversion='1.2.3'\nrequires-python='>=3.13'\n"
    "dependencies=[]\n"
    'authors=[{ name = "Acme Corp" }]\n'
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.windows]\nschema_version=1\napp_id='Acme.MyApp'\n"
    "[tool.kivy.windows.python]\nversion='3.13'\n"
)


def _windows_project(root: Path) -> None:
    _write(root, "pyproject.toml", _WINDOWS_PYPROJECT)
    _write_app_sources(root)
    lock = WheelRuntimeLock(
        platform="windows",
        requires_python=">=3.13",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.13.14",
            artifacts=(
                RuntimeArtifact(arch="amd64", url="https://e/x.tar.gz", sha256="x"),
            ),
        ),
        archs=("amd64",),
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256=compute_pyproject_sha256(_WINDOWS_PYPROJECT),
        tool_kivyforge_schema_version=1,
    )
    from kivyforge.platforms.windows.lock import dumps

    _write(root, "pylock.windows.toml", dumps(lock))


@pytest.fixture
def windows_leaves(monkeypatch, tmp_path):
    """Fake network staging + rcedit; launcher copy + bootstrap + dist copy real."""
    from kivyforge.platforms.windows import bundle as win_bundle
    from kivyforge.platforms.windows import cli as win_cli
    from kivyforge.platforms.windows import launcher as win_launcher

    def fake_runtime(runtime, arch, home, **k):
        home.mkdir(parents=True, exist_ok=True)
        (home / "python.exe").write_bytes(b"MZ")
        return home

    def fake_wheels(packages, arch, prefix, **k):
        (prefix / "Lib").mkdir(parents=True, exist_ok=True)

    vendored = tmp_path / "vendored-launcher.exe"
    vendored.write_bytes(b"MZ-launcher")

    monkeypatch.setattr(win_bundle, "stage_runtime", fake_runtime)
    monkeypatch.setattr(win_bundle, "stage_wheels", fake_wheels)
    monkeypatch.setattr(win_launcher, "vendored_launcher", lambda: vendored)
    monkeypatch.setattr(win_launcher, "patch_resources", lambda exe, patch, **k: None)
    monkeypatch.setattr(win_cli, "_require_windows_host", lambda: None)


class TestWindowsPipeline:
    def test_build_then_package(self, runner, tmp_path, windows_leaves):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            _windows_project(root)

            r = runner.invoke(build, ["-p", "windows"])
            assert r.exit_code == 0, r.output

            onedir = root / "build" / "windows" / "My App"
            assert (onedir / "My App.exe").read_bytes() == b"MZ-launcher"
            assert (onedir / "_kivyforge_bootstrap.py").exists()
            assert (onedir / "app" / "main.py").exists()
            assert (onedir / "python" / "python.exe").exists()

            r = runner.invoke(package, ["-p", "windows"])
            assert r.exit_code == 0, r.output
            # The dist folder is named from the sanitized *display_name*, not the
            # raw project.name — a regression guard for the verb/bundler contract.
            dest = root / "dist" / "windows" / "My App-1.2.3-amd64"
            assert (dest / "My App.exe").exists()
            assert (dest / "app" / "main.py").exists()
            assert "unsigned" in r.output
