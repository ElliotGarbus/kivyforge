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

from . import toolchain
from .bootstrap.contract import (
    COMPATIBLE_PYJNIUS,
    ContractError,
    check_pyjnius_contract,
)
from .elf import scan_alignment
from .lock import reader as lock_reader
from .splash import SPLASH_MIN_COMPILE_SDK

_EXE = ".exe" if os.name == "nt" else ""
_BAT = ".bat" if os.name == "nt" else ""


class AndroidProbe(Protocol):
    def which(self, name: str) -> str | None: ...
    def java_home(self) -> str | None: ...
    def sdk_root(self) -> Path | None: ...
    def ndk_versions(self, sdk: Path) -> list[str]: ...
    def build_tools_versions(self, sdk: Path) -> list[str]: ...
    def platform_installed(self, sdk: Path, api: int) -> bool: ...
    def accepted_licenses(self, sdk: Path) -> list[str]: ...
    def avds(self) -> list[str]: ...
    def connected_devices(self) -> list[str]: ...
    def has_kvm_or_haxm(self) -> bool: ...
    def tcp_reachable(self, host: str, port: int) -> bool: ...
    def latest_kivyforge_version(self) -> str | None: ...


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

    def accepted_licenses(self, sdk: Path) -> list[str]:
        """The license hash files ``sdkmanager --licenses`` writes on accept."""
        root = sdk / "licenses"
        return (
            sorted(p.name for p in root.iterdir() if p.is_file())
            if root.is_dir()
            else []
        )

    def avds(self) -> list[str]:
        try:
            from .adb import available_avds

            return available_avds()
        except Exception:  # noqa: BLE001
            return []

    def connected_devices(self) -> list[str]:
        try:
            from .adb import connected_devices

            return connected_devices()
        except Exception:  # noqa: BLE001
            return []

    def latest_kivyforge_version(self) -> str | None:
        from kivyforge.doctor.probe import RealProbe

        return RealProbe().latest_kivyforge_version()

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
def _check_kivyforge_version(
    probe: AndroidProbe, current: str, *, offline: bool
) -> CheckResult:
    """Report the running kivyforge, and nudge when PyPI has a newer one.

    The generated project's toolchain pins (AGP, Gradle, NDK) move with a
    kivyforge release, so "am I current" is a build-relevant question here, not
    just housekeeping.
    """
    if offline:
        return CheckResult("kivyforge", Status.PASS, f"{current} (offline)")
    from kivyforge.doctor.checks_common import _ver_tuple

    latest = probe.latest_kivyforge_version()
    if latest and _ver_tuple(latest) > _ver_tuple(current):
        return CheckResult(
            "kivyforge",
            Status.WARN,
            f"{current} (latest {latest})",
            hint="upgrade with `pip install -U kivyforge`.",
        )
    return CheckResult("kivyforge", Status.PASS, current)


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


def _check_sdk_licenses(probe: AndroidProbe, sdk: Path | None) -> CheckResult:
    """Unaccepted SDK licenses stop AGP mid-build with an opaque message.

    Acceptance is recorded as hash files under ``<sdk>/licenses/``; that is what
    AGP's own auto-download consults, so their presence is the whole signal.
    """
    if sdk is None:
        return CheckResult("SDK licenses", Status.SKIP, "no SDK root")
    accepted = probe.accepted_licenses(sdk)
    if not accepted:
        return CheckResult(
            "SDK licenses",
            Status.WARN,
            f"no accepted licenses recorded under {sdk / 'licenses'}",
            hint="run `sdkmanager --licenses` and accept; otherwise Gradle "
            "refuses to auto-install the SDK packages a build needs.",
        )
    return CheckResult("SDK licenses", Status.PASS, f"{len(accepted)} accepted")


def _check_gradle_wrapper(project_dir: Path) -> CheckResult:
    """The generated project builds through its own pinned wrapper (android/06).

    Not the host's ``gradle``: the wrapper is what makes the Gradle version part
    of kivyforge's toolchain pins, so a hand-edited or missing one is the
    difference between a reproducible build and whatever the host has.
    """
    if not project_dir.is_dir():
        return CheckResult(
            "Gradle wrapper", Status.SKIP, "project not generated yet (run build)"
        )
    script = project_dir / ("gradlew.bat" if os.name == "nt" else "gradlew")
    properties = project_dir / "gradle" / "wrapper" / "gradle-wrapper.properties"
    missing = [p.name for p in (script, properties) if not p.is_file()]
    if missing:
        return CheckResult(
            "Gradle wrapper",
            Status.FAIL,
            f"missing {', '.join(missing)}",
            hint="re-run `kivyforge build -p android` to regenerate the project.",
        )
    text = properties.read_text(encoding="utf-8")
    if toolchain.GRADLE_VERSION not in text:
        return CheckResult(
            "Gradle wrapper",
            Status.WARN,
            f"distributionUrl is not the pinned Gradle {toolchain.GRADLE_VERSION}",
            hint="the generated project is a managed artifact; rebuild rather "
            "than editing it (a hand-edited wrapper is overwritten anyway).",
        )
    return CheckResult(
        "Gradle wrapper", Status.PASS, f"gradle {toolchain.GRADLE_VERSION}"
    )


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
    devices = probe.connected_devices()
    if not devices:
        return CheckResult(
            "adb",
            Status.WARN,
            f"{adb}; no device or emulator attached",
            hint="attach a device (USB debugging on) or boot an AVD; "
            "`kivyforge run` and `run --smoke` need one.",
        )
    return CheckResult("adb", Status.PASS, f"{adb}; {', '.join(devices)}")


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
        # ``.major`` reads only the release segment's leading number, so a
        # pre-release like "3.0.0.dev202606221936" still counts as major 3 --
        # a direct ``Version(...) >= Version("3.0")`` comparison would not:
        # PEP 440 dev-releases sort *before* their final release, so that
        # comparison is False for every Kivy 3.0 dev build.
        is_sdl3 = Version(kivy.version).major >= 3
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


def _check_icon(config: Config, project_root: Path) -> CheckResult:
    from kivyforge.config.icons import icon_source_problem

    icons = config.android_required.icons
    if not icons.source:
        return CheckResult(
            "App icon",
            Status.SKIP,
            "no [tool.kivy.android.icons].source (default icon)",
        )
    problem = icon_source_problem(project_root / icons.source)
    if problem:
        return CheckResult(
            "App icon",
            Status.FAIL,
            problem.splitlines()[0],
            hint="a bad icon source fails the AAPT run, not the config load.",
        )
    # The layers are only referenced when set; a hex background is not a path.
    for key, value in (
        ("background", icons.background),
        ("monochrome", icons.monochrome),
    ):
        if value and not value.startswith("#") and not (project_root / value).is_file():
            return CheckResult(
                "App icon",
                Status.FAIL,
                f"[tool.kivy.android.icons].{key} not found: {value}",
            )
    return CheckResult("App icon", Status.PASS, icons.source)


def _check_splash(config: Config, project_root: Path) -> CheckResult:
    """Catch a bad splash path here rather than at AAPT time (android/06)."""
    from kivyforge.config.icons import IconSourceError, png_dimensions

    android = config.android_required
    splash = android.splash
    if not splash.source:
        return CheckResult(
            "Splash assets", Status.SKIP, "no [tool.kivy.android.splash].source"
        )
    source = project_root / splash.source
    if not source.is_file():
        return CheckResult(
            "Splash assets",
            Status.FAIL,
            f"[tool.kivy.android.splash].source not found: {source}",
            hint="expected a PNG, or an AnimatedVectorDrawable XML.",
        )
    animated = source.suffix.lower() == ".xml"
    if animated:
        text = source.read_text(encoding="utf-8", errors="replace")
        if "<vector" not in text and "<animated-vector" not in text:
            return CheckResult(
                "Splash assets",
                Status.FAIL,
                f"{splash.source} is XML but is neither a <vector> nor an "
                "<animated-vector> drawable",
            )
        animated = "<animated-vector" in text
    else:
        try:
            png_dimensions(source)
        except (IconSourceError, OSError) as exc:
            return CheckResult("Splash assets", Status.FAIL, str(exc).splitlines()[0])
    if splash.branding and not (project_root / splash.branding).is_file():
        return CheckResult(
            "Splash assets",
            Status.FAIL,
            f"[tool.kivy.android.splash].branding not found: {splash.branding}",
        )
    if android.compile_sdk < SPLASH_MIN_COMPILE_SDK:
        return CheckResult(
            "Splash assets",
            Status.FAIL,
            f"windowSplashScreen* need compile_sdk >= {SPLASH_MIN_COMPILE_SDK}; "
            f"this project compiles against android-{android.compile_sdk}",
            hint="raise [tool.kivy.android].compile_sdk.",
        )
    if splash.animation_duration is not None and not animated:
        return CheckResult(
            "Splash assets",
            Status.WARN,
            f"animation_duration is set but {splash.source} is not an "
            "AnimatedVectorDrawable; it will be ignored",
        )
    return CheckResult("Splash assets", Status.PASS, splash.source)


def _check_include_files(config: Config, project_root: Path, lock) -> CheckResult:
    """Report include_files drift as a warning before the build refuses it."""
    from kivyforge.artifacts.verify import sha256_file

    entries = config.android_required.include_files
    if not entries:
        return CheckResult(
            "include_files", Status.SKIP, "no [[tool.kivy.android.include_files]]"
        )
    pins = {(p.dest, p.source): p.sha256 for p in lock.include_files}
    staged: set[tuple[str, str]] = set()
    drifted: list[str] = []
    for entry in entries:
        for source in entry.sources:
            local = project_root / source
            children = (
                [c for c in sorted(local.rglob("*")) if c.is_file()]
                if local.is_dir()
                else [local]
            )
            for child in children:
                rel = (
                    (Path(source) / child.relative_to(local)).as_posix()
                    if local.is_dir()
                    else source
                )
                staged.add((entry.dest, rel))
                recorded = pins.get((entry.dest, rel))
                if not child.is_file():
                    drifted.append(f"{rel} (missing)")
                elif recorded is None:
                    drifted.append(f"{rel} (not in the lock)")
                elif recorded != sha256_file(child):
                    drifted.append(f"{rel} (changed)")
    drifted += [f"{source} (deleted)" for _dest, source in sorted(pins.keys() - staged)]
    if drifted:
        return CheckResult(
            "include_files",
            Status.WARN,
            "drift vs. the lock: " + ", ".join(drifted),
            hint="run `kivyforge lock -p android`; the build refuses to stage drift.",
        )
    return CheckResult(
        "include_files", Status.PASS, f"{len(staged)} file(s) match the lock"
    )


def _check_find_links(config: Config, project_root: Path) -> CheckResult:
    """A `find_links` dir that has moved or holds no wheels only shows up as an
    unresolvable requirement at lock time; name it here instead."""
    from kivyforge.lock.find_links import find_links_doctor_detail

    entries = config.android_required.find_links
    if not entries:
        return CheckResult("find_links directories", Status.SKIP, "not configured")
    root = project_root.resolve()
    problems: list[tuple[str, str | None]] = []
    empty: list[tuple[str, str | None]] = []
    ok: list[str] = []
    for entry in entries:
        path = (root / entry).resolve()
        detail, hint = find_links_doctor_detail(root, entry, path, platform="android")
        if not path.is_dir():
            problems.append((detail, hint))
        elif not any(path.glob("*.whl")):
            empty.append((detail, hint))
        else:
            ok.append(detail)
    for bucket, status in ((problems, Status.FAIL), (empty, Status.WARN)):
        if bucket:
            return CheckResult(
                "find_links directories",
                status,
                "; ".join(d for d, _ in bucket),
                hint=next((h for _, h in bucket if h), ""),
            )
    return CheckResult("find_links directories", Status.PASS, "; ".join(ok))


def _check_app_native_binaries(config: Config, project_root: Path) -> CheckResult:
    """Native code in ``app_dir`` cannot work on Android, whatever its ABI.

    ``app_dir`` is staged into the Python *asset* bundle and unpacked to
    app-private storage at first launch, and Android refuses to ``dlopen`` a
    library from there (W^X). Only ``jniLibs/`` — which kivyforge fills from
    wheels — is a loadable location, so a ``.so`` here is dead weight at best.
    """
    from .elf import ElfError, machine_name, read_elf

    app_dir = project_root / config.kivy.app_dir
    if not app_dir.is_dir():
        return CheckResult(
            "App-local native binaries",
            Status.SKIP,
            f"app_dir does not exist: {app_dir}",
        )
    found: list[str] = []
    for pattern in ("*.so", "*.dylib", "*.dll", "*.pyd"):
        for binary in sorted(app_dir.rglob(pattern)):
            rel = binary.relative_to(project_root).as_posix()
            try:
                info = read_elf(binary)
            except (ElfError, OSError):
                found.append(f"{rel} (not an ELF)")
            else:
                found.append(f"{rel} ({machine_name(info.machine)})")
    if found:
        return CheckResult(
            "App-local native binaries",
            Status.FAIL,
            "; ".join(found),
            hint="native code belongs in an Android wheel (jniLibs), not "
            "app_dir: the asset bundle is unpacked to app-private storage, "
            "which Android will not dlopen (android/03 §wheel content rules).",
        )
    return CheckResult(
        "App-local native binaries", Status.PASS, "no native binaries in app_dir"
    )


def _check_manifest_policy(config: Config) -> CheckResult:
    """Run `package`'s own release policy over the manifest kivyforge would
    generate, so a footgun surfaces now rather than at release time.

    This is the preflight's first pass only: the merged-manifest pass needs AGP,
    so `kivyforge package` remains the gate that sees library manifests.
    """
    from .generate.manifest import generate_manifest
    from .policy import check_release_manifest

    android = config.android_required
    try:
        manifest_xml = generate_manifest(android, orientation=config.kivy.orientation)
    except Exception as exc:  # noqa: BLE001 - a generation failure is its own report
        return CheckResult(
            "Manifest policy (release)",
            Status.FAIL,
            f"the manifest could not be generated: {exc}",
        )
    findings = check_release_manifest(
        manifest_xml,
        package=android.package,
        allow_exported=android.manifest.allow_exported,
    )
    fails = [f.message for f in findings if f.severity == "FAIL"]
    if fails:
        return CheckResult(
            "Manifest policy (release)",
            Status.FAIL,
            "; ".join(fails),
            hint="`kivyforge package` blocks on these before signing; fix them "
            "through the manifest escape hatches (android/04 §release policy).",
        )
    infos = [f.message for f in findings if f.severity == "INFO"]
    if infos:
        return CheckResult(
            "Manifest policy (release)",
            Status.PASS,
            "no violations; advisory: " + "; ".join(infos),
        )
    return CheckResult("Manifest policy (release)", Status.PASS, "no violations")


def _check_implied_features(config: Config) -> CheckResult:
    """Report the `<uses-feature>` set `auto_features` will synthesize.

    Play filters devices on these, so a permission quietly narrowing the store
    audience is worth seeing before upload rather than after.
    """
    from .generate.manifest import implied_features, qualified_permissions

    android = config.android_required
    if not android.permissions.auto_features:
        return CheckResult(
            "Implied features", Status.SKIP, "permissions.auto_features is false"
        )
    explicit = {f.name for f in android.permissions.features}
    permissions = qualified_permissions(android.permissions.uses)
    synthesized = [f for f in implied_features(permissions) if f not in explicit]
    if not synthesized:
        return CheckResult(
            "Implied features", Status.PASS, "no permission implies a feature"
        )
    return CheckResult(
        "Implied features",
        Status.PASS,
        'synthesized android:required="false": ' + ", ".join(synthesized),
    )


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
    # Channels 3 and 4 fetch too: a hosted .aar/.jar, and — when Maven
    # coordinates are declared — Gradle's own repositories (the defaults it
    # always consults plus any extra the project declares).
    for lib in lock.android_libs:
        if lib.url:
            hosts.add(urlparse(lib.url).hostname or "")
    if lock.gradle.declared:
        hosts |= {"dl.google.com", "repo.maven.apache.org"}
        for repo in lock.gradle.repositories:
            hosts.add(urlparse(repo).hostname or "")
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
        _check_kivyforge_version(probe, kivyforge_version, offline=offline),
        _check_jdk(probe),
        _check_sdk(sdk),
        _check_sdk_licenses(probe, sdk),
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
    results.append(_check_app_native_binaries(config, cwd))
    results.append(_check_icon(config, cwd))
    results.append(_check_splash(config, cwd))
    results.append(_check_find_links(config, cwd))
    results.append(_check_manifest_policy(config))
    results.append(_check_implied_features(config))

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
            _check_include_files(config, cwd, lock),
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
    results.append(_check_gradle_wrapper(project_dir))
    if project_dir.is_dir():
        results.append(_check_16k_alignment(project_dir))
    results.append(_check_signing(config, cwd))
    return results
