"""Linux-specific doctor checks (linux-spec).

Reuses the platform-neutral checks (kivyforge version, app source dir) from
``checks`` and adds the Linux environment (host libc, GL libraries, display
session) and project checks (glibc floor, arch coverage, icon, generated
``.desktop`` validity, find_links, reachable hosts) over the
``pylock.linux.toml`` model. The reachable-hosts check also covers the pinned
appimagetool / type2-runtime asset hosts, since packaging fetches them.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import urlparse

from kivyforge.config import ConfigError, load_config
from kivyforge.config.icons import APP_ICON_SIZE, icon_source_problem
from kivyforge.config.model import Config
from kivyforge.doctor import checks_common as C
from kivyforge.doctor.checks_common import _ver_tuple
from kivyforge.doctor.probe import Probe, RealProbe
from kivyforge.doctor.result import CheckResult, Status
from kivyforge.lock.find_links import find_links_doctor_detail
from kivyforge.lock.reader import LockError

from . import AppDirError
from .appimage import appimagetool_asset, type2_runtime_asset
from .desktop import render_desktop_entry
from .elftools import ARCH_ELF, describe, elf_machine, is_elf
from .lock import (
    LinuxLockfile,
    effective_glibc_floor,
    linux_wheel_coverage,
    load,
)
from .lock.runtime import DEFAULT_GLIBC_FLOOR

_GL_LIBS = ("libGL.so.1", "libEGL.so.1")


# ---- environment checks -------------------------------------------------


def check_linux_host(probe: Probe) -> CheckResult:
    host = probe.host_system()
    if host != "Linux":
        return CheckResult(
            "Host is Linux",
            Status.FAIL,
            f"host is {host!r}",
            hint="the AppImage/AppDir backend bundles a gnu/glibc "
            "python-build-standalone runtime and requires a Linux host.",
        )
    if probe.linux_libc() == "musl":
        return CheckResult(
            "Host is Linux",
            Status.WARN,
            "musl libc host",
            hint="the bundled python-build-standalone runtime is a gnu/glibc "
            "build and will not run on musl (Alpine); build on a glibc host.",
        )
    return CheckResult("Host is Linux", Status.PASS, "Linux (glibc)")


def check_gl_libraries(probe: Probe) -> CheckResult:
    libs = probe.shared_libraries()
    missing = [lib for lib in _GL_LIBS if lib not in libs]
    if missing:
        return CheckResult(
            "GL libraries",
            Status.WARN,
            f"{', '.join(missing)} not found by ldconfig",
            hint="libGL/libEGL come from the host, never the bundle. Install "
            "your distro's OpenGL runtime (Debian/Ubuntu: libgl1 libegl1; "
            "Fedora: mesa-libGL mesa-libEGL).",
        )
    return CheckResult("GL libraries", Status.PASS, ", ".join(_GL_LIBS))


def check_display_session(probe: Probe) -> CheckResult:
    sessions = probe.display_session()
    if not sessions:
        return CheckResult(
            "Display session",
            Status.WARN,
            "no DISPLAY or WAYLAND_DISPLAY",
            hint="the app needs an X11 or Wayland session to open a window; "
            "for headless CI run it under `xvfb-run` with software GL.",
        )
    return CheckResult("Display session", Status.PASS, ", ".join(sorted(sessions)))


# ---- project checks -----------------------------------------------------


def check_linux_glibc_floor(config: Config, lock: LinuxLockfile | None) -> CheckResult:
    declared = config.linux_required.glibc_floor
    runtime_floor = (lock.python_runtime.floor if lock else None) or DEFAULT_GLIBC_FLOOR
    if declared and _ver_tuple(declared) < _ver_tuple(runtime_floor):
        return CheckResult(
            "glibc floor",
            Status.FAIL,
            f"glibc_floor {declared} < runtime floor {runtime_floor}",
            hint=f"raise [tool.kivy.linux].glibc_floor to >= {runtime_floor}.",
        )
    if lock is None:
        return CheckResult("glibc floor", Status.SKIP, "no pylock.linux.toml")
    effective = effective_glibc_floor(lock)
    return CheckResult(
        "glibc floor", Status.PASS, f"effective host floor glibc {effective}"
    )


def check_linux_arch_coverage(
    config: Config, lock: LinuxLockfile | None
) -> CheckResult:
    archs = config.linux_required.archs
    if lock is None:
        return CheckResult("Architecture coverage", Status.SKIP, "no pylock.linux.toml")

    runtime_archs = {a.arch for a in lock.python_runtime.artifacts}
    missing_runtime = [a for a in archs if a not in runtime_archs]
    if missing_runtime:
        return CheckResult(
            "Architecture coverage",
            Status.FAIL,
            f"runtime missing arch(es): {', '.join(missing_runtime)}",
            hint="re-run `kivyforge lock -p linux` after setting archs.",
        )

    plain_linux_warnings: list[str] = []
    for pkg in lock.packages:
        if any(w.is_pure_python for w in pkg.wheels):
            continue
        # Source-aware coverage: a plain linux_* wheel counts only when vendored
        # via find_links, and yields the mandated no-glibc-promise warning.
        covered: set[str] = set()
        for wheel in pkg.wheels:
            wheel_archs, warning = linux_wheel_coverage(wheel, archs)
            covered.update(wheel_archs)
            if warning:
                plain_linux_warnings.append(f"{pkg.name}: {warning}")
        missing = [a for a in archs if a not in covered]
        if missing:
            return CheckResult(
                "Architecture coverage",
                Status.FAIL,
                f"{pkg.name} missing manylinux wheel(s) for: {', '.join(missing)}",
                hint="a compiled dep needs a manylinux wheel per arch; raise "
                "[tool.kivy.linux].glibc_floor or supply it via "
                "extra_index_urls/find_links, then re-lock.",
            )
    if plain_linux_warnings:
        return CheckResult(
            "Architecture coverage",
            Status.WARN,
            f"covers {', '.join(archs)} but relies on vendored plain linux_* wheel(s)",
            hint="; ".join(plain_linux_warnings),
        )
    return CheckResult(
        "Architecture coverage", Status.PASS, f"all deps cover {', '.join(archs)}"
    )


def check_linux_app_icon(config: Config, project_root: Path) -> CheckResult:
    source = config.linux_required.icons.source
    if not source:
        return CheckResult("App icon", Status.SKIP, "not configured")
    problem = icon_source_problem((project_root / source).resolve())
    if problem:
        return CheckResult("App icon", Status.FAIL, f"{source} invalid", hint=problem)
    return CheckResult("App icon", Status.PASS, f"{APP_ICON_SIZE}x{APP_ICON_SIZE} PNG")


def check_linux_desktop_entry(probe: Probe, config: Config) -> CheckResult:
    if not probe.has_desktop_file_validate():
        return CheckResult(
            "Desktop entry valid",
            Status.SKIP,
            "desktop-file-validate not installed",
        )
    app_id = config.linux_required.app_id
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{app_id}.desktop"
        path.write_text(render_desktop_entry(config), encoding="utf-8")
        errors = probe.desktop_file_errors(path)
    if errors:
        return CheckResult(
            "Desktop entry valid",
            Status.FAIL,
            "generated .desktop failed validation",
            hint=errors,
        )
    return CheckResult("Desktop entry valid", Status.PASS, f"{app_id}.desktop")


def check_linux_find_links(config: Config, project_root: Path) -> CheckResult:
    entries = config.linux_required.find_links
    if not entries:
        return CheckResult("find_links directories", Status.SKIP, "not configured")
    root = project_root.resolve()
    problems: list[tuple[str, str | None]] = []
    warnings: list[tuple[str, str | None]] = []
    ok: list[str] = []
    for entry in entries:
        path = (root / entry).resolve()
        detail, hint = find_links_doctor_detail(root, entry, path, platform="linux")
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


def check_linux_native_binaries(config: Config, project_root: Path) -> CheckResult:
    """Vendored native-binary sources exist and (once built) match the arch.

    SKIPs when no ``[tool.kivy.linux.native.binaries]`` are declared. Vendored
    (repo-relative) sources must be present on disk; URL sources are re-checked
    for reachability by ``check_linux_hosts_reachable``. No two single-file
    (non-archive) sources may share a staged basename (they would overwrite each
    other in ``usr/bin``; archive-member collisions are caught at build time).
    When the AppDir has been built, every ELF staged under ``usr/bin`` must match
    each configured arch's class + machine (a 32-bit / aarch64 ``.so`` in an
    x86_64 AppImage would only fail at ``dlopen`` time).
    """
    declared = config.linux_required.binaries
    if not declared:
        return CheckResult("Native binaries", Status.SKIP, "not configured")

    root = project_root.resolve()
    missing = [
        dep.source
        for dep in declared
        if not dep.source.startswith(("http://", "https://"))
        and not (root / dep.source).is_file()
    ]
    if missing:
        return CheckResult(
            "Native binaries",
            Status.FAIL,
            f"vendored source(s) not found: {', '.join(missing)}",
            hint="build/vendor the artifact under the project and re-run "
            "`kivyforge lock -p linux`.",
        )

    # Statically-detectable staging collisions: two single-file (non-archive)
    # sources whose basenames match land on the same usr/bin/<name> and the
    # second silently clobbers the first. Archive-member collisions need
    # extraction and are caught (loudly) at build time.
    staged: dict[str, str] = {}
    for dep in declared:
        if dep.source.lower().endswith((".zip", ".tar.gz", ".tgz")):
            continue
        base = dep.source.rsplit("/", 1)[-1] or dep.name
        prev = staged.get(base)
        if prev is not None:
            return CheckResult(
                "Native binaries",
                Status.FAIL,
                f"{prev!r} and {dep.name!r} both stage usr/bin/{base}",
                hint="two native binaries would overwrite each other in "
                "usr/bin; rename one artifact/source so each stages to a "
                "unique name.",
            )
        staged[base] = dep.name

    archs = config.linux_required.archs
    expected = {ARCH_ELF[a] for a in archs if a in ARCH_ELF}
    bin_dir = (
        root
        / "build"
        / "linux"
        / f"{config.display_name}.AppDir"
        / "usr"
        / "bin"
    )
    if expected and bin_dir.is_dir():
        problems: list[str] = []
        elves = 0
        for p in sorted(bin_dir.rglob("*")):
            if not is_elf(p):
                continue
            elves += 1
            found = elf_machine(p)
            if found not in expected:
                want = ", ".join(sorted(describe(c, m) for c, m in expected))
                problems.append(f"{p.name} is {describe(*found)}, need {want}")
        if problems:
            return CheckResult(
                "Native binaries",
                Status.FAIL,
                "; ".join(problems),
                hint="rebuild the native binaries for the configured arch "
                f"({', '.join(archs)}), then re-lock.",
            )
        return CheckResult(
            "Native binaries",
            Status.PASS,
            f"{elves} ELF match {', '.join(archs)}",
        )
    return CheckResult(
        "Native binaries",
        Status.PASS,
        f"{len(declared)} declared; sources present (build to verify arch match)",
    )


def check_linux_hosts_reachable(
    probe: Probe, config: Config, lock: LinuxLockfile | None
) -> CheckResult:
    hosts: set[str] = set()
    if lock is not None:
        for pkg in lock.packages:
            for wheel in pkg.wheels:
                if wheel.url:
                    _add_host(hosts, wheel.url)
        for art in lock.python_runtime.artifacts:
            if art.url:
                _add_host(hosts, art.url)
        for nb in lock.native_binaries:
            if nb.url:
                _add_host(hosts, nb.url)
    # Packaging fetches the pinned build tools too, so their hosts matter.
    for arch in config.linux_required.archs:
        try:
            _add_host(hosts, appimagetool_asset(arch)[0])
            _add_host(hosts, type2_runtime_asset(arch)[0])
        except AppDirError:
            continue
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
            hint="check your network/proxy; these hosts serve pinned wheels, the "
            "runtime, and the appimagetool/type2-runtime build tools.",
        )
    return CheckResult(
        "Required hosts reachable", Status.PASS, ", ".join(sorted(hosts))
    )


def _add_host(hosts: set[str], url: str) -> None:
    netloc = urlparse(url).hostname
    if netloc:
        hosts.add(netloc)


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
        check_linux_host(probe),
        check_gl_libraries(probe),
        check_display_session(probe),
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
            "Native binaries",
            "Required hosts reachable",
        ):
            results.append(CheckResult(name, Status.SKIP, C.SKIP_NOTE))
        return results

    results += [
        C.check_app_dir(config, project_root),
        check_linux_glibc_floor(config, lock),
        check_linux_arch_coverage(config, lock),
        check_linux_app_icon(config, project_root),
        check_linux_desktop_entry(probe, config),
        check_linux_find_links(config, project_root),
        check_linux_native_binaries(config, project_root),
        check_linux_hosts_reachable(probe, config, lock),
    ]
    return results


def linux_doctor(
    cwd: Path, *, kivyforge_version: str, offline: bool
) -> list[CheckResult]:
    """Load the Linux project + lock (if present) and run the Linux check set."""
    pyproject = cwd / "pyproject.toml"
    config = None
    lock = None
    parse_results: list[CheckResult] = []
    if pyproject.is_file():
        try:
            config = load_config(pyproject, require_ios=False, require_linux=True)
        except ConfigError as exc:
            parse_results.append(
                CheckResult("pyproject.toml", Status.FAIL, exc.format())
            )
        lockfile = cwd / "pylock.linux.toml"
        if lockfile.is_file():
            try:
                lock = load(lockfile)
            except LockError as exc:
                parse_results.append(C.lock_parse_fail("linux", exc))
    return parse_results + run_linux_checks(
        RealProbe(),
        kivyforge_version=kivyforge_version,
        config=config,
        project_root=cwd,
        lock=lock,
        offline=offline,
    )
