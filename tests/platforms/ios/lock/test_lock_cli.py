"""Phase 3 — kivyforge lock CLI: write, in-sync no-op, --update, --check (spec 05)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli import lock as lock_cli
from kivyforge.cli.lock import lock


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def patch_backends(monkeypatch, fake_resolver, fake_python_provider):
    """Make the CLI use the hermetic fakes instead of pip/python.org."""
    import kivyforge.platforms.ios.lock.builder as builder

    real_build = builder.build_lockfile

    def fake_build(
        config,
        *,
        project_root=None,
        resolver=None,
        python_provider=None,
        prefer=(),
        offline=False,
        now=None,
        on_warning=None,
        on_progress=None,
        on_transfer=None,
    ):
        return real_build(
            config,
            project_root=project_root,
            resolver=fake_resolver,
            python_provider=fake_python_provider,
            prefer=prefer,
            offline=offline,
            now=now,
        )

    monkeypatch.setattr(lock_cli, "build_lockfile", fake_build)
    return fake_resolver


class TestLockCli:
    def test_writes_lockfile(self, runner, tmp_path, minimal_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            from pathlib import Path

            (Path(fs) / "pyproject.toml").write_text(minimal_pyproject + "\n")
            result = runner.invoke(lock, [])
            assert result.exit_code == 0, result.output
            assert (Path(fs) / "pylock.ios.toml").is_file()
            assert "packages pinned" in result.output

    def test_in_sync_noop(self, runner, tmp_path, minimal_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            from pathlib import Path

            (Path(fs) / "pyproject.toml").write_text(minimal_pyproject + "\n")
            runner.invoke(lock, [])
            result = runner.invoke(lock, [])
            assert result.exit_code == 0
            assert "already in sync" in result.output

    def test_check_passes_when_in_sync(self, runner, tmp_path, minimal_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            from pathlib import Path

            (Path(fs) / "pyproject.toml").write_text(minimal_pyproject + "\n")
            runner.invoke(lock, [])
            result = runner.invoke(lock, ["--check"])
            assert result.exit_code == 0, result.output
            assert "up to date" in result.output

    def test_check_fails_when_stale(self, runner, tmp_path, minimal_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            from pathlib import Path

            pp = Path(fs) / "pyproject.toml"
            pp.write_text(minimal_pyproject + "\n")
            runner.invoke(lock, [])
            # edit pyproject so the recorded hash no longer matches
            pp.write_text(
                minimal_pyproject.replace(
                    "[tool.kivy.ios]\n",
                    '[tool.kivy.ios]\nexclude = ["unused-dist"]\n',
                )
            )
            result = runner.invoke(lock, ["--check"])
            assert result.exit_code != 0
            assert "out of date" in result.output or "stale" in result.output

    def test_check_without_lock_errors(self, runner, tmp_path, minimal_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            from pathlib import Path

            (Path(fs) / "pyproject.toml").write_text(minimal_pyproject + "\n")
            result = runner.invoke(lock, ["--check"])
            assert result.exit_code != 0
            assert "does not exist" in result.output

    def test_no_pyproject_errors(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(lock, [])
            assert result.exit_code != 0
            assert "no pyproject.toml" in result.output

    def test_a_comment_is_not_drift(self, runner, tmp_path, minimal_pyproject):
        """Only lock inputs count (#126): a comment leaves the lock alone."""
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = Path(fs) / "pyproject.toml"
            pp.write_text(minimal_pyproject + "\n")
            runner.invoke(lock, [])
            pp.write_text(minimal_pyproject + "\n# changed\n")
            result = runner.invoke(lock, ["--check"])
            assert result.exit_code == 0, result.output
            assert "up to date" in result.output


class TestIncludePins:
    """Plain ``lock`` refreshes include pins without re-resolving (§4.3)."""

    INCLUDE = (
        '\n[[tool.kivy.ios.include_files]]\ndest = "."\n'
        'sources = ["config/GoogleService-Info.plist"]\n'
    )

    @pytest.fixture
    def project(self, runner, tmp_path, minimal_pyproject):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "src").mkdir()
            (root / "config").mkdir()
            (root / "config" / "GoogleService-Info.plist").write_text("<plist/>")
            (root / "pyproject.toml").write_text(minimal_pyproject + self.INCLUDE)
            yield root

    def test_lock_records_a_pin(self, runner, project):
        result = runner.invoke(lock, [])
        assert result.exit_code == 0, result.output
        text = (project / "pylock.ios.toml").read_text()
        assert 'source = "config/GoogleService-Info.plist"' in text

    def test_an_edit_rewrites_the_pins_and_resolves_nothing(
        self, runner, project, patch_backends
    ):
        runner.invoke(lock, [])
        resolved = len(patch_backends.calls)
        (project / "config" / "GoogleService-Info.plist").write_text("<edited/>")

        check = runner.invoke(lock, ["--check"])
        assert check.exit_code == 4, check.output
        assert "include_files: config/GoogleService-Info.plist -> . (changed)" in (
            check.output
        )

        result = runner.invoke(lock, [])
        assert result.exit_code == 0, result.output
        assert "file hashes re-recorded" in result.output
        assert len(patch_backends.calls) == resolved + 1  # the --check only
        assert "already in sync" in runner.invoke(lock, []).output
