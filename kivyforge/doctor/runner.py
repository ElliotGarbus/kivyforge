"""Assemble doctor checks for environment or project mode (spec 05)."""

from __future__ import annotations

from pathlib import Path

from ..config.model import Config
from ..lock.linux import LinuxLockfile
from ..lock.model import Lockfile
from . import checks as C
from . import checks_linux as L
from .probe import Probe
from .result import CheckResult, Status


def run_checks(
    probe: Probe,
    *,
    kivyforge_version: str,
    config: Config | None = None,
    project_root: Path | None = None,
    lock: Lockfile | None = None,
    offline: bool = False,
) -> list[CheckResult]:
    """Run all checks. Project checks SKIP in environment mode (no config)."""
    project_root = project_root or Path.cwd()
    results = [
        C.check_xcode_version(probe),
        C.check_command_line_tools(probe),
        C.check_pip_version(probe),
        C.check_simulator_runtimes(probe, config),
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
        C.check_signing_identity(probe, config),
        C.check_provisioning_profile(config, project_root),
        C.check_app_icon(config, project_root),
        C.check_swift_toolchain(probe, config),
        C.check_find_links(config, project_root),
        C.check_hosts_reachable(probe, lock),
        C.check_app_native_binaries(probe, config, project_root),
        C.check_app_privacy_manifest(config, project_root),
        C.check_xcframework_privacy_manifests(config, project_root),
    ]
    return results


def run_linux_checks(
    probe: Probe,
    *,
    kivyforge_version: str,
    config: Config | None = None,
    project_root: Path | None = None,
    lock: LinuxLockfile | None = None,
    offline: bool = False,
) -> list[CheckResult]:
    """Run Linux doctor checks (linux-spec). Project checks SKIP without config."""
    project_root = project_root or Path.cwd()
    results = [
        L.check_linux_host(probe),
        L.check_gl_libraries(probe),
        L.check_display_session(probe),
        C.check_kivyforge_version(probe, kivyforge_version, offline=offline),
    ]

    if config is None:
        for name in (
            "App source directory",
            "glibc floor",
            "Architecture coverage",
            "App icon",
            "Desktop entry valid",
            "find_links directories",
            "Required hosts reachable",
        ):
            results.append(CheckResult(name, Status.SKIP, C.SKIP_NOTE))
        return results

    results += [
        C.check_app_dir(config, project_root),
        L.check_linux_glibc_floor(config, lock),
        L.check_linux_arch_coverage(config, lock),
        L.check_linux_app_icon(config, project_root),
        L.check_linux_desktop_entry(probe, config),
        L.check_linux_find_links(config, project_root),
        L.check_linux_hosts_reachable(probe, config, lock),
    ]
    return results
