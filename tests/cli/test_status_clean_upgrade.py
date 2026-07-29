"""Phase 7 — status / clean / upgrade / doctor CLI verbs."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.artifacts.download import DownloadError
from kivyforge.artifacts.verify import HashMismatch
from kivyforge.cli import upgrade as upgrade_mod
from kivyforge.cli.clean import clean
from kivyforge.cli.doctor import doctor
from kivyforge.cli.status import status
from kivyforge.cli.upgrade import upgrade
from kivyforge.lock import compute_pyproject_sha256
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.ios import doctor as doctor_mod
from kivyforge.platforms.ios.cli import _humanize
from kivyforge.platforms.ios.lock import (
    LockedXcframework,
    Lockfile,
    PythonXcframework,
    dumps,
)

PYPROJECT = (
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

DESKTOP_ONLY_PYPROJECT = (
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


def _lock(text: str, *, xcframeworks=()) -> Lockfile:
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
        xcframeworks=tuple(xcframeworks),
    )


def _write(fs: str, *, lock: bool = True, **lock_kw) -> Path:
    root = Path(fs)
    (root / "pyproject.toml").write_text(PYPROJECT)
    (root / "src").mkdir()
    if lock:
        (root / "pylock.ios.toml").write_text(dumps(_lock(PYPROJECT, **lock_kw)))
    return root


@pytest.fixture
def runner():
    return CliRunner()


class TestHumanize:
    def test_just_now(self):
        assert _humanize(0) == "just now"
        assert _humanize(59) == "just now"

    def test_minutes(self):
        assert _humanize(60) == "1 minute ago"
        assert _humanize(120) == "2 minutes ago"
        assert _humanize(3599) == "59 minutes ago"

    def test_hours(self):
        assert _humanize(3600) == "1 hour ago"
        assert _humanize(7200) == "2 hours ago"
        assert _humanize(86399) == "23 hours ago"

    def test_days(self):
        assert _humanize(86400) == "1 day ago"
        assert _humanize(172800) == "2 days ago"


class TestStatus:
    def test_snapshot(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(status, [])
            assert result.exit_code == 0, result.output
            assert "My App  (org.example.myapp)" in result.output
            assert "Python:     3.15.0" in result.output
            assert "Lock:       in sync" in result.output
            assert "not built" in result.output

    def test_lock_missing(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs, lock=False)
            result = runner.invoke(status, [])
            assert result.exit_code == 0
            assert "missing" in result.output

    def test_lock_unreadable(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs, lock=False)
            # Valid TOML but missing [tool.kivyforge] → LockError from reader
            (Path(fs) / "pylock.ios.toml").write_text("lock-version = '1.0'\n")
            result = runner.invoke(status, [])
            assert result.exit_code == 0
            assert "unreadable" in result.output

    def test_config_error_exits_nonzero(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            # Write a pyproject.toml missing required ios fields
            (Path(fs) / "pyproject.toml").write_text(
                "[project]\nname='x'\nversion='1'\n"
            )
            (Path(fs) / "src").mkdir()
            result = runner.invoke(status, [])
            assert result.exit_code != 0

    def test_no_pyproject_exits_nonzero(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(status, [])
            assert result.exit_code != 0

    def test_built_app_shows_age(self, runner, tmp_path, monkeypatch):
        import time

        fixed_time = 1_000_000.0
        monkeypatch.setattr(time, "time", lambda: fixed_time)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            # Create a fake built app directory
            app_path = (
                Path(fs)
                / "myapp-ios"
                / "build"
                / "DerivedData"
                / "Build"
                / "Products"
                / "Debug-iphonesimulator"
                / "myapp.app"
            )
            app_path.mkdir(parents=True)
            import os

            os.utime(app_path, (fixed_time - 120, fixed_time - 120))
            result = runner.invoke(status, [])
            assert result.exit_code == 0, result.output
            assert "minute" in result.output


class TestClean:
    def test_removes_staging(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            (Path(fs) / "myapp-ios").mkdir()
            (Path(fs) / "myapp-ios" / "x.txt").write_text("x")
            result = runner.invoke(clean, [])
            assert result.exit_code == 0, result.output
            assert not (Path(fs) / "myapp-ios").exists()
            assert "Removed myapp-ios/" in result.output

    def test_removes_linux_and_macos_trees(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            root = Path(fs)
            (root / "build" / "macos").mkdir(parents=True)
            (root / "build" / "linux" / "My App.AppDir").mkdir(parents=True)
            (root / "dist" / "linux").mkdir(parents=True)
            (root / "dist" / "linux" / "x.AppImage").write_text("x")
            result = runner.invoke(clean, [])
            assert result.exit_code == 0, result.output
            assert not (root / "build" / "macos").exists()
            assert not (root / "build" / "linux").exists()
            assert not (root / "dist" / "linux").exists()
            # Emptied build/ and dist/ husks are pruned.
            assert not (root / "build").exists()
            assert not (root / "dist").exists()
            assert "Removed build/macos/" in result.output
            assert "Removed build/linux/" in result.output
            assert "Removed dist/linux/" in result.output

    def test_desktop_only_project_cleans(self, runner, tmp_path):
        """A project with no [tool.kivy.ios] overlay must still clean."""
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "pyproject.toml").write_text(DESKTOP_ONLY_PYPROJECT)
            root = Path(fs)
            (root / "build" / "linux" / "My App.AppDir").mkdir(parents=True)
            result = runner.invoke(clean, [])
            assert result.exit_code == 0, result.output
            assert not (root / "build" / "linux").exists()
            assert "Removed build/linux/" in result.output

    def test_nothing_to_clean(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(clean, [])
            assert result.exit_code == 0
            assert "Nothing to clean" in result.output

    def test_cache_flush(self, runner, tmp_path, monkeypatch):
        cleared = []

        class FakeCache:
            def clear(self):
                cleared.append(True)

        monkeypatch.setattr(
            "kivyforge.cli.clean.ArtifactCache", lambda *a, **k: FakeCache()
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(clean, ["--cache"])
            assert result.exit_code == 0
            assert cleared == [True]

    def test_cache_only_without_pyproject(self, runner, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "kivyforge.cli.clean.ArtifactCache",
            lambda *a, **k: type("C", (), {"clear": lambda self: None})(),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(clean, ["--cache"])
            assert result.exit_code == 0

    def test_gradle_daemon_is_stopped_before_the_removal(
        self, runner, tmp_path, monkeypatch
    ):
        """A live daemon holds handles under app/build, which makes removing
        <app>-android/ fail outright on Windows — so the order matters."""
        from kivyforge.platforms.android import gradlew as gradlew_mod

        events = []

        def fake_stop(project_dir):
            events.append(("stop", project_dir.exists()))
            return True

        monkeypatch.setattr(gradlew_mod, "stop_gradle_daemon", fake_stop)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            android = Path(fs) / "myapp-android"
            _write(fs)
            (android / "app" / "build").mkdir(parents=True)
            result = runner.invoke(clean, [])
            assert result.exit_code == 0, result.output
            assert events == [("stop", True)]
            assert not android.exists()
            assert "Stopped the project's Gradle daemon(s)." in result.output

    def test_no_android_project_means_no_daemon_call(
        self, runner, tmp_path, monkeypatch
    ):
        from kivyforge.platforms.android import gradlew as gradlew_mod

        called = []
        monkeypatch.setattr(
            gradlew_mod, "stop_gradle_daemon", lambda p: called.append(p) or True
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(clean, [])
            assert result.exit_code == 0
            assert called == []

    def test_cache_all_flushes_the_shared_gradle_caches(
        self, runner, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "kivyforge.cli.clean.ArtifactCache",
            lambda *a, **k: type("C", (), {"clear": lambda self: None})(),
        )
        gradle_home = tmp_path / "gradle-home"
        (gradle_home / "caches" / "modules-2").mkdir(parents=True)
        (gradle_home / "daemon" / "8.11.1").mkdir(parents=True)
        # Configuration, not cache: flushing it would cost every project on the
        # machine a wrapper re-download for no benefit.
        (gradle_home / "wrapper").mkdir()
        (gradle_home / "gradle.properties").write_text("org.gradle.jvmargs=-Xmx2g\n")
        monkeypatch.setenv("GRADLE_USER_HOME", str(gradle_home))
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(clean, ["--cache-all"])
            assert result.exit_code == 0, result.output
        assert not (gradle_home / "caches").exists()
        assert not (gradle_home / "daemon").exists()
        assert (gradle_home / "wrapper").exists()
        assert (gradle_home / "gradle.properties").exists()
        assert "Flushed shared Gradle caches, daemon" in result.output

    def test_plain_cache_spares_the_shared_gradle_home(
        self, runner, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "kivyforge.cli.clean.ArtifactCache",
            lambda *a, **k: type("C", (), {"clear": lambda self: None})(),
        )
        gradle_home = tmp_path / "gradle-home-2"
        (gradle_home / "caches").mkdir(parents=True)
        monkeypatch.setenv("GRADLE_USER_HOME", str(gradle_home))
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(clean, ["--cache"])
            assert result.exit_code == 0, result.output
        assert (gradle_home / "caches").exists()

    def test_cache_all_and_project_only_contradict(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(clean, ["--cache-all", "--project-only"])
            assert result.exit_code != 0
            assert "contradict" in result.output


class TestUpgrade:
    def test_refreshes_python_and_xcframeworks(self, runner, tmp_path, monkeypatch):
        fetched = []

        def fake_fetch(*, name, sha256, filename, url=None, **kw):
            fetched.append(name)
            return Path("/cache") / filename

        monkeypatch.setattr(upgrade_mod, "fetch_artifact", fake_fetch)
        xc = LockedXcframework(
            name="SDL3",
            version="3.0.0",
            sha256="a" * 64,
            slices=("ios-arm64",),
            url="https://example/SDL3.zip",
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs, xcframeworks=[xc])
            result = runner.invoke(upgrade, [])
            assert result.exit_code == 0, result.output
            assert "Python.xcframework" in fetched
            assert "SDL3" in fetched
            assert "Refreshed 2 artifact(s)" in result.output

    def test_python_only(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(upgrade, ["--python"])
            assert result.exit_code == 0
            assert fetched == ["Python.xcframework"]

    def test_skips_vendored_xcframework(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        xc = LockedXcframework(
            name="Local",
            version="1",
            sha256="a" * 64,
            slices=("ios-arm64",),
            path="vendor/Local.zip",
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs, xcframeworks=[xc])
            result = runner.invoke(upgrade, ["--xcframeworks"])
            assert result.exit_code == 0
            assert "Local" not in fetched
            assert "Skipped 1 vendored" in result.output

    def test_name_selects_single_xcframework(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        xc = LockedXcframework(
            name="SDL3",
            version="3.0.0",
            sha256="a" * 64,
            slices=("ios-arm64",),
            url="https://example/SDL3.zip",
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs, xcframeworks=[xc])
            result = runner.invoke(upgrade, ["--name", "SDL3"])
            assert result.exit_code == 0, result.output
            assert fetched == ["SDL3"]
            assert "Python.xcframework" not in fetched

    def test_name_selects_python_only(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        xc = LockedXcframework(
            name="SDL3",
            version="3.0.0",
            sha256="a" * 64,
            slices=("ios-arm64",),
            url="https://example/SDL3.zip",
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs, xcframeworks=[xc])
            result = runner.invoke(upgrade, ["--name", "Python.xcframework"])
            assert result.exit_code == 0, result.output
            assert fetched == ["Python.xcframework"]

    def test_name_unknown_errors(self, runner, tmp_path, monkeypatch):
        monkeypatch.setattr(
            upgrade_mod, "fetch_artifact", lambda *, name, **kw: Path("/x")
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(upgrade, ["--name", "DoesNotExist"])
            assert result.exit_code != 0
            assert "no artifact named 'DoesNotExist'" in result.output

    def test_hash_mismatch_surfaces_as_toolchain_error(
        self, runner, tmp_path, monkeypatch
    ):
        def boom(*, name, sha256, filename, url=None, **kw):
            raise HashMismatch(
                name=name,
                source=url or filename,
                expected=sha256,
                actual="0" * 64,
            )

        monkeypatch.setattr(upgrade_mod, "fetch_artifact", boom)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(upgrade, ["--python"])
            assert result.exit_code != 0
            assert "SHA-256 mismatch" in result.output

    def test_download_error_surfaces_as_toolchain_error(
        self, runner, tmp_path, monkeypatch
    ):
        def boom(*, name, **kw):
            raise DownloadError("network down")

        monkeypatch.setattr(upgrade_mod, "fetch_artifact", boom)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(upgrade, ["--python"])
            assert result.exit_code != 0
            assert "network down" in result.output

    def test_missing_lock_errors(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs, lock=False)
            result = runner.invoke(upgrade, [])
            assert result.exit_code != 0
            assert "kivyforge lock" in result.output


def _wheelruntime_lock(
    text: str, platform: str, *, archs=("arm64", "x86_64")
) -> WheelRuntimeLock:
    return WheelRuntimeLock(
        platform=platform,
        requires_python=">=3.13",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.13.14",
            artifacts=tuple(
                RuntimeArtifact(
                    arch=arch,
                    url=f"https://example/cpython-{arch}.tar.gz",
                    sha256="c" * 64,
                )
                for arch in archs
            ),
        ),
        archs=archs,
        kivyforge_version="3.0.0.dev0",
        generated_at="t",
        pyproject_sha256=compute_pyproject_sha256(text),
        tool_kivyforge_schema_version=1,
    )


def _write_desktop(
    fs: str, platform: str, *, lock: bool = True, archs=("arm64", "x86_64")
) -> Path:
    root = Path(fs)
    root_pyproject = DESKTOP_ONLY_PYPROJECT if platform == "linux" else _MACOS_PYPROJECT
    (root / "pyproject.toml").write_text(root_pyproject)
    (root / "src").mkdir()
    if lock:
        from kivyforge.platforms.linux.lock import dumps as dumps_linux
        from kivyforge.platforms.macos.lock import dumps as dumps_macos

        dumper = dumps_macos if platform == "macos" else dumps_linux
        (root / f"pylock.{platform}.toml").write_text(
            dumper(_wheelruntime_lock(root_pyproject, platform, archs=archs))
        )
    return root


_MACOS_PYPROJECT = (
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


class TestUpgradeDesktop:
    """macOS/Linux: the bundled python-build-standalone runtime is the only
    lock-pinned artifact upgrade can refresh (no xcframework-equivalent)."""

    def test_macos_refreshes_all_runtime_archs(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_desktop(fs, "macos")
            result = runner.invoke(upgrade, ["-p", "macos"])
            assert result.exit_code == 0, result.output
            assert set(fetched) == {"python-runtime-arm64", "python-runtime-x86_64"}
            assert "Refreshed 2 artifact(s)" in result.output

    def test_macos_name_selects_single_arch(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_desktop(fs, "macos")
            result = runner.invoke(upgrade, ["-p", "macos", "--name", "arm64"])
            assert result.exit_code == 0, result.output
            assert fetched == ["python-runtime-arm64"]

    def test_macos_name_unknown_arch_errors(self, runner, tmp_path, monkeypatch):
        monkeypatch.setattr(
            upgrade_mod, "fetch_artifact", lambda *, name, **kw: Path("/x")
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_desktop(fs, "macos")
            result = runner.invoke(upgrade, ["-p", "macos", "--name", "riscv64"])
            assert result.exit_code != 0
            assert "no runtime artifact for arch 'riscv64'" in result.output
            assert "arm64" in result.output and "x86_64" in result.output

    def test_macos_xcframeworks_flag_errors(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_desktop(fs, "macos")
            result = runner.invoke(upgrade, ["-p", "macos", "--xcframeworks"])
        assert result.exit_code != 0
        assert "--xcframeworks is iOS-only" in result.output

    def test_linux_refreshes_single_runtime_arch(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_desktop(fs, "linux", archs=("x86_64",))
            result = runner.invoke(upgrade, ["-p", "linux"])
            assert result.exit_code == 0, result.output
            assert fetched == ["python-runtime-x86_64"]
            assert "Refreshed 1 artifact(s)" in result.output

    def test_desktop_missing_lock_errors(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_desktop(fs, "macos", lock=False)
            result = runner.invoke(upgrade, ["-p", "macos"])
        assert result.exit_code != 0
        assert "kivyforge lock" in result.output

    def test_hash_mismatch_surfaces_as_toolchain_error(
        self, runner, tmp_path, monkeypatch
    ):
        def boom(*, name, sha256, filename, url=None, **kw):
            raise HashMismatch(
                name=name, source=url or filename, expected=sha256, actual="0" * 64
            )

        monkeypatch.setattr(upgrade_mod, "fetch_artifact", boom)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_desktop(fs, "macos")
            result = runner.invoke(upgrade, ["-p", "macos"])
            assert result.exit_code != 0
            assert "SHA-256 mismatch" in result.output


class TestDoctor:
    def test_environment_mode_no_pyproject(self, runner, tmp_path, monkeypatch):
        from tests.doctor.conftest import FakeProbe

        monkeypatch.setattr(doctor_mod, "RealProbe", lambda: FakeProbe())
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(doctor, ["--offline"])
            assert "environment mode" in result.output
            assert "SKIP" in result.output

    def test_project_mode_fail_exits_nonzero(self, runner, tmp_path, monkeypatch):
        from tests.doctor.conftest import FakeProbe

        monkeypatch.setattr(doctor_mod, "RealProbe", lambda: FakeProbe(xcode=None))
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs)
            result = runner.invoke(doctor, ["--offline"])
            assert "project mode" in result.output
            assert result.exit_code != 0

    def test_malformed_pyproject_fails_nonzero(self, runner, tmp_path, monkeypatch):
        from tests.doctor.conftest import FakeProbe

        # Healthy environment so the only failure is the unparseable config;
        # doctor must still exit non-zero (was: printed FAIL but exited 0).
        monkeypatch.setattr(doctor_mod, "RealProbe", lambda: FakeProbe())
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            # Valid TOML, invalid config: bundle_id is required.
            (Path(fs) / "pyproject.toml").write_text(
                "[project]\nname='a'\nversion='1'\n[tool.kivy.ios]\nschema_version=1\n"
            )
            result = runner.invoke(doctor, ["--offline"])
            assert "[FAIL] pyproject.toml" in result.output
            assert result.exit_code != 0

    def test_malformed_lock_reported_as_fail(self, runner, tmp_path, monkeypatch):
        from tests.doctor.conftest import FakeProbe

        monkeypatch.setattr(doctor_mod, "RealProbe", lambda: FakeProbe())
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write(fs, lock=False)
            # Valid TOML but missing [tool.kivyforge] → LockError from the reader.
            (Path(fs) / "pylock.ios.toml").write_text("lock-version = '1.0'\n")
            result = runner.invoke(doctor, ["--offline"])
            assert "[FAIL] pylock.ios.toml" in result.output
            assert result.exit_code != 0
