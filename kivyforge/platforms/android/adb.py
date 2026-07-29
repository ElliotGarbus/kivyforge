"""adb / emulator integration (android/06 §run).

Device selection: an explicit ``--serial`` wins; else the single connected
device; else boot the named (or only) AVD and wait for ``sys.boot_completed``.
All paths resolve tools from the detected SDK so no PATH setup is required.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

_EXE = ".exe" if os.name == "nt" else ""
BOOT_TIMEOUT_SEC = 300


def _sdk_root() -> Path | None:
    from .doctor import RealAndroidProbe

    return RealAndroidProbe().sdk_root()


class AdbError(Exception):
    pass


def sdk_tool(name: str, *, subdir: str) -> str:
    sdk = _sdk_root()
    if sdk is not None:
        candidate = sdk / subdir / f"{name}{_EXE}"
        if candidate.exists():
            return str(candidate)
    import shutil as _shutil

    tool = _shutil.which(name)
    if tool is None:
        raise AdbError(
            f"{name} not found (looked in the SDK's {subdir}/ and PATH); "
            f"run `kivyforge doctor -p android`."
        )
    return tool


def adb(*args: str, serial: str | None = None, check: bool = True) -> str:
    cmd = [sdk_tool("adb", subdir="platform-tools")]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AdbError(f"adb {' '.join(args)} failed:\n{proc.stderr or proc.stdout}")
    return proc.stdout


def connected_devices() -> list[str]:
    out = adb("devices")
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def available_avds() -> list[str]:
    emulator = sdk_tool("emulator", subdir="emulator")
    proc = subprocess.run([emulator, "-list-avds"], capture_output=True, text=True)
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def boot_emulator(avd: str) -> str:
    """Boot ``avd`` headless-friendly; return the emulator serial once booted."""
    before = set(connected_devices())
    emulator = sdk_tool("emulator", subdir="emulator")
    subprocess.Popen(
        [emulator, "-avd", avd, "-no-boot-anim", "-no-audio"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + BOOT_TIMEOUT_SEC
    serial: str | None = None
    while time.monotonic() < deadline:
        new = [d for d in connected_devices() if d not in before]
        if new:
            serial = new[0]
            booted = adb(
                "shell",
                "getprop",
                "sys.boot_completed",
                serial=serial,
                check=False,
            ).strip()
            if booted == "1":
                return serial
        time.sleep(2)
    raise AdbError(
        f"emulator {avd!r} did not finish booting within "
        f"{BOOT_TIMEOUT_SEC}s (serial: {serial or 'never appeared'})."
    )


def resolve_device(
    *,
    prefer_emulator: bool = False,
    require_physical: bool = False,
    serial: str | None = None,
    avd: str | None = None,
) -> str:
    """android/06 selection rules -> a ready adb serial.

    ``require_physical`` is ``run --device``: never fall back to booting an
    emulator, because silently testing on an AVD is the opposite of what the
    user asked for.
    """
    if serial:
        if serial not in connected_devices():
            raise AdbError(
                f"--serial {serial!r} is not a connected device "
                f"(adb devices: {', '.join(connected_devices()) or 'none'})."
            )
        return serial
    devices = connected_devices()
    if require_physical or not prefer_emulator:
        physical = [d for d in devices if not d.startswith("emulator-")]
        if len(physical) == 1:
            return physical[0]
        if len(physical) > 1:
            raise AdbError(
                f"multiple devices attached ({', '.join(physical)}); pass --serial."
            )
        if require_physical:
            attached = ", ".join(devices) or "none"
            raise AdbError(
                "--device asks for a physical device, but adb sees none "
                f"(attached: {attached}). Enable USB debugging and authorize "
                "this host, or drop --device to use an emulator."
            )
    emulators = [d for d in devices if d.startswith("emulator-")]
    if emulators:
        return emulators[0]
    avds = available_avds()
    if avd is None:
        if not avds:
            raise AdbError(
                "no device attached and no AVD exists; create one "
                "(Android Studio Device Manager or avdmanager) or plug in a "
                "device."
            )
        avd = avds[0]
    elif avd not in avds:
        raise AdbError(f"AVD {avd!r} not found (available: {', '.join(avds)}).")
    return boot_emulator(avd)


# The two ABIs kivyforge builds for, keyed by the Android ABI names adb reports.
_ABI_FROM_ANDROID = {"arm64-v8a": "arm64_v8a", "x86_64": "x86_64"}


def device_abi(serial: str) -> str | None:
    """The kivyforge ABI name for ``serial``'s preferred supported ABI.

    Asking the target beats inferring it: an arm64 emulator on Apple Silicon and
    an arm64 phone want the same ABI as an x86_64 AVD does not, and installing
    the wrong one only fails later, as ``INSTALL_FAILED_NO_MATCHING_ABIS``.
    Returns ``None`` when the device reports nothing kivyforge builds for (a
    32-bit-only device), leaving the caller to decide.
    """
    out = adb(
        "shell", "getprop", "ro.product.cpu.abilist", serial=serial, check=False
    ).strip()
    if not out:
        out = adb(
            "shell", "getprop", "ro.product.cpu.abi", serial=serial, check=False
        ).strip()
    for reported in out.split(","):
        mapped = _ABI_FROM_ANDROID.get(reported.strip())
        if mapped:
            return mapped
    return None


def host_abi() -> str:
    """The ABI an emulator runs at native speed on this host.

    The fallback for :func:`device_abi`, and what android/06 documents for
    ``run --emulator``: x86_64 system images on an x86_64 host, arm64 ones on an
    arm64 host such as Apple Silicon.
    """
    import platform

    return (
        "arm64_v8a" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
    )


def install_apk(serial: str, apk: Path) -> None:
    adb("install", "-r", str(apk), serial=serial)


def launch(serial: str, package: str, activity: str) -> None:
    adb("shell", "am", "start", "-n", f"{package}/{activity}", serial=serial)


def force_stop(serial: str, package: str) -> None:
    adb("shell", "am", "force-stop", package, serial=serial, check=False)


def logcat_dump(serial: str) -> str:
    return adb("logcat", "-d", serial=serial)


def logcat_clear(serial: str) -> None:
    adb("logcat", "-c", serial=serial, check=False)
