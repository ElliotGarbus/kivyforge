"""kivyforge lock -p macos: dispatch, write, in-sync no-op, --check."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.lock import lock

from .conftest import FakeMacosResolver, FakeRuntimeProvider


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def patch_macos_build(monkeypatch):
    """Inject hermetic fakes into the macOS lock build."""
    import kivyforge.platforms.macos.lock as macos_lock

    real_build = macos_lock.build_macos_lockfile

    def fake_build(config, text, *, project_root=None, offline=False, **_kw):
        return real_build(
            config,
            text,
            project_root=project_root,
            resolver=FakeMacosResolver(),
            runtime_provider=FakeRuntimeProvider(floor="11.0"),
            offline=offline,
        )

    monkeypatch.setattr(macos_lock, "build_macos_lockfile", fake_build)


class TestMacosLockCli:
    def test_writes_lockfile(self, runner, tmp_path, macos_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(macos_pyproject + "\n")
            result = runner.invoke(lock, ["-p", "macos"])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "pylock.macos.toml").is_file()
            assert "packages pinned" in result.output

    def test_in_sync_noop(self, runner, tmp_path, macos_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(macos_pyproject + "\n")
            runner.invoke(lock, ["-p", "macos"])
            result = runner.invoke(lock, ["-p", "macos"])
            assert result.exit_code == 0
            assert "already in sync" in result.output

    def test_check_passes_when_in_sync(self, runner, tmp_path, macos_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(macos_pyproject + "\n")
            runner.invoke(lock, ["-p", "macos"])
            result = runner.invoke(lock, ["-p", "macos", "--check"])
            assert result.exit_code == 0, result.output
            assert "up to date" in result.output

    def test_check_fails_when_stale(self, runner, tmp_path, macos_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = Path(fs) / "pyproject.toml"
            pp.write_text(macos_pyproject + "\n")
            runner.invoke(lock, ["-p", "macos"])
            pp.write_text(macos_pyproject + "\n# changed\n")
            result = runner.invoke(lock, ["-p", "macos", "--check"])
            assert result.exit_code != 0
            assert "out of date" in result.output or "stale" in result.output

    def test_ios_and_macos_locks_coexist(self, runner, tmp_path):
        """One pyproject with both overlays produces both lockfiles."""
        text = (
            "[project]\nname='myapp'\nversion='1'\nrequires-python='>=3.15'\n"
            "dependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.myapp'\n"
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(text + "\n")
            result = runner.invoke(lock, ["-p", "macos"])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "pylock.macos.toml").is_file()
