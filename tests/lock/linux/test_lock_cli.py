"""kivyforge lock -p linux: dispatch, write, in-sync no-op, --check."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.lock import lock

from .conftest import FakeLinuxResolver, FakeRuntimeProvider


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def patch_linux_build(monkeypatch):
    """Inject hermetic fakes into the Linux lock build."""
    import kivyforge.lock.linux as linux_lock

    real_build = linux_lock.build_linux_lockfile

    def fake_build(config, text, *, project_root=None, offline=False, **_kw):
        return real_build(
            config,
            text,
            project_root=project_root,
            resolver=FakeLinuxResolver(),
            runtime_provider=FakeRuntimeProvider(floor="2.17"),
            offline=offline,
        )

    monkeypatch.setattr(linux_lock, "build_linux_lockfile", fake_build)


class TestLinuxLockCli:
    def test_writes_lockfile(self, runner, tmp_path, linux_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(linux_pyproject + "\n")
            result = runner.invoke(lock, ["-p", "linux"])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "pylock.linux.toml").is_file()
            assert "packages pinned" in result.output

    def test_in_sync_noop(self, runner, tmp_path, linux_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(linux_pyproject + "\n")
            runner.invoke(lock, ["-p", "linux"])
            result = runner.invoke(lock, ["-p", "linux"])
            assert result.exit_code == 0
            assert "already in sync" in result.output

    def test_check_passes_when_in_sync(self, runner, tmp_path, linux_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(linux_pyproject + "\n")
            runner.invoke(lock, ["-p", "linux"])
            result = runner.invoke(lock, ["-p", "linux", "--check"])
            assert result.exit_code == 0, result.output
            assert "up to date" in result.output

    def test_check_fails_when_stale(self, runner, tmp_path, linux_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = Path(fs) / "pyproject.toml"
            pp.write_text(linux_pyproject + "\n")
            runner.invoke(lock, ["-p", "linux"])
            pp.write_text(linux_pyproject + "\n# changed\n")
            result = runner.invoke(lock, ["-p", "linux", "--check"])
            assert result.exit_code != 0
            assert "out of date" in result.output or "stale" in result.output
