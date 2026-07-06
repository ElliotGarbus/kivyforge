"""macOS-specific doctor checks (macos-spec).

Reuses the platform-neutral checks (pip, toolchain version, app source dir) from
``checks`` and adds the macOS environment (host + codesign) and project checks
(arch coverage, runtime floor, icon, find_links, reachable hosts) over the
``pylock.macos.toml`` model.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ..config.model import Config
from ..lock.find_links import find_links_doctor_detail
from ..lock.macos import MacosLockfile, wheel_arch
from ..project.icon import APP_ICON_SIZE, icon_source_problem
from .checks import _ver_tuple
from .probe import Probe
from .result import CheckResult, Status


def check_macos_host(probe: Probe) -> CheckResult:
    host = probe.host_system()
    if host != "Darwin":
        return CheckResult(
            "Host is macOS",
            Status.FAIL,
            f"host is {host!r}",
            hint="the macOS .app backend (codesign + lipo) requires a macOS host.",
        )
    return CheckResult("Host is macOS", Status.PASS, "Darwin")


def check_codesign(probe: Probe) -> CheckResult:
    if not probe.has_codesign():
        return CheckResult(
            "Codesign available",
            Status.FAIL,
            "codesign not found",
            hint="install the Xcode command-line tools: `xcode-select --install`.",
        )
    return CheckResult("Codesign available", Status.PASS, "codesign present")


def check_macos_app_icon(config: Config, project_root: Path) -> CheckResult:
    source = config.macos_required.icons.source
    if not source:
        return CheckResult("App icon", Status.SKIP, "not configured")
    problem = icon_source_problem((project_root / source).resolve())
    if problem:
        return CheckResult("App icon", Status.FAIL, f"{source} invalid", hint=problem)
    return CheckResult("App icon", Status.PASS, f"{APP_ICON_SIZE}x{APP_ICON_SIZE} PNG")


def check_macos_find_links(config: Config, project_root: Path) -> CheckResult:
    entries = config.macos_required.find_links
    if not entries:
        return CheckResult("find_links directories", Status.SKIP, "not configured")
    root = project_root.resolve()
    problems: list[tuple[str, str | None]] = []
    warnings: list[tuple[str, str | None]] = []
    ok: list[str] = []
    for entry in entries:
        path = (root / entry).resolve()
        detail, hint = find_links_doctor_detail(root, entry, path)
        if not path.is_dir():
            problems.append((detail, hint))
        elif not any(path.glob("*.whl")):
            warnings.append((detail, hint))
        else:
            ok.append(detail)
    if problems:
        return CheckResult(
            "find_links directories",
            Status.FAIL,
            "; ".join(d for d, _ in problems),
            hint=next((h for _, h in problems if h), ""),
        )
    if warnings:
        return CheckResult(
            "find_links directories",
            Status.WARN,
            "; ".join(d for d, _ in warnings),
            hint=next((h for _, h in warnings if h), ""),
        )
    return CheckResult("find_links directories", Status.PASS, "; ".join(ok))


def check_macos_arch_coverage(
    config: Config, lock: MacosLockfile | None
) -> CheckResult:
    archs = config.macos_required.archs
    if lock is None:
        return CheckResult("Architecture coverage", Status.SKIP, "no pylock.macos.toml")

    runtime_archs = {a.arch for a in lock.python_runtime.artifacts}
    missing_runtime = [a for a in archs if a not in runtime_archs]
    if missing_runtime:
        return CheckResult(
            "Architecture coverage",
            Status.FAIL,
            f"runtime missing arch(es): {', '.join(missing_runtime)}",
            hint="re-run `kivyforge lock -p macos` after setting archs.",
        )

    for pkg in lock.packages:
        if any(w.is_pure_python for w in pkg.wheels):
            continue
        covered: set[str] = set()
        for wheel in pkg.wheels:
            arch = wheel_arch(wheel.platform_tag)
            covered |= set(archs) if arch == "universal2" else ({arch} & set(archs))
        missing = [a for a in archs if a not in covered]
        if missing:
            return CheckResult(
                "Architecture coverage",
                Status.FAIL,
                f"{pkg.name} missing wheel(s) for: {', '.join(missing)}",
                hint="a compiled dep needs a per-arch or universal2 wheel per arch; "
                "re-lock or narrow [tool.kivy.macos].archs.",
            )
    return CheckResult(
        "Architecture coverage", Status.PASS, f"all deps cover {', '.join(archs)}"
    )


def check_macos_runtime_floor(
    config: Config, lock: MacosLockfile | None
) -> CheckResult:
    declared = config.macos_required.minimum_system_version
    floor = lock.python_runtime.floor if lock else None
    if not declared or not floor:
        return CheckResult(
            "Runtime floor", Status.SKIP, "no explicit minimum_system_version/floor"
        )
    if _ver_tuple(declared) < _ver_tuple(floor):
        return CheckResult(
            "Runtime floor",
            Status.FAIL,
            f"minimum_system_version {declared} < runtime floor {floor}",
            hint=f"raise [tool.kivy.macos].minimum_system_version to >= {floor}.",
        )
    return CheckResult("Runtime floor", Status.PASS, f"{declared} >= {floor}")


def check_macos_signing_identity(probe: Probe, config: Config) -> CheckResult:
    """When Developer ID signing is configured, the identity is in the keychain."""
    signing = config.macos_required.signing
    if not signing.configured:
        return CheckResult(
            "Signing identity",
            Status.SKIP,
            "not configured (ad-hoc floor applies)",
        )
    identities = probe.keychain_identities()
    if not any(signing.identity in line for line in identities):
        return CheckResult(
            "Signing identity",
            Status.FAIL,
            f"identity {signing.identity!r} not in keychain",
            hint="import your 'Developer ID Application' certificate (Xcode -> "
            "Settings -> Accounts -> Manage Certificates), or fix "
            "[tool.kivy.macos.signing].identity.",
        )
    return CheckResult("Signing identity", Status.PASS, signing.identity)


def check_macos_notary_setup(probe: Probe, config: Config) -> CheckResult:
    """When a notary profile is configured, notarytool must be available.

    Profile *validity* needs a network round-trip to Apple, so it is verified
    at submit time; doctor only validates the local tooling.
    """
    signing = config.macos_required.signing
    if not signing.notary_profile:
        return CheckResult("Notary setup", Status.SKIP, "no notary_profile")
    if not probe.has_notarytool():
        return CheckResult(
            "Notary setup",
            Status.FAIL,
            "xcrun notarytool not found",
            hint="notarytool ships with recent Xcode command-line tools; run "
            "`xcode-select --install` / update the CLT.",
        )
    return CheckResult(
        "Notary setup",
        Status.PASS,
        f"profile {signing.notary_profile!r}; notarytool present "
        "(profile validity is checked at submit time)",
    )


def check_macos_hosts_reachable(
    probe: Probe, lock: MacosLockfile | None
) -> CheckResult:
    if lock is None:
        return CheckResult(
            "Required hosts reachable", Status.SKIP, "no pylock.macos.toml"
        )
    hosts: set[str] = set()
    for pkg in lock.packages:
        for wheel in pkg.wheels:
            if wheel.url:
                _add_host(hosts, wheel.url)
    for art in lock.python_runtime.artifacts:
        if art.url:
            _add_host(hosts, art.url)
    if not hosts:
        return CheckResult(
            "Required hosts reachable", Status.PASS, "all artifacts vendored"
        )
    unreachable = [h for h in sorted(hosts) if not probe.tcp_reachable(h, 443)]
    if unreachable:
        return CheckResult(
            "Required hosts reachable",
            Status.FAIL,
            f"unreachable: {', '.join(unreachable)}",
            hint="check your network/proxy; these hosts serve pinned artifacts.",
        )
    return CheckResult(
        "Required hosts reachable", Status.PASS, ", ".join(sorted(hosts))
    )


def _add_host(hosts: set[str], url: str) -> None:
    netloc = urlparse(url).hostname
    if netloc:
        hosts.add(netloc)
