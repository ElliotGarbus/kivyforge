"""iOS-specific doctor checks (spec 05). Pure over a ``Probe``.

Reuses the platform-neutral checks (pip, toolchain version, app source dir) from
``checks_common`` and adds the iOS environment (Xcode, command-line tools,
simulator runtimes) and project checks (signing, provisioning, icon, Swift
toolchain, find_links, reachable hosts, native binaries, privacy manifests) over
the ``pylock.ios.toml`` model.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from kivyforge.config.model import Config
from kivyforge.doctor import checks_common as C
from kivyforge.doctor.checks_common import _ver_tuple
from kivyforge.doctor.probe import Probe
from kivyforge.doctor.result import CheckResult, Status
from kivyforge.icon import APP_ICON_SIZE, icon_source_problem
from kivyforge.lock.find_links import find_links_doctor_detail

from .lock.model import Lockfile

MIN_XCODE = "15.0"  # devicectl (run --device) requires Xcode 15+


# ---- environment checks -------------------------------------------------


def check_xcode_version(probe: Probe) -> CheckResult:
    version = probe.xcode_version()
    if version is None:
        return CheckResult(
            "Xcode version",
            Status.FAIL,
            "Xcode not found",
            hint="install Xcode from the App Store, then `xcode-select --switch`.",
        )
    if _ver_tuple(version) < _ver_tuple(MIN_XCODE):
        return CheckResult(
            "Xcode version",
            Status.FAIL,
            f"{version} (need >= {MIN_XCODE})",
            hint=f"update Xcode to {MIN_XCODE} or newer.",
        )
    return CheckResult("Xcode version", Status.PASS, version)


def check_command_line_tools(probe: Probe) -> CheckResult:
    path = probe.xcode_select_path()
    if not path:
        return CheckResult(
            "Command-line tools",
            Status.FAIL,
            "xcode-select path not set",
            hint="run `xcode-select --install` or `sudo xcode-select --switch`.",
        )
    if not probe.has_xcrun_clang():
        return CheckResult(
            "Command-line tools",
            Status.FAIL,
            "xcrun clang not found",
            hint="run `xcode-select --install`.",
        )
    return CheckResult("Command-line tools", Status.PASS, path)


def check_simulator_runtimes(probe: Probe, config: Config | None) -> CheckResult:
    runtimes = probe.simulator_runtimes()
    if not runtimes:
        return CheckResult(
            "Simulator runtimes",
            Status.WARN,
            "no iOS simulator runtimes installed",
            hint="install one via Xcode > Settings > Components.",
        )
    if config is not None:
        floor = config.ios_required.deployment_target
        ok = [r for r in runtimes if _ver_tuple(r) >= _ver_tuple(floor)]
        if not ok:
            return CheckResult(
                "Simulator runtimes",
                Status.WARN,
                f"installed {', '.join(runtimes)} < deployment_target {floor}",
                hint=f"install an iOS {floor}+ simulator runtime.",
            )
    return CheckResult("Simulator runtimes", Status.PASS, ", ".join(runtimes))


# ---- project checks -----------------------------------------------------


def check_signing_identity(probe: Probe, config: Config) -> CheckResult:
    signing = config.ios_required.signing
    if signing.auto_signing:
        return CheckResult("Signing identity", Status.PASS, "automatic signing")
    identities = probe.keychain_identities()
    if not any(signing.identity in line for line in identities):
        return CheckResult(
            "Signing identity",
            Status.FAIL,
            f"identity {signing.identity!r} not in keychain",
            hint="import the signing certificate or set auto_signing = true.",
        )
    return CheckResult("Signing identity", Status.PASS, signing.identity)


def check_swift_toolchain(probe: Probe, config: Config) -> CheckResult:
    """SPM resolution (lock) and compilation (build) need Xcode's Swift toolchain.

    Skipped for pure-wheel projects — only relevant when ``swift_packages`` is
    declared (spec 07).
    """
    packages = config.ios_required.swift_packages
    if not packages:
        return CheckResult(
            "Swift package toolchain", Status.SKIP, "no swift_packages declared"
        )
    if not probe.has_swift_toolchain():
        return CheckResult(
            "Swift package toolchain",
            Status.FAIL,
            "swift not found",
            hint="install Xcode's Swift toolchain (`xcode-select --switch "
            "/Applications/Xcode.app`) — required to resolve/build Swift packages.",
        )
    return CheckResult(
        "Swift package toolchain",
        Status.PASS,
        f"{len(packages)} swift package(s) declared",
    )


def check_app_icon(config: Config, project_root: Path) -> CheckResult:
    source = config.ios_required.icons.source
    if not source:
        return CheckResult("App icon", Status.SKIP, "not configured")
    path = (project_root / source).resolve()
    problem = icon_source_problem(path)
    if problem:
        return CheckResult(
            "App icon",
            Status.FAIL,
            f"{source} invalid",
            hint=problem,
        )
    return CheckResult("App icon", Status.PASS, f"{APP_ICON_SIZE}x{APP_ICON_SIZE} PNG")


def check_provisioning_profile(config: Config, project_root: Path) -> CheckResult:
    profile = config.ios_required.signing.provisioning_profile
    if not profile:
        return CheckResult("Provisioning profile", Status.PASS, "not set")
    path = (
        (project_root / profile) if not Path(profile).is_absolute() else Path(profile)
    )
    if not path.exists():
        return CheckResult(
            "Provisioning profile",
            Status.FAIL,
            f"{profile} not found",
            hint="point provisioning_profile at an existing .mobileprovision.",
        )
    return CheckResult("Provisioning profile", Status.PASS, profile)


def check_find_links(config: Config, project_root: Path) -> CheckResult:
    entries = config.ios_required.find_links
    if not entries:
        return CheckResult("find_links directories", Status.SKIP, "not configured")

    root = project_root.resolve()
    problems: list[tuple[str, str | None]] = []
    warnings: list[tuple[str, str | None]] = []
    ok: list[str] = []

    for entry in entries:
        path = (root / entry).resolve()
        detail, hint = find_links_doctor_detail(root, entry, path)
        if not path.exists() or not path.is_dir():
            problems.append((detail, hint))
        elif not any(path.glob("*.whl")):
            warnings.append((detail, hint))
        else:
            ok.append(detail)

    if problems:
        detail = "; ".join(d for d, _ in problems)
        hint = next((h for _, h in problems if h), "")
        return CheckResult("find_links directories", Status.FAIL, detail, hint=hint)
    if warnings:
        detail = "; ".join(d for d, _ in warnings)
        hint = next((h for _, h in warnings if h), "")
        return CheckResult("find_links directories", Status.WARN, detail, hint=hint)
    return CheckResult("find_links directories", Status.PASS, "; ".join(ok))


def check_hosts_reachable(probe: Probe, lock: Lockfile | None) -> CheckResult:
    if lock is None:
        return CheckResult(
            "Required hosts reachable", Status.SKIP, "no pylock.ios.toml"
        )
    hosts = sorted(_lock_hosts(lock))
    if not hosts:
        return CheckResult(
            "Required hosts reachable", Status.PASS, "all artifacts vendored"
        )
    unreachable = [h for h in hosts if not probe.tcp_reachable(h, 443)]
    if unreachable:
        return CheckResult(
            "Required hosts reachable",
            Status.FAIL,
            f"unreachable: {', '.join(unreachable)}",
            hint="check your network/proxy; these hosts serve pinned artifacts.",
        )
    return CheckResult("Required hosts reachable", Status.PASS, ", ".join(hosts))


def check_app_native_binaries(
    probe: Probe, config: Config, project_root: Path
) -> CheckResult:
    app_dir = project_root / config.kivy.app_dir
    if not app_dir.is_dir():
        return CheckResult(
            "App-local native binaries", Status.SKIP, f"{config.kivy.app_dir} missing"
        )
    offenders: list[str] = []
    unknown: list[str] = []
    for pattern in ("*.so", "*.dylib"):
        for binary in app_dir.rglob(pattern):
            rel = binary.relative_to(project_root)
            platforms = probe.binary_platforms(binary)
            if not platforms:
                # No platform could be read: truncated, corrupt, not a Mach-O,
                # or lacking an LC_BUILD_VERSION. Can't confirm it's iOS-safe.
                unknown.append(str(rel))
            elif not platforms & {"ios", "ios-simulator"}:
                offenders.append(f"{rel} ({', '.join(sorted(platforms))})")
    if offenders:
        return CheckResult(
            "App-local native binaries",
            Status.FAIL,
            "; ".join(offenders),
            hint="non-iOS native code won't load on device; ship it as an iOS wheel.",
        )
    if unknown:
        return CheckResult(
            "App-local native binaries",
            Status.WARN,
            "unrecognized binary: " + "; ".join(unknown),
            hint="could not read an iOS Mach-O platform from these files "
            "(truncated, corrupt, or not a Mach-O); confirm they are iOS dylibs "
            "or ship them as an iOS wheel.",
        )
    return CheckResult("App-local native binaries", Status.PASS, "none non-iOS")


def check_app_privacy_manifest(config: Config, project_root: Path) -> CheckResult:
    manifest = project_root / f"{config.app_slug}-ios" / "PrivacyInfo.xcprivacy"
    if not manifest.exists():
        return CheckResult(
            "App-level privacy manifest",
            Status.WARN,
            "PrivacyInfo.xcprivacy absent",
            hint="`kivyforge build` generates a minimal stub; if you use "
            "required-reason APIs, set [tool.kivy.ios.privacy_manifest].source.",
        )
    return CheckResult("App-level privacy manifest", Status.PASS, "present")


def check_xcframework_privacy_manifests(
    config: Config, project_root: Path
) -> CheckResult:
    frameworks = project_root / f"{config.app_slug}-ios" / "Frameworks"
    if not frameworks.is_dir():
        return CheckResult(
            "xcframework privacy manifests", Status.SKIP, "project not built"
        )
    missing = []
    for xc in sorted(frameworks.glob("*.xcframework")):
        if not any(xc.rglob("PrivacyInfo.xcprivacy")):
            missing.append(xc.name)
    if missing:
        return CheckResult(
            "xcframework privacy manifests",
            Status.WARN,
            f"no PrivacyInfo in: {', '.join(missing)}",
            hint="each framework's author must add a privacy manifest; "
            "kivyforge cannot add it for them.",
        )
    return CheckResult("xcframework privacy manifests", Status.PASS, "all present")


def _lock_hosts(lock: Lockfile) -> set[str]:
    hosts: set[str] = set()
    for pkg in lock.packages:
        for wheel in pkg.wheels:
            if wheel.url:
                _add_host(hosts, wheel.url)
    for xc in lock.xcframeworks:
        if xc.url:
            _add_host(hosts, xc.url)
    for sp in lock.swift_packages:
        if sp.url:
            host = _git_host(sp.url)
            if host:
                hosts.add(host)
    if lock.python_xcframework.url:
        _add_host(hosts, lock.python_xcframework.url)
    return hosts


def _add_host(hosts: set[str], url: str) -> None:
    netloc = urlparse(url).hostname
    if netloc:
        hosts.add(netloc)


def _git_host(url: str) -> str | None:
    """Host of a Git URL, handling both ``https://`` and scp-like ``git@host:``."""
    if "://" in url:
        return urlparse(url).hostname
    if "@" in url and ":" in url:
        return url.split("@", 1)[1].split(":", 1)[0] or None
    return urlparse(url).hostname


def run_ios_checks(
    probe: Probe,
    *,
    kivyforge_version: str,
    config: Config | None = None,
    project_root: Path | None = None,
    lock: Lockfile | None = None,
    offline: bool = False,
) -> list[CheckResult]:
    """Run all iOS checks. Project checks SKIP in environment mode (no config)."""
    project_root = project_root or Path.cwd()
    results = [
        check_xcode_version(probe),
        check_command_line_tools(probe),
        C.check_pip_version(probe),
        check_simulator_runtimes(probe, config),
        C.check_kivyforge_version(probe, kivyforge_version, offline=offline),
    ]

    if config is None:
        for name in (
            "App source directory",
            "Signing identity",
            "Provisioning profile",
            "App icon",
            "Swift package toolchain",
            "find_links directories",
            "Required hosts reachable",
            "App-local native binaries",
            "App-level privacy manifest",
            "xcframework privacy manifests",
        ):
            results.append(CheckResult(name, Status.SKIP, C.SKIP_NOTE))
        return results

    results += [
        C.check_app_dir(config, project_root),
        check_signing_identity(probe, config),
        check_provisioning_profile(config, project_root),
        check_app_icon(config, project_root),
        check_swift_toolchain(probe, config),
        check_find_links(config, project_root),
        check_hosts_reachable(probe, lock),
        check_app_native_binaries(probe, config, project_root),
        check_app_privacy_manifest(config, project_root),
        check_xcframework_privacy_manifests(config, project_root),
    ]
    return results
