"""Deliberate, per-verb coverage that ``KIVYFORGE_PLATFORM`` (no ``-p``) drives
the same dispatch as ``--platform`` for every platform-aware verb.

Before this file, the env-var resolution *mechanism* was tested only once, in
isolation, at the shared ``resolve_target()`` layer (and only for iOS). Every
CLI-level test that omitted ``-p`` and landed on iOS did so *incidentally*,
courtesy of the autouse ``KIVYFORGE_PLATFORM=ios`` fixture in
``tests/conftest.py`` — no test ever set the env var to ``macos``/``linux`` and
checked that a verb dispatched there. This file closes that gap for all nine
platform-aware verbs: ``status``, ``build``, ``run``, ``package``, ``open``,
``doctor`` (shared ``Platform`` dispatch, verified by monkeypatching the
resolved backend's method), plus ``lock``, ``upgrade``, ``init`` (bespoke
per-verb dispatch, verified functionally with hermetic fakes).
"""

from __future__ import annotations

import textwrap
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli import init as init_mod
from kivyforge.cli import lock as lock_mod
from kivyforge.cli import upgrade as upgrade_mod
from kivyforge.cli.build import build
from kivyforge.cli.doctor import doctor
from kivyforge.cli.init import init
from kivyforge.cli.lock import lock
from kivyforge.cli.open_cmd import open_
from kivyforge.cli.package import package
from kivyforge.cli.run import run
from kivyforge.cli.status import status
from kivyforge.cli.upgrade import upgrade
from kivyforge.lock import compute_pyproject_sha256
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms import get_platform
from kivyforge.platforms.ios.lock import Lockfile, PythonXcframework

MINIMAL_PYPROJECT = '[project]\nname = "myapp"\nversion = "1.0.0"\n'

PYPROJECT_IOS = (
    textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.15"
        dependencies = ["kivy"]

        [tool.kivy]
        app_dir = "src"
        display_name = "My App"

        [tool.kivy.ios]
        schema_version = 1
        bundle_id = "org.example.myapp"
        deployment_target = "13.0"

        [tool.kivy.ios.python]
        version = "3.15.0"
        """
    ).strip()
    + "\n"
)

PYPROJECT_MACOS = (
    textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.13"
        dependencies = ["kivy"]

        [tool.kivy]
        app_dir = "src"
        display_name = "My App"

        [tool.kivy.macos]
        schema_version = 1
        bundle_id = "org.example.myapp"

        [tool.kivy.macos.python]
        version = "3.13.14"
        """
    ).strip()
    + "\n"
)

PYPROJECT_LINUX = (
    textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.13"
        dependencies = ["kivy"]

        [tool.kivy]
        app_dir = "src"
        display_name = "My App"

        [tool.kivy.linux]
        schema_version = 1
        app_id = "org.example.myapp"

        [tool.kivy.linux.python]
        version = "3.13.14"
        """
    ).strip()
    + "\n"
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project(tmp_path, runner):
    """A minimal project dir with no platform overlay — enough for every verb
    whose dispatch goes through a mocked ``Platform`` method, since the env-var
    resolution step (unlike the host-default step) never checks ``configured``.
    """
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        (Path(fs) / "pyproject.toml").write_text(MINIMAL_PYPROJECT)
        yield Path(fs)


class TestSharedDispatchViaEnvVar:
    """``status``/``build``/``run``/``package``/``open``/``doctor`` all resolve
    via the same ``Platform`` object and then call one of its methods. Patching
    that resolved backend's method (rather than the CLI's business logic)
    proves the *right* backend was selected purely from the env var.
    """

    @pytest.mark.parametrize("target_platform", ["ios", "macos", "linux"])
    def test_status(self, runner, project, monkeypatch, target_platform):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", target_platform)
        calls = []
        monkeypatch.setattr(
            get_platform(target_platform), "status", lambda root: calls.append(root)
        )
        result = runner.invoke(status, [])
        assert result.exit_code == 0, result.output
        assert calls == [project]

    @pytest.mark.parametrize("target_platform", ["ios", "macos", "linux"])
    def test_build(self, runner, project, monkeypatch, target_platform):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", target_platform)
        calls = []
        monkeypatch.setattr(
            get_platform(target_platform),
            "build",
            lambda root, **kw: calls.append(root),
        )
        result = runner.invoke(build, [])
        assert result.exit_code == 0, result.output
        assert calls == [project]

    @pytest.mark.parametrize("target_platform", ["ios", "macos", "linux"])
    def test_run(self, runner, project, monkeypatch, target_platform):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", target_platform)
        calls = []
        monkeypatch.setattr(
            get_platform(target_platform),
            "run",
            lambda root, **kw: calls.append(root),
        )
        result = runner.invoke(run, [])
        assert result.exit_code == 0, result.output
        assert calls == [project]

    @pytest.mark.parametrize("target_platform", ["ios", "macos", "linux"])
    def test_package(self, runner, project, monkeypatch, target_platform):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", target_platform)
        calls = []
        monkeypatch.setattr(
            get_platform(target_platform),
            "package",
            lambda root, **kw: calls.append(root),
        )
        result = runner.invoke(package, [])
        assert result.exit_code == 0, result.output
        assert calls == [project]

    def test_open_ios(self, runner, project, monkeypatch):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "ios")
        calls = []
        monkeypatch.setattr(
            get_platform("ios"), "open_project", lambda root: calls.append(root)
        )
        result = runner.invoke(open_, [])
        assert result.exit_code == 0, result.output
        assert calls == [project]

    @pytest.mark.parametrize("target_platform", ["macos", "linux"])
    def test_open_desktop_env_var_still_reaches_correct_backend(
        self, runner, project, monkeypatch, target_platform
    ):
        """Desktop backends have no Xcode project to open, so this errors — but
        the error naming *that* platform (not iOS, the default fixture value)
        proves the env var — not the fixture default — drove resolution."""
        monkeypatch.setenv("KIVYFORGE_PLATFORM", target_platform)
        result = runner.invoke(open_, [])
        assert result.exit_code != 0
        assert target_platform in result.output

    @pytest.mark.parametrize("target_platform", ["ios", "macos", "linux"])
    def test_doctor(self, runner, project, monkeypatch, target_platform):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", target_platform)
        calls = []
        monkeypatch.setattr(
            get_platform(target_platform),
            "doctor",
            lambda cwd, **kw: calls.append(cwd) or [],
        )
        result = runner.invoke(doctor, ["--offline"])
        assert result.exit_code == 0, result.output
        assert calls == [project]
        assert f"({target_platform}," in result.output


def _ios_lockfile(text: str) -> Lockfile:
    return Lockfile(
        requires_python=">=3.15",
        packages=(),
        python_xcframework=PythonXcframework(
            version="3.15.0", url="https://example/py.tar.gz", sha256="c" * 64
        ),
        kivyforge_version="3.0.0.dev0",
        generated_at="t",
        pyproject_sha256=compute_pyproject_sha256(text),
        tool_kivyforge_schema_version=1,
    )


def _wheelruntime_lockfile(text: str, platform_name: str) -> WheelRuntimeLock:
    return WheelRuntimeLock(
        platform=platform_name,
        requires_python=">=3.13",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.13.14",
            artifacts=(
                RuntimeArtifact(
                    arch="arm64",
                    url="https://example/cpython-arm64.tar.gz",
                    sha256="c" * 64,
                ),
            ),
        ),
        archs=("arm64",),
        kivyforge_version="3.0.0.dev0",
        generated_at="t",
        pyproject_sha256=compute_pyproject_sha256(text),
        tool_kivyforge_schema_version=1,
    )


class TestLockDispatchViaEnvVar:
    """``lock`` doesn't call a ``Platform`` method — it resolves the backend
    then picks per-platform build/dump callables by ``backend.name``. The
    build callable is faked (no network) so this stays hermetic; a real
    ``pylock.<platform>.toml`` for the *resolved* platform is the proof.
    """

    def test_ios(self, runner, tmp_path, monkeypatch):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "ios")
        monkeypatch.setattr(
            lock_mod, "build_lockfile", lambda config, text, **kw: _ios_lockfile(text)
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(PYPROJECT_IOS)
            result = runner.invoke(lock, [])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "pylock.ios.toml").is_file()
            assert not (Path(fs) / "pylock.macos.toml").exists()

    def test_macos(self, runner, tmp_path, monkeypatch):
        import kivyforge.platforms.macos.lock as macos_lock

        monkeypatch.setenv("KIVYFORGE_PLATFORM", "macos")
        monkeypatch.setattr(
            macos_lock,
            "build_macos_lockfile",
            lambda config, text, **kw: _wheelruntime_lockfile(text, "macos"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(PYPROJECT_MACOS)
            result = runner.invoke(lock, [])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "pylock.macos.toml").is_file()
            assert not (Path(fs) / "pylock.ios.toml").exists()

    def test_linux(self, runner, tmp_path, monkeypatch):
        import kivyforge.platforms.linux.lock as linux_lock

        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        monkeypatch.setattr(
            linux_lock,
            "build_linux_lockfile",
            lambda config, text, **kw: _wheelruntime_lockfile(text, "linux"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(PYPROJECT_LINUX)
            result = runner.invoke(lock, [])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "pylock.linux.toml").is_file()
            assert not (Path(fs) / "pylock.ios.toml").exists()


class TestUpgradeDispatchViaEnvVar:
    """``upgrade`` also branches on ``backend.name`` rather than calling a
    ``Platform`` method; confirm the env var drives it to the right lock file
    and artifact-name scheme (``Python.xcframework`` vs ``python-runtime-*``).
    """

    def test_ios(self, runner, tmp_path, monkeypatch):
        from kivyforge.platforms.ios.lock import dumps as ios_dumps

        monkeypatch.setenv("KIVYFORGE_PLATFORM", "ios")
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(PYPROJECT_IOS)
            (root / "pylock.ios.toml").write_text(
                ios_dumps(_ios_lockfile(PYPROJECT_IOS))
            )
            result = runner.invoke(upgrade, [])
            assert result.exit_code == 0, result.output
            assert fetched == ["Python.xcframework"]

    def test_macos(self, runner, tmp_path, monkeypatch):
        from kivyforge.platforms.macos.lock import dumps as macos_dumps

        monkeypatch.setenv("KIVYFORGE_PLATFORM", "macos")
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(PYPROJECT_MACOS)
            (root / "pylock.macos.toml").write_text(
                macos_dumps(_wheelruntime_lockfile(PYPROJECT_MACOS, "macos"))
            )
            result = runner.invoke(upgrade, [])
            assert result.exit_code == 0, result.output
            assert fetched == ["python-runtime-arm64"]

    def test_linux(self, runner, tmp_path, monkeypatch):
        from kivyforge.platforms.linux.lock import dumps as linux_dumps

        monkeypatch.setenv("KIVYFORGE_PLATFORM", "linux")
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(PYPROJECT_LINUX)
            (root / "pylock.linux.toml").write_text(
                linux_dumps(_wheelruntime_lockfile(PYPROJECT_LINUX, "linux"))
            )
            result = runner.invoke(upgrade, [])
            assert result.exit_code == 0, result.output
            assert fetched == ["python-runtime-arm64"]


class TestInitDispatchViaEnvVar:
    """``init`` has its own bespoke resolution (``_resolve_init_platform``) that
    reads ``KIVYFORGE_PLATFORM`` directly rather than via the shared
    ``_platform.resolve_target`` wrapper — its own, separate deliberate
    coverage (previously: only a negative/unknown-value env test existed).
    """

    @pytest.mark.parametrize(
        "target_platform, overlay_key",
        [("ios", "ios"), ("macos", "macos"), ("linux", "linux")],
    )
    def test_fresh_project_seeds_overlay_via_env_var(
        self, runner, tmp_path, monkeypatch, target_platform, overlay_key
    ):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", target_platform)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(MINIMAL_PYPROJECT)
            result = runner.invoke(init, [])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert overlay_key in data["tool"]["kivy"]
