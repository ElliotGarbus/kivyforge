"""A re-lock keeps the locked python-build-standalone runtime when it still fits.

Finding the PBS build is a GitHub API query that pages through releases, 15 MB
a page, and took up to 40 s on Windows (#88 follow-up). Packages keep their
pins on a re-lock (#126); the runtime now does too, while nothing it depends on
moved. ``lock --update`` always looks it up again.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.lock import lock
from kivyforge.lock.wheelruntime.builder import _locked_runtime
from kivyforge.lock.wheelruntime.model import PythonRuntime, RuntimeArtifact
from tests.platforms.linux.lock.conftest import FakeLinuxResolver, FakeRuntimeProvider


def _runtime(version="3.13.14", archs=("x86_64",), floor="2.17", provider=None):
    return PythonRuntime(
        provider=provider or FakeRuntimeProvider.name,
        version=version,
        artifacts=tuple(
            RuntimeArtifact(arch=a, url=f"https://dl/{a}.tar.gz", sha256="c" * 64)
            for a in archs
        ),
        floor=floor,
    )


class TestLockedRuntime:
    def test_a_matching_runtime_is_kept(self):
        provider = FakeRuntimeProvider(floor="2.17")
        locked = _runtime()
        assert _locked_runtime(locked, provider, "3.13.14", ("x86_64",)) == locked

    def test_artifacts_follow_the_requested_archs(self):
        provider = FakeRuntimeProvider(floor="2.17")
        locked = _runtime(archs=("x86_64", "aarch64"))
        kept = _locked_runtime(locked, provider, "3.13.14", ("x86_64",))
        assert kept is not None
        assert [a.arch for a in kept.artifacts] == ["x86_64"]

    @pytest.mark.parametrize(
        ("locked", "floor", "version", "archs"),
        [
            pytest.param(None, "2.17", "3.13.14", ("x86_64",), id="no lock"),
            pytest.param(_runtime(), "2.17", "3.13.15", ("x86_64",), id="new version"),
            pytest.param(_runtime(), "2.28", "3.13.14", ("x86_64",), id="new floor"),
            pytest.param(
                _runtime(), "2.17", "3.13.14", ("x86_64", "aarch64"), id="new arch"
            ),
            pytest.param(
                _runtime(provider="python.org"),
                "2.17",
                "3.13.14",
                ("x86_64",),
                id="other provider",
            ),
        ],
    )
    def test_anything_it_depends_on_moving_looks_up_again(
        self, locked, floor, version, archs
    ):
        provider = FakeRuntimeProvider(floor=floor)
        assert _locked_runtime(locked, provider, version, archs) is None


PYPROJECT = textwrap.dedent(
    """
    [project]
    name = "myapp"
    version = "1.0.0"
    requires-python = ">=3.13"
    dependencies = ["kivy>=3.0,<4", "more-itertools>=10.5"]

    [tool.kivy]
    app_dir = "src"

    [tool.kivy.linux]
    schema_version = 1
    app_id = "org.example.myapp"

    [tool.kivy.linux.python]
    version = "3.13.14"
    """
)


@pytest.fixture
def runtime_provider(monkeypatch):
    """`lock -p linux` with hermetic fakes; returns the runtime provider."""
    import kivyforge.platforms.linux.lock as linux_lock

    provider = FakeRuntimeProvider(floor="2.17")
    real_build = linux_lock.build_linux_lockfile

    def build(config, **kwargs):
        kwargs.pop("on_warning", None)
        return real_build(
            config,
            resolver=FakeLinuxResolver(),
            runtime_provider=provider,
            **kwargs,
        )

    monkeypatch.setattr(linux_lock, "build_linux_lockfile", build)
    return provider


def _edit_an_input(path: Path) -> None:
    path.write_text(
        PYPROJECT.replace(
            'app_id = "org.example.myapp"\n',
            'app_id = "org.example.myapp"\nexclude = ["docutils"]\n',
        ),
        encoding="utf-8",
    )


class TestThroughTheCli:
    def test_a_re_lock_keeps_the_runtime(self, runtime_provider, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            path = Path(fs) / "pyproject.toml"
            path.write_text(PYPROJECT, encoding="utf-8")
            runner.invoke(lock, ["-p", "linux"])
            assert len(runtime_provider.calls) == 1
            _edit_an_input(path)
            result = runner.invoke(lock, ["-p", "linux"])
            assert result.exit_code == 0, result.output
        assert len(runtime_provider.calls) == 1  # not looked up again
        assert "keeping the locked python-build-standalone build" in result.output

    def test_check_keeps_the_runtime(self, runtime_provider, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
            runner.invoke(lock, ["-p", "linux"])
            result = runner.invoke(lock, ["-p", "linux", "--check"])
            assert result.exit_code == 0, result.output
        assert len(runtime_provider.calls) == 1

    def test_update_looks_it_up_again(self, runtime_provider, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
            runner.invoke(lock, ["-p", "linux"])
            result = runner.invoke(lock, ["-p", "linux", "--update"])
            assert result.exit_code == 0, result.output
        assert len(runtime_provider.calls) == 2

    def test_a_new_python_version_looks_it_up_again(self, runtime_provider, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            path = Path(fs) / "pyproject.toml"
            path.write_text(PYPROJECT, encoding="utf-8")
            runner.invoke(lock, ["-p", "linux"])
            path.write_text(PYPROJECT.replace("3.13.14", "3.13.15"), encoding="utf-8")
            result = runner.invoke(lock, ["-p", "linux"])
            assert result.exit_code == 0, result.output
        assert [c["version"] for c in runtime_provider.calls] == ["3.13.14", "3.13.15"]
