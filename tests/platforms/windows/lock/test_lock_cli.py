"""kivyforge lock -p windows: dispatch, write, in-sync no-op, --check."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.lock import lock

from .conftest import FakeRuntimeProvider, FakeWindowsResolver


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def patch_windows_build(monkeypatch):
    """Inject hermetic fakes into the Windows lock build."""
    import kivyforge.platforms.windows.lock as windows_lock

    real_build = windows_lock.build_windows_lockfile

    def fake_build(config, text, *, project_root=None, offline=False, **_kw):
        return real_build(
            config,
            text,
            project_root=project_root,
            resolver=FakeWindowsResolver(),
            runtime_provider=FakeRuntimeProvider(),
            offline=offline,
        )

    monkeypatch.setattr(windows_lock, "build_windows_lockfile", fake_build)


class TestWindowsLockCli:
    def test_writes_lockfile(self, runner, tmp_path, windows_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(windows_pyproject + "\n")
            result = runner.invoke(lock, ["-p", "windows"])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "pylock.windows.toml").is_file()
            assert "packages pinned" in result.output

    def test_in_sync_noop(self, runner, tmp_path, windows_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(windows_pyproject + "\n")
            runner.invoke(lock, ["-p", "windows"])
            result = runner.invoke(lock, ["-p", "windows"])
            assert result.exit_code == 0
            assert "already in sync" in result.output

    def test_check_passes_when_in_sync(self, runner, tmp_path, windows_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(windows_pyproject + "\n")
            runner.invoke(lock, ["-p", "windows"])
            result = runner.invoke(lock, ["-p", "windows", "--check"])
            assert result.exit_code == 0, result.output
            assert "up to date" in result.output

    def test_check_fails_when_stale(self, runner, tmp_path, windows_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = Path(fs) / "pyproject.toml"
            pp.write_text(windows_pyproject + "\n")
            runner.invoke(lock, ["-p", "windows"])
            pp.write_text(windows_pyproject + "\n# changed\n")
            result = runner.invoke(lock, ["-p", "windows", "--check"])
            assert result.exit_code != 0
            assert "out of date" in result.output or "stale" in result.output
