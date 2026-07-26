"""AndroidPlatform registration + shell behavior (Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kivyforge.platforms import get_platform, resolve_target
from kivyforge.platforms.android import AndroidPlatform


class TestRegistration:
    def test_registered(self):
        backend = get_platform("android")
        assert isinstance(backend, AndroidPlatform)
        assert backend.package_formats == ("apk", "aab")
        assert backend.default_package_format == "apk"

    def test_never_a_host_default(self):
        # Cross-compiled target: no host maps to it (resolution-chain step 3),
        # even when the overlay is configured.
        assert AndroidPlatform.host_system is None
        with pytest.raises(Exception):
            resolve_target(None, configured={"android"}, env={}, host_system="Windows")

    def test_explicit_selection_works(self):
        backend = resolve_target(
            "android", configured=set(), env={}, host_system="Linux"
        )
        assert backend.name == "android"

    def test_env_selection_works(self):
        backend = resolve_target(
            None,
            configured=set(),
            env={"KIVYFORGE_PLATFORM": "android"},
            host_system="Darwin",
        )
        assert backend.name == "android"

    def test_any_host_is_capable(self):
        backend = AndroidPlatform()
        for host in ("Windows", "Darwin", "Linux"):
            backend.check_host_capability(host_system=host)  # must not raise

    def test_status_without_config_is_actionable(self, tmp_path: Path):
        from kivyforge.platforms.android import AndroidBuildError

        backend = AndroidPlatform()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "1.0.0"\n[tool.kivy]\napp_dir = "src"\n',
            encoding="utf-8",
        )
        with pytest.raises(AndroidBuildError, match="tool.kivy.android"):
            backend.status(tmp_path)

    def test_build_without_config_is_actionable(self, tmp_path: Path):
        from kivyforge.platforms.android import AndroidBuildError

        backend = AndroidPlatform()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "1.0.0"\n[tool.kivy]\napp_dir = "src"\n',
            encoding="utf-8",
        )
        with pytest.raises(AndroidBuildError, match="tool.kivy.android"):
            backend.build(
                tmp_path,
                target=None,
                arch=None,
                no_verify_lock=False,
                no_cache=False,
                team_id=None,
                signing_identity=None,
                export_method="debugging",
            )


class TestDoctorStub:
    def test_environment_mode_runs(self, tmp_path: Path):
        backend = AndroidPlatform()
        results = backend.doctor(tmp_path, kivyforge_version="0.0-test", offline=True)
        names = [r.name for r in results]
        assert names[0] == "kivyforge"
        assert "JDK" in names and "Android SDK" in names and "NDK" in names

    def test_project_mode_reports_config(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "app"',
                    'version = "1.0.0"',
                    "[tool.kivy]",
                    'app_dir = "src"',
                    "[tool.kivy.android]",
                    "schema_version = 1",
                    'package = "org.example.app"',
                    "[tool.kivy.android.python]",
                    'version = "3.14.6"',
                ]
            ),
            encoding="utf-8",
        )
        backend = AndroidPlatform()
        results = backend.doctor(tmp_path, kivyforge_version="0.0-test", offline=True)
        by_name = {r.name: r for r in results}
        assert by_name["Android config"].status.value == "PASS"
        assert "org.example.app" in by_name["Android config"].detail
        assert by_name["App source directory"].status.value == "PASS"

    def test_project_mode_reports_config_error(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "app"',
                    'version = "1.0.0"',
                    "[tool.kivy]",
                    'app_dir = "src"',
                    "[tool.kivy.android]",
                    "schema_version = 1",
                    'package = "nodots"',  # invalid
                ]
            ),
            encoding="utf-8",
        )
        backend = AndroidPlatform()
        results = backend.doctor(tmp_path, kivyforge_version="0.0-test", offline=True)
        by_name = {r.name: r for r in results}
        assert by_name["Android config"].status.value == "FAIL"
