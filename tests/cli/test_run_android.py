"""``kivyforge run`` — Android branch dispatch (android-only flags, list-devices,
smoke, and android_run delegation) with the backend/target resolution and the
Android collaborators mocked (spec 05 / android/06 §run).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from kivyforge.cli.run import run as run_cmd
from kivyforge.platforms.android import adb as adb_mod
from kivyforge.platforms.android import cli as android_cli_mod


class _FakeBackend:
    def __init__(self, name: str):
        self.name = name
        self.run_calls: list[dict] = []

    def run(self, project_root, **kwargs):
        self.run_calls.append({"project_root": project_root, **kwargs})


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fake_project_root(tmp_path):
    return tmp_path


def _patch_resolve_target(monkeypatch, backend, project_root):
    import kivyforge.cli.run as run_mod

    monkeypatch.setattr(
        run_mod, "resolve_target", lambda cli_platform, verb: (backend, project_root)
    )


class TestAndroidOnlyFlagsGuard:
    @pytest.mark.parametrize(
        "flag",
        ["--emulator", "--serial=ABC123", "--smoke", "--release", "--avd=Pixel"],
    )
    def test_android_only_flag_rejected_on_other_backends(
        self, runner, fake_project_root, monkeypatch, flag
    ):
        backend = _FakeBackend("macos")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        result = runner.invoke(run_cmd, [flag])
        assert result.exit_code != 0
        assert "Android-only" in result.output

    def test_multiple_flags_pluralised_message(
        self, runner, fake_project_root, monkeypatch
    ):
        backend = _FakeBackend("macos")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        result = runner.invoke(run_cmd, ["--emulator", "--smoke"])
        assert result.exit_code != 0
        assert "are" in result.output
        assert "Android-only" in result.output

    def test_android_backend_allows_android_only_flags(
        self, runner, fake_project_root, monkeypatch
    ):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        monkeypatch.setattr(
            android_cli_mod, "android_run", lambda project_root, **kw: None
        )
        monkeypatch.setattr(
            android_cli_mod, "android_smoke", lambda project_root, **kw: None
        )
        result = runner.invoke(run_cmd, ["--emulator"])
        assert result.exit_code == 0, result.output


class TestAndroidListDevices:
    def test_prints_devices_and_avds(self, runner, fake_project_root, monkeypatch):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        monkeypatch.setattr(
            adb_mod, "connected_devices", lambda: ["emulator-5554", "ABC123"]
        )
        monkeypatch.setattr(adb_mod, "available_avds", lambda: ["Pixel_API_35"])
        result = runner.invoke(run_cmd, ["--list-devices"])
        assert result.exit_code == 0, result.output
        assert "emulator-5554, ABC123" in result.output
        assert "Pixel_API_35" in result.output

    def test_none_when_nothing_available(self, runner, fake_project_root, monkeypatch):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        monkeypatch.setattr(adb_mod, "connected_devices", lambda: [])
        monkeypatch.setattr(adb_mod, "available_avds", lambda: [])
        result = runner.invoke(run_cmd, ["--list-devices"])
        assert result.exit_code == 0, result.output
        assert "Devices: none" in result.output
        assert "AVDs: none" in result.output


class TestAndroidSmoke:
    def test_smoke_delegates_with_expected_kwargs(
        self, runner, fake_project_root, monkeypatch
    ):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        captured = {}

        def fake_smoke(project_root, **kwargs):
            captured["project_root"] = project_root
            captured.update(kwargs)

        monkeypatch.setattr(android_cli_mod, "android_smoke", fake_smoke)
        result = runner.invoke(
            run_cmd,
            [
                "--smoke",
                "--release",
                "--arch",
                "arm64_v8a",
                "--serial",
                "ABC123",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured["project_root"] == fake_project_root
        assert captured["release"] is True
        assert captured["abi"] == "arm64_v8a"
        assert captured["serial"] == "ABC123"
        assert captured["prefer_emulator"] is False

    def test_smoke_prefers_emulator_when_avd_given(
        self, runner, fake_project_root, monkeypatch
    ):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        captured = {}
        monkeypatch.setattr(
            android_cli_mod,
            "android_smoke",
            lambda project_root, **kw: captured.update(kw),
        )
        result = runner.invoke(run_cmd, ["--smoke", "--avd", "Pixel_API_35"])
        assert result.exit_code == 0, result.output
        assert captured["avd"] == "Pixel_API_35"
        assert captured["prefer_emulator"] is True


class TestAndroidRun:
    def test_run_delegates_with_expected_kwargs(
        self, runner, fake_project_root, monkeypatch
    ):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        captured = {}

        def fake_run(project_root, **kwargs):
            captured["project_root"] = project_root
            captured.update(kwargs)

        monkeypatch.setattr(android_cli_mod, "android_run", fake_run)
        result = runner.invoke(
            run_cmd, ["--no-build", "--arch", "x86_64", "--destination", "OTHER456"]
        )
        assert result.exit_code == 0, result.output
        assert captured["project_root"] == fake_project_root
        assert captured["no_build"] is True
        assert captured["abi"] == "x86_64"
        # --serial not given, so --destination is used as the adb serial.
        assert captured["serial"] == "OTHER456"
        assert captured["prefer_emulator"] is False

    def test_explicit_serial_wins_over_destination(
        self, runner, fake_project_root, monkeypatch
    ):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        captured = {}
        monkeypatch.setattr(
            android_cli_mod,
            "android_run",
            lambda project_root, **kw: captured.update(kw),
        )
        result = runner.invoke(
            run_cmd, ["--serial", "ABC123", "--destination", "OTHER456"]
        )
        assert result.exit_code == 0, result.output
        assert captured["serial"] == "ABC123"


class TestAndroidDeviceSelector:
    """`--device` is documented as Android's `--emulator` counterpart, so it has
    to reach the backend rather than being silently ignored."""

    def _captured_run(self, runner, project_root, monkeypatch, argv):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, project_root)
        captured: dict = {}
        monkeypatch.setattr(
            android_cli_mod,
            "android_run",
            lambda project_root, **kw: captured.update(kw),
        )
        return runner.invoke(run_cmd, argv), captured

    def test_device_requires_a_physical_target(
        self, runner, fake_project_root, monkeypatch
    ):
        result, captured = self._captured_run(
            runner, fake_project_root, monkeypatch, ["--device"]
        )
        assert result.exit_code == 0, result.output
        assert captured["require_physical"] is True
        assert captured["prefer_emulator"] is False

    def test_default_auto_selects(self, runner, fake_project_root, monkeypatch):
        """No selector: adb's own rules apply (a single attached device, else an
        AVD), so nothing is forced."""
        result, captured = self._captured_run(
            runner, fake_project_root, monkeypatch, []
        )
        assert result.exit_code == 0, result.output
        assert captured["require_physical"] is False
        assert captured["prefer_emulator"] is False

    def test_device_and_emulator_are_mutually_exclusive(
        self, runner, fake_project_root, monkeypatch
    ):
        result, _ = self._captured_run(
            runner, fake_project_root, monkeypatch, ["--device", "--emulator"]
        )
        assert result.exit_code != 0
        assert "opposite targets" in result.output

    def test_device_with_avd_is_rejected(self, runner, fake_project_root, monkeypatch):
        result, _ = self._captured_run(
            runner, fake_project_root, monkeypatch, ["--device", "--avd", "Pixel"]
        )
        assert result.exit_code != 0
        assert "--avd names an emulator" in result.output

    def test_explicit_simulator_is_rejected_on_android(
        self, runner, fake_project_root, monkeypatch
    ):
        result, _ = self._captured_run(
            runner, fake_project_root, monkeypatch, ["--simulator"]
        )
        assert result.exit_code != 0
        assert "--simulator is iOS-only" in result.output
        assert "--emulator" in result.output

    def test_device_reaches_smoke_too(self, runner, fake_project_root, monkeypatch):
        backend = _FakeBackend("android")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        captured: dict = {}
        monkeypatch.setattr(
            android_cli_mod,
            "android_smoke",
            lambda project_root, **kw: captured.update(kw),
        )
        result = runner.invoke(run_cmd, ["--smoke", "--device"])
        assert result.exit_code == 0, result.output
        assert captured["require_physical"] is True


class TestNonAndroidRunStillDelegates:
    def test_non_android_backend_run_called(
        self, runner, fake_project_root, monkeypatch
    ):
        backend = _FakeBackend("macos")
        _patch_resolve_target(monkeypatch, backend, fake_project_root)
        result = runner.invoke(run_cmd, ["--arch", "arm64"])
        assert result.exit_code == 0, result.output
        assert len(backend.run_calls) == 1
        call = backend.run_calls[0]
        assert call["project_root"] == fake_project_root
        assert call["arch"] == "arm64"
