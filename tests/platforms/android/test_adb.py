"""adb/emulator device-selection logic against a fake adb layer (android/06)."""

from __future__ import annotations

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
