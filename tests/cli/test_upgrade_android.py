"""``kivyforge upgrade`` — Android backend + the remaining cross-platform gaps
(unsupported-platform dispatch, iOS/wheelruntime corrupt-lock wrapping, the
windows wheelruntime loader branch, and DownloadError surfacing for desktop
runtimes) not already covered by ``test_status_clean_upgrade.py`` (spec 05).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.artifacts.download import DownloadError
from kivyforge.cli import upgrade as upgrade_mod
from kivyforge.cli.upgrade import upgrade
from kivyforge.lock import compute_pyproject_sha256
from kivyforge.lock.wheelruntime.model import (
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.android.lock.model import (
    AndroidLockfile,
    LockedAndroidLib,
    PythonAndroidRuntime,
)
from kivyforge.platforms.android.lock.writer import dumps as dumps_android

ANDROID_PYPROJECT = (
    textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        dependencies = ["pyjnius"]

        [tool.kivy]
        app_dir = "src"

        [tool.kivy.android]
        schema_version = 1
        package = "org.example.myapp"

        [tool.kivy.android.python]
        version = "3.14.6"
        """
    ).strip()
    + "\n"
)


@pytest.fixture
def runner():
    return CliRunner()


def _android_lock(
    *,
    runtimes=None,
    libs=(),
    pyproject_text=ANDROID_PYPROJECT,
) -> AndroidLockfile:
    if runtimes is None:
        runtimes = (
            PythonAndroidRuntime(
                version="3.14.6",
                abi="arm64_v8a",
                url="https://example/py-arm64.tar.gz",
                sha256="a" * 64,
                min_api=24,
            ),
            PythonAndroidRuntime(
                version="3.14.6",
                abi="x86_64",
                url="https://example/py-x86_64.tar.gz",
                sha256="b" * 64,
                min_api=24,
            ),
        )
    return AndroidLockfile(
        requires_python=">=3.14",
        packages=(),
        python_android=runtimes,
        kivyforge_version="0",
        generated_at="t",
        pyproject_sha256=compute_pyproject_sha256(pyproject_text),
        tool_kivy_android_schema_version=1,
        kivy_generation=2,
        android_libs=libs,
    )


def _write_android(fs: str, *, lock: AndroidLockfile | None | bool = True) -> Path:
    root = Path(fs)
    (root / "pyproject.toml").write_text(ANDROID_PYPROJECT, encoding="utf-8")
    (root / "src").mkdir()
    if lock is not False:
        payload = lock if isinstance(lock, AndroidLockfile) else _android_lock()
        (root / "pylock.android.toml").write_text(
            dumps_android(payload), encoding="utf-8"
        )
    return root


class TestUpgradeAndroid:
    def test_refreshes_runtimes_and_libs(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        lib = LockedAndroidLib(
            name="Sdk.aar",
            kind="aar",
            version="1.0",
            url="https://example/Sdk.aar",
            sha256="c" * 64,
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs, lock=_android_lock(libs=(lib,)))
            result = runner.invoke(upgrade, ["-p", "android"])
            assert result.exit_code == 0, result.output
            assert set(fetched) == {
                "python-android-arm64_v8a",
                "python-android-x86_64",
                "Sdk.aar",
            }
            assert "Refreshed 3 artifact(s)" in result.output

    def test_python_only_skips_libs_entirely(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        lib = LockedAndroidLib(
            name="Sdk.aar",
            kind="aar",
            version="1.0",
            url="https://example/Sdk.aar",
            sha256="c" * 64,
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs, lock=_android_lock(libs=(lib,)))
            result = runner.invoke(upgrade, ["-p", "android", "--python"])
            assert result.exit_code == 0, result.output
            assert "Sdk.aar" not in fetched
            assert "Refreshed 2 artifact(s)" in result.output

    def test_name_selects_single_abi(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs)
            result = runner.invoke(upgrade, ["-p", "android", "--name", "x86_64"])
            assert result.exit_code == 0, result.output
            assert fetched == ["python-android-x86_64"]

    def test_name_python_sentinel_matches_all_runtimes(
        self, runner, tmp_path, monkeypatch
    ):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        lib = LockedAndroidLib(
            name="Sdk.aar",
            kind="aar",
            version="1.0",
            url="https://example/Sdk.aar",
            sha256="c" * 64,
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs, lock=_android_lock(libs=(lib,)))
            result = runner.invoke(upgrade, ["-p", "android", "--name", "python"])
            assert result.exit_code == 0, result.output
            assert set(fetched) == {
                "python-android-arm64_v8a",
                "python-android-x86_64",
            }
            assert "Sdk.aar" not in fetched

    def test_vendored_runtime_and_lib_are_skipped(self, runner, tmp_path, monkeypatch):
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        runtimes = (
            PythonAndroidRuntime(
                version="3.14.6",
                abi="arm64_v8a",
                path="vendor/py-arm64.tar.gz",
                sha256="a" * 64,
                min_api=24,
            ),
        )
        lib = LockedAndroidLib(
            name="Sdk.aar",
            kind="aar",
            version="1.0",
            path="vendor/Sdk.aar",
            sha256="c" * 64,
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs, lock=_android_lock(runtimes=runtimes, libs=(lib,)))
            result = runner.invoke(upgrade, ["-p", "android"])
            assert result.exit_code == 0, result.output
            assert fetched == []
            assert "Refreshed 0 artifact(s); 2 vendored (path) entry(ies) skipped." in (
                result.output
            )

    def test_libs_only_skips_the_runtime_entirely(self, runner, tmp_path, monkeypatch):
        """The Android counterpart of --xcframeworks, which upgrade's own error
        message has always pointed at."""
        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        lib = LockedAndroidLib(
            name="Sdk.aar",
            kind="aar",
            version="1.0",
            url="https://example/Sdk.aar",
            sha256="c" * 64,
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs, lock=_android_lock(libs=(lib,)))
            result = runner.invoke(upgrade, ["-p", "android", "--libs"])
            assert result.exit_code == 0, result.output
            assert fetched == ["Sdk.aar"]
            assert "Refreshed 1 artifact(s)" in result.output

    def test_python_and_libs_together_are_rejected(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs)
            result = runner.invoke(upgrade, ["-p", "android", "--python", "--libs"])
            assert result.exit_code != 0
            assert "disjoint halves" in result.output

    def test_libs_flag_rejected_off_android(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(IOS_PYPROJECT, encoding="utf-8")
            (root / "src").mkdir()
            result = runner.invoke(upgrade, ["-p", "ios", "--libs"])
            assert result.exit_code != 0
            assert "--libs is Android-only" in result.output
            assert "--xcframeworks" in result.output

    def test_unknown_name_errors_with_the_known_ones(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs)
            result = runner.invoke(upgrade, ["-p", "android", "--name", "nope"])
            assert result.exit_code != 0
            assert "no artifact named 'nope'" in result.output
            assert "arm64_v8a" in result.output

    def test_xcframeworks_flag_rejected_on_android(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs)
            result = runner.invoke(upgrade, ["-p", "android", "--xcframeworks"])
            assert result.exit_code != 0
            assert "--xcframeworks is iOS-only" in result.output
            assert "--libs" in result.output

    def test_missing_lock_errors(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_android(fs, lock=False)
            result = runner.invoke(upgrade, ["-p", "android"])
            assert result.exit_code != 0
            assert "kivyforge lock -p android" in result.output

    def test_corrupt_lock_wrapped_as_toolchain_error(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = _write_android(fs)
            (root / "pylock.android.toml").write_text(
                "not valid toml [[[", encoding="utf-8"
            )
            result = runner.invoke(upgrade, ["-p", "android"])
            assert result.exit_code != 0
            assert "pylock.android.toml" in result.output


class TestUpgradeUnsupportedPlatform:
    def test_unsupported_platform_dispatch_errors(self, runner, tmp_path, monkeypatch):
        class _FakeBackend:
            name = "amiga"

        monkeypatch.setattr(
            upgrade_mod,
            "resolve_target",
            lambda cli_platform, verb: (_FakeBackend(), tmp_path),
        )
        result = runner.invoke(upgrade, [])
        assert result.exit_code != 0
        assert "does not support platform 'amiga'" in result.output


IOS_PYPROJECT = (
    textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.15"
        dependencies = ["kivy"]

        [tool.kivy]
        app_dir = "src"

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


class TestUpgradeIosCorruptLock:
    def test_corrupt_ios_lock_wrapped_as_toolchain_error(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(IOS_PYPROJECT, encoding="utf-8")
            (root / "src").mkdir()
            (root / "pylock.ios.toml").write_text(
                "not valid toml [[[", encoding="utf-8"
            )
            result = runner.invoke(upgrade, [])
            assert result.exit_code != 0
            assert "pylock.ios.toml" in result.output


WINDOWS_PYPROJECT = (
    textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"

        [tool.kivy]
        app_dir = "src"
        entry_point = "main"

        [tool.kivy.windows]
        schema_version = 1
        app_id = "Example.MyApp"

        [tool.kivy.windows.python]
        version = "3.13"
        """
    ).strip()
    + "\n"
)


def _windows_runtime_lock(text: str) -> WheelRuntimeLock:
    return WheelRuntimeLock(
        platform="windows",
        requires_python=">=3.13",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.13.14",
            artifacts=(
                RuntimeArtifact(
                    arch="x86_64",
                    url="https://example/cpython-x86_64.tar.gz",
                    sha256="c" * 64,
                ),
            ),
        ),
        archs=("x86_64",),
        kivyforge_version="3.0.0.dev0",
        generated_at="t",
        pyproject_sha256=compute_pyproject_sha256(text),
        tool_kivyforge_schema_version=1,
    )


class TestUpgradeWindowsWheelruntime:
    def test_windows_refreshes_runtime(self, runner, tmp_path, monkeypatch):
        from kivyforge.platforms.windows.lock import dumps as dumps_windows

        fetched = []
        monkeypatch.setattr(
            upgrade_mod,
            "fetch_artifact",
            lambda *, name, **kw: fetched.append(name) or Path("/x"),
        )
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(WINDOWS_PYPROJECT, encoding="utf-8")
            (root / "src").mkdir()
            (root / "pylock.windows.toml").write_text(
                dumps_windows(_windows_runtime_lock(WINDOWS_PYPROJECT)),
                encoding="utf-8",
            )
            result = runner.invoke(upgrade, ["-p", "windows"])
            assert result.exit_code == 0, result.output
            assert fetched == ["python-runtime-x86_64"]

    def test_windows_corrupt_lock_wrapped_as_toolchain_error(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(WINDOWS_PYPROJECT, encoding="utf-8")
            (root / "src").mkdir()
            (root / "pylock.windows.toml").write_text(
                "not valid toml [[[", encoding="utf-8"
            )
            result = runner.invoke(upgrade, ["-p", "windows"])
            assert result.exit_code != 0
            assert "pylock.windows.toml" in result.output

    def test_download_error_surfaces_for_desktop_runtime(
        self, runner, tmp_path, monkeypatch
    ):
        from kivyforge.platforms.windows.lock import dumps as dumps_windows

        def boom(*, name, **kw):
            raise DownloadError("network down")

        monkeypatch.setattr(upgrade_mod, "fetch_artifact", boom)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(WINDOWS_PYPROJECT, encoding="utf-8")
            (root / "src").mkdir()
            (root / "pylock.windows.toml").write_text(
                dumps_windows(_windows_runtime_lock(WINDOWS_PYPROJECT)),
                encoding="utf-8",
            )
            result = runner.invoke(upgrade, ["-p", "windows"])
            assert result.exit_code != 0
            assert "network down" in result.output
