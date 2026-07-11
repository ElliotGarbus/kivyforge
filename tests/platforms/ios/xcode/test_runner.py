"""Phase 6 — process funnel + simctl/devicectl/open argv builders."""

from __future__ import annotations

import pytest

from kivyforge.platforms.ios.xcode.runner import (
    CommandError,
    devicectl_install,
    devicectl_launch,
    devicectl_list_json,
    open_command,
    parse_devicectl_devices,
    parse_simctl_devices,
    pick_device,
    pick_simulator,
    resolve_device_destination,
    resolve_simulator_destination,
    run_command,
    simctl_boot,
    simctl_install,
    simctl_launch,
)


class _Proc:
    def __init__(self, rc, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


class TestRunCommand:
    def test_success_returns_proc(self):
        proc = run_command(["true"], runner=lambda *a, **k: _Proc(0, "ok"))
        assert proc.stdout == "ok"

    def test_failure_raises(self):
        with pytest.raises(CommandError) as exc:
            run_command(["false"], runner=lambda *a, **k: _Proc(2, err="boom"))
        assert exc.value.returncode == 2
        assert "boom" in str(exc.value)

    def test_failure_keeps_stdout_when_stderr_also_present(self):
        # Regression: xcodebuild sends its destination-matching warning to
        # stderr and the real `error:` diagnostics to stdout. Both must
        # survive into the raised CommandError, not just stderr.
        with pytest.raises(CommandError) as exc:
            run_command(
                ["xcodebuild"],
                runner=lambda *a, **k: _Proc(
                    65,
                    out="error: No profiles for 'org.x' were found",
                    err="xcodebuild: WARNING: Using the first of multiple "
                    "matching destinations",
                ),
            )
        message = str(exc.value)
        assert "No profiles for 'org.x' were found" in message
        assert "WARNING: Using the first of multiple" in message

    def test_check_false_swallows(self):
        proc = run_command(["x"], runner=lambda *a, **k: _Proc(1, "out"), check=False)
        assert proc.returncode == 1


class TestArgvBuilders:
    def test_open(self, tmp_path):
        assert open_command(tmp_path / "x.xcodeproj") == [
            "open",
            str(tmp_path / "x.xcodeproj"),
        ]

    def test_simctl(self):
        assert simctl_boot("UDID")[:3] == ["xcrun", "simctl", "boot"]
        assert simctl_install("UDID", "/a.app")[-1] == "/a.app"
        launch = simctl_launch("UDID", "org.x.app")
        assert "--console-pty" in launch
        assert launch[-2:] == ["UDID", "org.x.app"]

    def test_simctl_launch_no_console(self):
        assert "--console-pty" not in simctl_launch("U", "b", console=False)

    def test_devicectl(self):
        inst = devicectl_install("UDID", "/a.app")
        assert inst[:4] == ["xcrun", "devicectl", "device", "install"]
        assert "--device" in inst
        launch = devicectl_launch("UDID", "org.x.app")
        assert launch[:5] == [
            "xcrun",
            "devicectl",
            "device",
            "process",
            "launch",
        ]
        assert launch[-1] == "org.x.app"


class TestSimulatorSelection:
    _PAYLOAD = {
        "devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-17-2": [
                {
                    "udid": "OLD-UDID",
                    "name": "iPhone 15",
                    "state": "Shutdown",
                    "isAvailable": True,
                }
            ],
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [
                {
                    "udid": "NEW-UDID",
                    "name": "iPhone 17",
                    "state": "Shutdown",
                    "isAvailable": True,
                },
                {
                    "udid": "BOOT-UDID",
                    "name": "iPhone 15 Pro",
                    "state": "Booted",
                    "isAvailable": True,
                },
            ],
        }
    }

    def test_parse_devices(self):
        devices = parse_simctl_devices(self._PAYLOAD)
        assert len(devices) == 3
        assert devices[0].runtime == "17.2"

    def test_pick_booted_simulator(self):
        devices = parse_simctl_devices(self._PAYLOAD)
        picked = pick_simulator(devices)
        assert picked.udid == "BOOT-UDID"

    def test_pick_newest_iphone_when_none_booted(self):
        payload = {
            "devices": {
                k: [d for d in v if d["state"] != "Booted"]
                for k, v in self._PAYLOAD["devices"].items()
            }
        }
        devices = parse_simctl_devices(payload)
        picked = pick_simulator(devices)
        assert picked.udid == "NEW-UDID"

    def test_pick_by_name(self):
        devices = parse_simctl_devices(self._PAYLOAD)
        picked = pick_simulator(devices, "iPhone 15")
        assert picked.udid == "OLD-UDID"

    def test_resolve_boots_default(self):
        calls: list[list[str]] = []

        def fake(argv, capture_output=True, text=True):
            calls.append(argv)
            if "-j" in argv:
                import json

                return _Proc(0, json.dumps(self._PAYLOAD))
            return _Proc(0)

        device = resolve_simulator_destination(None, runner=fake)
        assert device.udid == "BOOT-UDID"
        assert simctl_boot("x")[:3] == ["xcrun", "simctl", "boot"]  # sanity
        assert not any(c[:3] == ["xcrun", "simctl", "boot"] for c in calls)

    def test_resolve_boots_shutdown_default(self):
        payload = {
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [
                    {
                        "udid": "NEW-UDID",
                        "name": "iPhone 17",
                        "state": "Shutdown",
                        "isAvailable": True,
                    }
                ]
            }
        }
        calls: list[list[str]] = []

        def fake(argv, capture_output=True, text=True):
            calls.append(argv)
            if "-j" in argv:
                import json

                return _Proc(0, json.dumps(payload))
            return _Proc(0)

        device = resolve_simulator_destination(None, runner=fake)
        assert device.udid == "NEW-UDID"
        assert ["xcrun", "simctl", "boot", "NEW-UDID"] in calls
        assert ["open", "-a", "Simulator"] in calls


class TestDeviceSelection:
    _PAYLOAD = {
        "result": {
            "devices": [
                {
                    "identifier": "WATCH-ID",
                    "deviceProperties": {"name": "Elliot's Apple Watch"},
                    "hardwareProperties": {"platform": "watchOS"},
                    "connectionProperties": {
                        "tunnelState": "disconnected",
                        "pairingState": "paired",
                    },
                },
                {
                    "identifier": "IPHONE-ID",
                    "deviceProperties": {"name": "Elliot's iPhone"},
                    "hardwareProperties": {"platform": "iOS"},
                    "connectionProperties": {
                        "tunnelState": "connected",
                        "pairingState": "paired",
                    },
                },
            ]
        }
    }

    def test_parse_devices(self):
        devices = parse_devicectl_devices(self._PAYLOAD)
        assert len(devices) == 2
        assert devices[1].platform == "iOS"
        assert devices[1].tunnel_state == "connected"
        assert devices[1].pairing_state == "paired"

    def test_pick_sole_paired_ios_device(self):
        devices = parse_devicectl_devices(self._PAYLOAD)
        picked = pick_device(devices)
        assert picked.identifier == "IPHONE-ID"

    def test_pick_ignores_paired_watch(self):
        # A paired Apple Watch is not an iOS device and must never be
        # silently auto-selected.
        devices = parse_devicectl_devices(self._PAYLOAD)
        assert all(d.identifier != "WATCH-ID" or d.platform != "iOS" for d in devices)

    def test_pick_ios_device_with_no_active_tunnel(self):
        # Regression: with Xcode closed, a plugged-in/paired iPhone reports
        # tunnelState "disconnected" (no CoreDevice client has a tunnel open
        # yet) — it must still be picked; devicectl opens the tunnel itself
        # on install/launch.
        payload = {
            "result": {
                "devices": [
                    {
                        "identifier": "IPHONE-ID",
                        "deviceProperties": {"name": "Elliot's iPhone"},
                        "hardwareProperties": {"platform": "iOS"},
                        "connectionProperties": {
                            "tunnelState": "disconnected",
                            "pairingState": "paired",
                        },
                    }
                ]
            }
        }
        devices = parse_devicectl_devices(payload)
        picked = pick_device(devices)
        assert picked.identifier == "IPHONE-ID"

    def test_pick_by_explicit_name(self):
        devices = parse_devicectl_devices(self._PAYLOAD)
        picked = pick_device(devices, "Elliot's iPhone")
        assert picked.identifier == "IPHONE-ID"

    def test_pick_no_devices_raises(self):
        with pytest.raises(CommandError):
            pick_device([])

    def test_pick_no_paired_device_raises(self):
        payload = {
            "result": {
                "devices": [
                    {
                        "identifier": "IPHONE-ID",
                        "deviceProperties": {"name": "Elliot's iPhone"},
                        "hardwareProperties": {"platform": "iOS"},
                        "connectionProperties": {
                            "tunnelState": "disconnected",
                            "pairingState": "unpaired",
                        },
                    }
                ]
            }
        }
        devices = parse_devicectl_devices(payload)
        with pytest.raises(CommandError, match="no paired iOS device"):
            pick_device(devices)

    def test_pick_multiple_paired_raises(self):
        payload = {
            "result": {
                "devices": [
                    {
                        "identifier": "A",
                        "deviceProperties": {"name": "iPhone A"},
                        "hardwareProperties": {"platform": "iOS"},
                        "connectionProperties": {
                            "tunnelState": "connected",
                            "pairingState": "paired",
                        },
                    },
                    {
                        "identifier": "B",
                        "deviceProperties": {"name": "iPhone B"},
                        "hardwareProperties": {"platform": "iOS"},
                        "connectionProperties": {
                            "tunnelState": "disconnected",
                            "pairingState": "paired",
                        },
                    },
                ]
            }
        }
        devices = parse_devicectl_devices(payload)
        with pytest.raises(CommandError, match="multiple paired"):
            pick_device(devices)

    def test_resolve_device_destination_writes_and_reads_json(self):
        import json

        calls: list[list[str]] = []

        def fake(argv, capture_output=True, text=True):
            calls.append(argv)
            assert argv[:4] == ["xcrun", "devicectl", "list", "devices"]
            output_path = argv[-1]
            with open(output_path, "w") as fh:
                json.dump(self._PAYLOAD, fh)
            return _Proc(0)

        device = resolve_device_destination(None, runner=fake)
        assert device.identifier == "IPHONE-ID"
        assert calls and "-j" in calls[0]

    def test_devicectl_list_json_argv(self):
        argv = devicectl_list_json("/tmp/out.json")
        assert argv == ["xcrun", "devicectl", "list", "devices", "-j", "/tmp/out.json"]
