"""adb/emulator device-selection logic against a fake adb layer (android/06)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kivyforge.platforms.android import adb as adb_mod


@pytest.fixture
def fake_adb(monkeypatch):
    """Replace connected_devices / available_avds / boot_emulator with fakes."""
    state = {"devices": [], "avds": [], "booted": None}

    monkeypatch.setattr(adb_mod, "connected_devices", lambda: list(state["devices"]))
    monkeypatch.setattr(adb_mod, "available_avds", lambda: list(state["avds"]))

    def _boot(avd):
        serial = f"emulator-{5554 + len(state['devices'])}"
        state["devices"].append(serial)
        state["booted"] = avd
        return serial

    monkeypatch.setattr(adb_mod, "boot_emulator", _boot)
    return state


class TestResolveDevice:
    def test_explicit_serial(self, fake_adb):
        fake_adb["devices"] = ["emulator-5554", "ABC123"]
        assert adb_mod.resolve_device(serial="ABC123") == "ABC123"

    def test_explicit_serial_absent_errors(self, fake_adb):
        fake_adb["devices"] = ["emulator-5554"]
        with pytest.raises(adb_mod.AdbError, match="not a connected device"):
            adb_mod.resolve_device(serial="NOPE")

    def test_single_physical_device_auto(self, fake_adb):
        fake_adb["devices"] = ["ABC123"]
        assert adb_mod.resolve_device() == "ABC123"

    def test_multiple_physical_requires_serial(self, fake_adb):
        fake_adb["devices"] = ["ABC123", "DEF456"]
        with pytest.raises(adb_mod.AdbError, match="multiple devices"):
            adb_mod.resolve_device()

    def test_existing_emulator_reused(self, fake_adb):
        fake_adb["devices"] = ["emulator-5554"]
        assert adb_mod.resolve_device(prefer_emulator=True) == "emulator-5554"

    def test_boots_named_avd_when_none_connected(self, fake_adb):
        fake_adb["avds"] = ["Pixel_API_35", "kivyforge_x86_64"]
        result = adb_mod.resolve_device(prefer_emulator=True, avd="kivyforge_x86_64")
        assert result == "emulator-5554"
        assert fake_adb["booted"] == "kivyforge_x86_64"

    def test_boots_first_avd_when_unspecified(self, fake_adb):
        fake_adb["avds"] = ["OnlyAvd"]
        adb_mod.resolve_device(prefer_emulator=True)
        assert fake_adb["booted"] == "OnlyAvd"

    def test_unknown_avd_errors(self, fake_adb):
        fake_adb["avds"] = ["Real"]
        with pytest.raises(adb_mod.AdbError, match="not found"):
            adb_mod.resolve_device(avd="Ghost")

    def test_no_device_no_avd_errors(self, fake_adb):
        with pytest.raises(adb_mod.AdbError, match="no device attached"):
            adb_mod.resolve_device()


class TestParsing:
    def test_connected_devices_parses_adb_output(self, monkeypatch):
        out = (
            "List of devices attached\n"
            "emulator-5554\tdevice\n"
            "ABC123\tdevice\n"
            "OFFLINE1\toffline\n"
            "\n"
        )
        monkeypatch.setattr(adb_mod, "adb", lambda *a, **k: out)
        assert adb_mod.connected_devices() == ["emulator-5554", "ABC123"]


class TestSdkTool:
    def test_found_in_sdk_root(self, tmp_path, monkeypatch):
        tool_dir = tmp_path / "platform-tools"
        tool_dir.mkdir()
        exe_name = f"adb{adb_mod._EXE}"
        (tool_dir / exe_name).write_text("x", encoding="utf-8")
        monkeypatch.setattr(adb_mod, "_sdk_root", lambda: tmp_path)
        assert adb_mod.sdk_tool("adb", subdir="platform-tools") == str(
            tool_dir / exe_name
        )

    def test_falls_back_to_path_when_missing_from_sdk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(adb_mod, "_sdk_root", lambda: tmp_path)
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/adb")
        assert adb_mod.sdk_tool("adb", subdir="platform-tools") == "/usr/bin/adb"

    def test_falls_back_to_path_when_no_sdk_root(self, monkeypatch):
        monkeypatch.setattr(adb_mod, "_sdk_root", lambda: None)
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/adb")
        assert adb_mod.sdk_tool("adb", subdir="platform-tools") == "/usr/bin/adb"

    def test_raises_when_nowhere_to_be_found(self, monkeypatch):
        monkeypatch.setattr(adb_mod, "_sdk_root", lambda: None)
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(adb_mod.AdbError, match="not found"):
            adb_mod.sdk_tool("adb", subdir="platform-tools")


class TestSdkRoot:
    def test_delegates_to_real_probe(self, monkeypatch, tmp_path):
        from kivyforge.platforms.android.doctor import RealAndroidProbe

        monkeypatch.setattr(RealAndroidProbe, "sdk_root", lambda self: tmp_path)
        assert adb_mod._sdk_root() == tmp_path


class TestAdbFunction:
    def _stub_tool(self, monkeypatch):
        monkeypatch.setattr(adb_mod, "sdk_tool", lambda name, *, subdir: "adb")

    def test_success_returns_stdout(self, monkeypatch):
        self._stub_tool(monkeypatch)
        captured = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

        monkeypatch.setattr(adb_mod.subprocess, "run", fake_run)
        assert adb_mod.adb("devices") == "ok\n"
        assert captured["cmd"] == ["adb", "devices"]

    def test_serial_inserted_before_args(self, monkeypatch):
        self._stub_tool(monkeypatch)
        captured = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(adb_mod.subprocess, "run", fake_run)
        adb_mod.adb("shell", "echo", "hi", serial="ABC123")
        assert captured["cmd"] == ["adb", "-s", "ABC123", "shell", "echo", "hi"]

    def test_nonzero_exit_raises_when_checked(self, monkeypatch):
        self._stub_tool(monkeypatch)

        def fake_run(cmd, capture_output, text):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no device")

        monkeypatch.setattr(adb_mod.subprocess, "run", fake_run)
        with pytest.raises(adb_mod.AdbError, match="no device"):
            adb_mod.adb("shell", "true")

    def test_nonzero_exit_ignored_when_unchecked(self, monkeypatch):
        self._stub_tool(monkeypatch)

        def fake_run(cmd, capture_output, text):
            return subprocess.CompletedProcess(cmd, 1, stdout="partial", stderr="")

        monkeypatch.setattr(adb_mod.subprocess, "run", fake_run)
        assert adb_mod.adb("shell", "true", check=False) == "partial"


class TestAvailableAvds:
    def test_parses_and_strips_blank_lines(self, monkeypatch):
        monkeypatch.setattr(adb_mod, "sdk_tool", lambda name, *, subdir: "emulator")

        def fake_run(cmd, capture_output, text):
            return subprocess.CompletedProcess(
                cmd, 0, stdout="Pixel_API_35\n\nkivyforge_x86_64\n  \n", stderr=""
            )

        monkeypatch.setattr(adb_mod.subprocess, "run", fake_run)
        assert adb_mod.available_avds() == ["Pixel_API_35", "kivyforge_x86_64"]


class TestBootEmulator:
    def _no_sleep(self, monkeypatch):
        monkeypatch.setattr(adb_mod.time, "sleep", lambda _s: None)

    def _stub_popen(self, monkeypatch):
        monkeypatch.setattr(
            adb_mod.subprocess,
            "Popen",
            lambda *a, **k: None,
        )

    def test_returns_serial_once_booted(self, monkeypatch):
        self._no_sleep(monkeypatch)
        self._stub_popen(monkeypatch)
        monkeypatch.setattr(adb_mod, "sdk_tool", lambda name, *, subdir: "emulator")
        devices_seq = iter([[], ["emulator-5554"], ["emulator-5554"]])
        monkeypatch.setattr(
            adb_mod,
            "connected_devices",
            lambda: next(devices_seq, ["emulator-5554"]),
        )
        monkeypatch.setattr(adb_mod, "adb", lambda *a, **k: "1")
        assert adb_mod.boot_emulator("kivyforge_x86_64") == "emulator-5554"

    def test_waits_for_boot_completed_before_returning(self, monkeypatch):
        self._no_sleep(monkeypatch)
        self._stub_popen(monkeypatch)
        monkeypatch.setattr(adb_mod, "sdk_tool", lambda name, *, subdir: "emulator")
        # First call captures the pre-boot device set (empty); every call after
        # that sees the new emulator serial already attached.
        calls = {"n": 0}

        def fake_connected():
            calls["n"] += 1
            return [] if calls["n"] == 1 else ["emulator-5554"]

        monkeypatch.setattr(adb_mod, "connected_devices", fake_connected)
        boot_calls = iter(["0", "0", "1"])
        monkeypatch.setattr(adb_mod, "adb", lambda *a, **k: next(boot_calls))
        assert adb_mod.boot_emulator("kivyforge_x86_64") == "emulator-5554"

    def test_timeout_raises(self, monkeypatch):
        self._no_sleep(monkeypatch)
        self._stub_popen(monkeypatch)
        monkeypatch.setattr(adb_mod, "sdk_tool", lambda name, *, subdir: "emulator")
        monkeypatch.setattr(adb_mod, "BOOT_TIMEOUT_SEC", 0)
        monkeypatch.setattr(adb_mod, "connected_devices", lambda: [])
        with pytest.raises(adb_mod.AdbError, match="did not finish booting"):
            adb_mod.boot_emulator("kivyforge_x86_64")


class TestDeviceCommands:
    def test_install_apk(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            adb_mod, "adb", lambda *a, **k: captured.update(args=a, kw=k)
        )
        apk = Path("/tmp/app.apk")
        adb_mod.install_apk("ABC123", apk)
        assert captured["args"] == ("install", "-r", str(apk))
        assert captured["kw"] == {"serial": "ABC123"}

    def test_launch(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            adb_mod, "adb", lambda *a, **k: captured.update(args=a, kw=k)
        )
        adb_mod.launch("ABC123", "org.example.app", ".MainActivity")
        assert captured["args"] == (
            "shell",
            "am",
            "start",
            "-n",
            "org.example.app/.MainActivity",
        )
        assert captured["kw"] == {"serial": "ABC123"}

    def test_force_stop(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            adb_mod, "adb", lambda *a, **k: captured.update(args=a, kw=k)
        )
        adb_mod.force_stop("ABC123", "org.example.app")
        assert captured["args"] == ("shell", "am", "force-stop", "org.example.app")
        assert captured["kw"] == {"serial": "ABC123", "check": False}

    def test_logcat_dump(self, monkeypatch):
        monkeypatch.setattr(adb_mod, "adb", lambda *a, **k: "log output")
        assert adb_mod.logcat_dump("ABC123") == "log output"

    def test_logcat_clear(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            adb_mod, "adb", lambda *a, **k: captured.update(args=a, kw=k)
        )
        adb_mod.logcat_clear("ABC123")
        assert captured["args"] == ("logcat", "-c")
        assert captured["kw"] == {"serial": "ABC123", "check": False}
