"""kivyforge lock -p linux: dispatch, write, in-sync no-op, --check."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.lock import lock
from kivyforge.platforms.linux.lock import build_linux_lockfile as real_linux_build

from .conftest import FakeLinuxResolver, FakeRuntimeProvider


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def patch_linux_build(monkeypatch):
    """Inject hermetic fakes into the Linux lock build."""
    import kivyforge.platforms.linux.lock as linux_lock

    real_build = linux_lock.build_linux_lockfile

    def fake_build(config, *, project_root=None, offline=False, **_kw):
        return real_build(
            config,
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
            pp.write_text(
                linux_pyproject.replace(
                    "[tool.kivy.linux]\n",
                    '[tool.kivy.linux]\nexclude = ["unused-dist"]\n',
                )
            )
            result = runner.invoke(lock, ["-p", "linux", "--check"])
            assert result.exit_code != 0
            assert "out of date" in result.output or "stale" in result.output

    def test_a_comment_is_not_drift(self, runner, tmp_path, linux_pyproject):
        """Only lock inputs count (#126): a comment leaves the lock alone."""
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = Path(fs) / "pyproject.toml"
            pp.write_text(linux_pyproject + "\n")
            runner.invoke(lock, ["-p", "linux"])
            pp.write_text(linux_pyproject + "\n# changed\n")
            result = runner.invoke(lock, ["-p", "linux", "--check"])
            assert result.exit_code == 0, result.output
            assert "up to date" in result.output


class _HashingResolver(FakeLinuxResolver):
    """Takes kivy from find_links, hashed by the builder as pip would (#190)."""

    def __init__(self):
        super().__init__(vendored=True)

    def resolve(self, requirements, **kwargs):
        packages = super().resolve(requirements, **kwargs)
        for package in packages:
            if package.name == "kivy":
                package.wheels = [
                    dataclasses.replace(w, sha256="") for w in package.wheels
                ]
        return packages


class TestReplacedLocalWheel:
    """A wheel rebuilt in find_links under the same filename (#190)."""

    @pytest.fixture(autouse=True)
    def hashing_build(self, monkeypatch):
        import kivyforge.platforms.linux.lock as linux_lock

        self.resolver = _HashingResolver()

        def fake_build(config, *, project_root=None, offline=False, **kw):
            return real_linux_build(
                config,
                project_root=project_root,
                resolver=self.resolver,
                runtime_provider=FakeRuntimeProvider(floor="2.17"),
                offline=offline,
                prefer=kw.get("prefer", ()),
            )

        monkeypatch.setattr(linux_lock, "build_linux_lockfile", fake_build)

    def _project(self, fs, linux_pyproject) -> Path:
        root = Path(fs)
        (root / "pyproject.toml").write_text(
            linux_pyproject.replace(
                "[tool.kivy.linux]\n", '[tool.kivy.linux]\nfind_links = ["wheels"]\n'
            )
            + "\n"
        )
        wheels = root / "wheels"
        wheels.mkdir()
        wheel = wheels / (
            "kivy-3.0.0-cp315-cp315-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
        )
        wheel.write_bytes(b"first build")
        return wheel

    def test_lock_re_records_the_new_hash(self, runner, tmp_path, linux_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            wheel = self._project(fs, linux_pyproject)
            assert runner.invoke(lock, ["-p", "linux"]).exit_code == 0
            wheel.write_bytes(b"second build")

            result = runner.invoke(lock, ["-p", "linux"])

            assert result.exit_code == 0, result.output
            assert "already in sync" not in result.output
            assert f"wheels/{wheel.name} changed since it was locked" in result.output
            new_hash = hashlib.sha256(b"second build").hexdigest()
            assert new_hash in (Path(fs) / "pylock.linux.toml").read_text()
            # Only the rebuilt package lost its pin; the rest kept theirs.
            assert self.resolver.calls[-1]["constraints"] == {
                "more-itertools": "10.5.0"
            }

    def test_check_names_the_rebuilt_wheel(self, runner, tmp_path, linux_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            wheel = self._project(fs, linux_pyproject)
            assert runner.invoke(lock, ["-p", "linux"]).exit_code == 0
            wheel.write_bytes(b"second build")

            result = runner.invoke(lock, ["-p", "linux", "--check"])

            assert result.exit_code == 4, result.output
            assert f"~ kivy: {wheel.name} changed (sha256 " in result.output
