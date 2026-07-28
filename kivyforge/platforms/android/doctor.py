"""``kivyforge doctor`` — Android checks (android/06 §doctor).

Environment checks (JDK, SDK, build-tools, NDK, emulator, adb) touch the host
only through an injectable ``AndroidProbe`` so the check logic is unit-testable
with a fake. Project checks assert against real seams (the config, the lock,
staged ``.so``s, the generated manifest) and are exercised on a real project.

kivyforge never installs the host toolchain (android/06): every check only
*detects* and prints an actionable hint derived from the project's own config.
Each check reports PASS / WARN / FAIL / SKIP; exit is non-zero only on FAIL.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol

from kivyforge.config.errors import ConfigError
from kivyforge.config.loader import load_config
from kivyforge.config.model import AndroidConfig, Config
from kivyforge.doctor.result import CheckResult, Status

from .bootstrap.contract import (
    COMPATIBLE_PYJNIUS,
    ContractError,
    check_pyjnius_contract,
)
from .elf import scan_alignment
from .lock import reader as lock_reader

_EXE = ".exe" if os.name == "nt" else ""
_BAT = ".bat" if os.name == "nt" else ""


class AndroidProbe(Protocol):
    def which(self, name: str) -> str | None: ...
    def java_home(self) -> str | None: ...
    def sdk_root(self) -> Path | None: ...
    def ndk_versions(self, sdk: Path) -> list[str]: ...
    def build_tools_versions(self, sdk: Path) -> list[str]: ...
    def platform_installed(self, sdk: Path, api: int) -> bool: ...
    def avds(self) -> list[str]: ...
    def has_kvm_or_haxm(self) -> bool: ...
    def tcp_reachable(self, host: str, port: int) -> bool: ...


class RealAndroidProbe:
    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def java_home(self) -> str | None:
        jh = os.environ.get("JAVA_HOME")
        if jh and (Path(jh) / "bin" / f"java{_EXE}").exists():
            return jh
        return None

    def sdk_root(self) -> Path | None:
        for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            value = os.environ.get(var)
            if value and Path(value).is_dir():
                return Path(value)
        candidates = []
        if os.name == "nt":
            local = os.environ.get("LOCALAPPDATA")
            if local:
                candidates.append(Path(local) / "Android" / "Sdk")
        else:
            home = Path.home()
            candidates += [home / "Android" / "Sdk", home / "android-sdk"]
        return next((c for c in candidates if c.is_dir()), None)

    def ndk_versions(self, sdk: Path) -> list[str]:
        root = sdk / "ndk"
        return (
            sorted(p.name for p in root.iterdir() if p.is_dir())
            if root.is_dir()
            else []
        )

    def build_tools_versions(self, sdk: Path) -> list[str]:
        root = sdk / "build-tools"
        return (
            sorted(p.name for p in root.iterdir() if p.is_dir())
            if root.is_dir()
            else []
        )

    def platform_installed(self, sdk: Path, api: int) -> bool:
        return (sdk / "platforms" / f"android-{api}").is_dir()

    def avds(self) -> list[str]:
        try:
            from .adb import available_avds

            return available_avds()
        except Exception:  # noqa: BLE001
            return []

    def has_kvm_or_haxm(self) -> bool:
        if os.name == "nt":
            return True  # WHPX/HAXM presence is hard to probe cheaply; assume ok
        return Path("/dev/kvm").exists()

    def tcp_reachable(self, host: str, port: int) -> bool:
        import socket

        try:
            with socket.create_connection((host, port), timeout=5):
                return True
        except OSError:
            return False


# --------------------------------------------------------------------------- #
# environment checks
# --------------------------------------------------------------------------- #
def _check_jdk(probe: AndroidProbe) -> CheckResult:
    jh = probe.java_home()
    if jh:
        return CheckResult("JDK", Status.PASS, f"JAVA_HOME={jh}")
    java = probe.which("java")
    if java:
        return CheckResult("JDK", Status.PASS, java)
    return CheckResult(
        "JDK",
        Status.FAIL,
        "no java on PATH and JAVA_HOME unset",
        hint="install a JDK 17+ (AGP requires it) and set JAVA_HOME.",
    )


def _check_sdk(sdk: Path | None) -> CheckResult:
    if sdk is None:
        return CheckResult(
            "Android SDK",
            Status.FAIL,
            "ANDROID_HOME/ANDROID_SDK_ROOT unset and no SDK at the conventional "
            "location",
            hint="install the SDK and set ANDROID_HOME.",
        )
    sdkmanager = sdk / "cmdline-tools" / "latest" / "bin" / f"sdkmanager{_BAT}"
    if not sdkmanager.exists():
        return CheckResult(
            "Android SDK",
            Status.WARN,
            f"{sdk} exists but cmdline-tools/latest is missing",
            hint="install the 'cmdline-tools;latest' package.",
        )
    return CheckResult("Android SDK", Status.PASS, str(sdk))


def _check_build_tools(
    probe: AndroidProbe, sdk: Path | None, android: AndroidConfig | None
) -> CheckResult:
    if sdk is None:
        return CheckResult("Build-tools / platform", Status.SKIP, "no SDK root")
    versions = probe.build_tools_versions(sdk)
    if not versions:
        return CheckResult(
            "Build-tools / platform",
            Status.FAIL,
            "no build-tools installed",
            hint="sdkmanager 'build-tools;<version>'.",
        )
    if android is not None and not probe.platform_installed(sdk, android.compile_sdk):
        return CheckResult(
            "Build-tools / platform",
            Status.FAIL,
            f"the compile_sdk platform (android-{android.compile_sdk}) is not "
            "installed",
            hint=f"sdkmanager 'platforms;android-{android.compile_sdk}'.",
        )
    return CheckResult(
        "Build-tools / platform", Status.PASS, f"build-tools {versions[-1]}"
    )


def _check_ndk(probe: AndroidProbe, sdk: Path | None) -> CheckResult:
    if sdk is None:
        return CheckResult("NDK", Status.SKIP, "no SDK root to look in")
    versions = probe.ndk_versions(sdk)
    if not versions:
        return CheckResult(
            "NDK",
            Status.FAIL,
            "no NDK installed (required for EVERY build — it compiles the native "
            "launcher)",
            hint="sdkmanager 'ndk;<version>' (r27+ recommended for 16 KB).",
        )
    return CheckResult("NDK", Status.PASS, ", ".join(versions))


def _check_adb(probe: AndroidProbe, sdk: Path | None) -> CheckResult:
    adb = probe.which("adb")
    if adb is None and sdk is not None:
        candidate = sdk / "platform-tools" / f"adb{_EXE}"
        if candidate.exists():
            adb = str(candidate)
    if adb is None:
        return CheckResult(
            "adb",
            Status.WARN,
            "platform-tools not found",
            hint="sdkmanager platform-tools (needed for `kivyforge run`).",
        )
    return CheckResult("adb", Status.PASS, adb)


def _check_emulator(probe: AndroidProbe, sdk: Path | None) -> CheckResult:
    avds = probe.avds()
    accel = probe.has_kvm_or_haxm()
    if not avds:
        return CheckResult(
            "Emulator / virtualization",
            Status.WARN,
            "no AVD found",
            hint="create an AVD (Android Studio Device Manager or avdmanager) "
            "for `kivyforge run --emulator`.",
        )
    if not accel:
        return CheckResult(
            "Emulator / virtualization",
            Status.WARN,
            f"AVDs present ({len(avds)}) but no hardware acceleration",
            hint="enable KVM (Linux) / HAXM or Hyper-V (macOS/Windows).",
        )
    return CheckResult(
        "Emulator / virtualization", Status.PASS, f"{len(avds)} AVD(s), accelerated"
    )


# --------------------------------------------------------------------------- #
# project checks
# --------------------------------------------------------------------------- #
def _check_sdl_kivy_match(config: Config, lock) -> CheckResult:
    android = config.android_required
    kivy = next((p for p in lock.packages if p.name.lower() == "kivy"), None)
    if kivy is None:
        return CheckResult("SDL / Kivy match", Status.SKIP, "kivy not in the lock")
    from packaging.version import InvalidVersion, Version

    try:
        is_sdl3 = Version(kivy.version) >= Version("3.0")
    except InvalidVersion:
        return CheckResult(
            "SDL / Kivy match", Status.WARN, f"unparseable kivy {kivy.version!r}"
        )
    expected = 3 if is_sdl3 else 2
    if android.kivy_generation != expected:
        return CheckResult(
            "SDL / Kivy match",
            Status.WARN,
            f"kivy_generation = {android.kivy_generation} but kivy {kivy.version} "
            f"is SDL{expected}",
            hint=f"set kivy_generation = {expected} and re-lock.",
        )
    return CheckResult(
        "SDL / Kivy match",
        Status.PASS,
        f"kivy {kivy.version} / kivy_generation {android.kivy_generation}",
    )


def _check_pyjnius_contract(lock) -> CheckResult:
    pyjnius = next((p for p in lock.packages if p.name.lower() == "pyjnius"), None)
    if pyjnius is None:
        return CheckResult(
            "pyjnius / bootstrap match", Status.SKIP, "pyjnius not in the lock"
        )
    try:
        check_pyjnius_contract(pyjnius.version)
    except ContractError:
        return CheckResult(
            "pyjnius / bootstrap match",
            Status.FAIL,
            f"locked pyjnius {pyjnius.version} is outside the bootstrap template's "
            f"invoke0 range ({COMPATIBLE_PYJNIUS})",
            hint="re-lock to a compatible pyjnius or upgrade kivyforge.",
        )
    return CheckResult(
        "pyjnius / bootstrap match",
        Status.PASS,
        f"pyjnius {pyjnius.version} in range",
    )


def _check_16k_alignment(project_dir: Path) -> CheckResult:
    jnilibs = project_dir / "app" / "src" / "main" / "jniLibs"
    if not jnilibs.is_dir():
        return CheckResult(
            "16 KB alignment", Status.SKIP, "no staged jniLibs yet (run build)"
        )
    bad = scan_alignment(jnilibs)
    if bad:
        names = ", ".join(f"{p.name} (0x{a:x})" for p, a in bad[:5])
        return CheckResult(
            "16 KB alignment",
            Status.FAIL,
            f"{len(bad)} native lib(s) below 16 KB LOAD alignment: {names}",
            hint="rebuild the offending wheel with NDK r28+ or "
            "-Wl,-z,max-page-size=16384 (android/03 §wheel content rules).",
        )
    return CheckResult(
        "16 KB alignment", Status.PASS, "all staged .so's are 16 KB-aligned"
    )


def _check_abi_coverage(config: Config, lock) -> CheckResult:
    android = config.android_required
    from kivyforge.platforms.android.stage.wheels import (
        WheelStageError,
        select_wheel,
    )

    missing = []
    for package in lock.packages:
        for abi in android.abis:
            try:
                select_wheel(package, abi=abi, min_sdk=android.min_sdk)
            except WheelStageError:
                missing.append(f"{package.name}/{abi}")
    if missing:
        return CheckResult(
            "ABI coverage",
            Status.FAIL,
            f"missing wheel slices: {', '.join(missing[:5])}",
            hint="re-lock, or narrow [tool.kivy.android].abis.",
        )
    return CheckResult(
        "ABI coverage", Status.PASS, f"every package covers {', '.join(android.abis)}"
    )


def _check_signing(config: Config, project_root: Path) -> CheckResult:
    android = config.android_required
    if not android.signing.configured:
        return CheckResult(
            "Signing (release)",
            Status.SKIP,
            "[tool.kivy.android.signing] not configured (debug builds are fine)",
        )
    from .signing import SigningError, resolve_signing

    try:
        resolve_signing(android.signing, project_root=project_root)
    except SigningError as exc:
        return CheckResult(
            "Signing (release)",
            Status.FAIL,
            str(exc).splitlines()[0],
            hint="see `kivyforge package` signing prerequisites (android/07).",
        )
    return CheckResult("Signing (release)", Status.PASS, "keystore + alias resolve")


def _check_lock_hosts(probe: AndroidProbe, lock) -> CheckResult:
    from urllib.parse import urlparse

    hosts: set[str] = set()
    for runtime in lock.python_android:
        if runtime.url:
            hosts.add(urlparse(runtime.url).hostname or "")
    for package in lock.packages:
        for wheel in package.wheels:
            if wheel.url:
                hosts.add(urlparse(wheel.url).hostname or "")
    hosts.discard("")
    if not hosts:
        return CheckResult(
            "Required hosts reachable", Status.SKIP, "all artifacts are vendored"
        )
    unreachable = [h for h in sorted(hosts) if not probe.tcp_reachable(h, 443)]
    if unreachable:
        return CheckResult(
            "Required hosts reachable",
            Status.WARN,
            f"cannot reach: {', '.join(unreachable)}",
            hint="check your network; needed to fetch runtime/wheels.",
        )
    return CheckResult(
        "Required hosts reachable", Status.PASS, f"{len(hosts)} host(s) reachable"
    )


def android_doctor(
    cwd: Path,
    *,
    kivyforge_version: str,
    offline: bool,
    probe: AndroidProbe | None = None,
) -> list[CheckResult]:
    probe = probe or RealAndroidProbe()
    sdk = probe.sdk_root()

    config: Config | None = None
    pyproject = cwd / "pyproject.toml"
    config_result: CheckResult | None = None
    if pyproject.exists():
        try:
            config = load_config(pyproject, require_ios=False, require_android=True)
        except ConfigError as exc:
            config_result = CheckResult(
                "Android config",
                Status.FAIL,
                str(exc).splitlines()[0],
                hint="fix pyproject.toml; see the error above.",
            )

    android = config.android if config else None
    results = [
        CheckResult("kivyforge", Status.PASS, kivyforge_version),
        _check_jdk(probe),
        _check_sdk(sdk),
        _check_build_tools(probe, sdk, android),
        _check_ndk(probe, sdk),
        _check_adb(probe, sdk),
        _check_emulator(probe, sdk),
    ]

    if config_result is not None:
        results.append(config_result)
        return results
    if config is None:
        return results  # environment mode

    android = config.android_required
    results.append(
        CheckResult(
            "Android config",
            Status.PASS,
            f"{android.package} (min {android.min_sdk} / target "
            f"{android.target_sdk}, kivy_generation {android.kivy_generation}, "
            f"abis {', '.join(android.abis)})",
        )
    )
    app_dir = cwd / config.kivy.app_dir
    results.append(
        CheckResult("App source directory", Status.PASS, str(app_dir))
        if app_dir.is_dir()
        else CheckResult(
            "App source directory",
            Status.FAIL,
            f"[tool.kivy].app_dir does not exist: {app_dir}",
            hint="create it or fix app_dir.",
        )
    )

    lock_path = cwd / "pylock.android.toml"
    if lock_path.is_file():
        try:
            lock = lock_reader.load(lock_path)
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult("Lock", Status.FAIL, f"unreadable lock: {exc}"))
            return results
        results += [
            _check_sdl_kivy_match(config, lock),
            _check_pyjnius_contract(lock),
            _check_abi_coverage(config, lock),
        ]
        if not offline:
            results.append(_check_lock_hosts(probe, lock))
    else:
        results.append(
            CheckResult(
                "Lock",
                Status.WARN,
                "pylock.android.toml not found",
                hint="run `kivyforge lock -p android`.",
            )
        )

    from .cli import project_dir_for

    project_dir = project_dir_for(cwd, config)
    if project_dir.is_dir():
        results.append(_check_16k_alignment(project_dir))
    results.append(_check_signing(config, cwd))
    return results
