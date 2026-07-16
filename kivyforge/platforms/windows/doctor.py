r"""Windows-specific doctor checks (windows-spec).

Reuses the platform-neutral checks (kivyforge version, app source dir) and adds
the Windows environment (host OS, long-path support) and project checks (app_id
style, ``win_amd64`` arch coverage, icon, native-binary sources / collisions /
arch, reachable hosts, resource assets, signtool + signing certificate,
find_links) over the ``pylock.windows.toml`` model.

Every check returns an explicit PASS / WARN / FAIL / SKIP; ``doctor`` exits
non-zero only on FAIL. Signing checks SKIP unless ``[tool.kivy.windows.signing]``
is configured, and the certificate lookup targets the **same** ``store_scope``
store that ``signtool`` will use, so the two never disagree.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from kivyforge.config import ConfigError, load_config
from kivyforge.config.icons import APP_ICON_SIZE, icon_source_problem
from kivyforge.config.model import (
    WINDOWS_APP_ID_MAX_LENGTH,
    Config,
)
from kivyforge.doctor import checks_common as C
from kivyforge.doctor.probe import Probe, RealProbe
from kivyforge.doctor.result import CheckResult, Status
from kivyforge.lock.find_links import find_links_doctor_detail
from kivyforge.lock.reader import LockError

from .bundle import bundle_dir_name, onedir_path
from .lock import WindowsLockfile, load
from .naming import _RESERVED
from .petools import PeArchError, verify_pe_arch

# A well-formed AppUserModelID *style* (Microsoft's recommendation): one or more
# PascalCase segments joined by periods, e.g. ``Acme.MyApp`` or
# ``Contoso.Suite.Editor``. Only a WARN — the loader already enforces the hard
# constraints (no spaces, <=128 chars).
_APP_ID_STYLE = re.compile(r"^[A-Z][A-Za-z0-9]*(\.[A-Z][A-Za-z0-9]*)+$")

_ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz")


# ---- environment checks -------------------------------------------------


def check_windows_host(probe: Probe) -> CheckResult:
    host = probe.host_system()
    if host != "Windows":
        return CheckResult(
            "Host is Windows",
            Status.FAIL,
            f"host is {host!r}",
            hint="the onedir backend stages an MSVC amd64 "
            "python-build-standalone runtime and uses Windows-only tools "
            "(rcedit, signtool); build on a Windows host.",
        )
    return CheckResult("Host is Windows", Status.PASS, "Windows")


def check_long_path_support(probe: Probe) -> CheckResult:
    enabled = probe.long_paths_enabled()
    if enabled is None:
        return CheckResult(
            "Long-path support",
            Status.SKIP,
            "could not read LongPathsEnabled",
        )
    if not enabled:
        return CheckResult(
            "Long-path support",
            Status.WARN,
            "LongPathsEnabled is off",
            hint="a full runtime prefix under build/windows can exceed the legacy "
            "260-char MAX_PATH. Enable it: set HKLM\\SYSTEM\\CurrentControlSet\\"
            "Control\\FileSystem\\LongPathsEnabled=1 (admin), then reboot.",
        )
    return CheckResult("Long-path support", Status.PASS, "LongPathsEnabled=1")


# ---- project checks -----------------------------------------------------


def check_windows_app_id(config: Config) -> CheckResult:
    app_id = config.windows_required.app_id
    if " " in app_id or len(app_id) > WINDOWS_APP_ID_MAX_LENGTH:
        return CheckResult(
            "AppUserModelID",
            Status.FAIL,
            f"{app_id!r} violates the AppUserModelID constraints",
            hint="the AppUserModelID must contain no spaces and be at most "
            f"{WINDOWS_APP_ID_MAX_LENGTH} characters.",
        )
    if not _APP_ID_STYLE.match(app_id):
        return CheckResult(
            "AppUserModelID",
            Status.WARN,
            f"{app_id!r} is not the recommended CompanyName.ProductName style",
            hint="Microsoft recommends a PascalCase, period-delimited "
            "AppUserModelID such as 'Acme.MyApp' so taskbar grouping and jump "
            "lists behave; it still works as-is.",
        )
    return CheckResult("AppUserModelID", Status.PASS, app_id)


def check_windows_arch_coverage(
    config: Config, lock: WindowsLockfile | None
) -> CheckResult:
    archs = config.windows_required.archs
    if lock is None:
        return CheckResult(
            "Architecture coverage", Status.SKIP, "no pylock.windows.toml"
        )
    runtime_archs = {a.arch for a in lock.python_runtime.artifacts}
    missing_runtime = [a for a in archs if a not in runtime_archs]
    if missing_runtime:
        return CheckResult(
            "Architecture coverage",
            Status.FAIL,
            f"runtime missing arch(es): {', '.join(missing_runtime)}",
            hint="re-run `kivyforge lock -p windows` after setting archs.",
        )
    # arm64: this hardcodes win_amd64; generalize to each configured arch's tag
    # (windows_platform_tag(arch)) so arm64 coverage is checked too. The native
    # arch check (check_windows_native_arch) already loops per arch and needs no
    # change. See arm64-windows.md §8.
    for pkg in lock.packages:
        if any(w.is_pure_python for w in pkg.wheels):
            continue
        tags = {w.platform_tag for w in pkg.wheels}
        if "win_amd64" not in tags:
            return CheckResult(
                "Architecture coverage",
                Status.FAIL,
                f"{pkg.name} has no win_amd64 wheel",
                hint="a compiled dependency must publish a win_amd64 wheel; supply "
                "it via extra_index_urls/find_links and re-lock, or drop the dep "
                "on Windows.",
            )
    return CheckResult(
        "Architecture coverage", Status.PASS, f"all deps cover {', '.join(archs)}"
    )


def check_windows_app_icon(config: Config, project_root: Path) -> CheckResult:
    source = config.windows_required.icons.source
    if not source:
        return CheckResult("App icon", Status.SKIP, "not configured")
    problem = icon_source_problem((project_root / source).resolve())
    if problem:
        return CheckResult("App icon", Status.FAIL, f"{source} invalid", hint=problem)
    return CheckResult("App icon", Status.PASS, f"{APP_ICON_SIZE}x{APP_ICON_SIZE} PNG")


def check_windows_native_sources(config: Config, project_root: Path) -> CheckResult:
    declared = config.windows_required.binaries
    if not declared:
        return CheckResult("Native binaries: sources", Status.SKIP, "not configured")
    root = project_root.resolve()
    missing = [
        dep.source
        for dep in declared
        if not dep.source.startswith(("http://", "https://"))
        and not (root / dep.source).is_file()
    ]
    if missing:
        return CheckResult(
            "Native binaries: sources",
            Status.FAIL,
            f"vendored source(s) not found: {', '.join(missing)}",
            hint="vendor the artifact under the project and re-run "
            "`kivyforge lock -p windows` (URL sources are checked by the hosts "
            "reachability check).",
        )
    return CheckResult(
        "Native binaries: sources",
        Status.PASS,
        f"{len(declared)} declared; sources present",
    )


def check_windows_native_collision(config: Config) -> CheckResult:
    """Case-insensitive + reserved-name preflight for single-file sources.

    Windows is case-insensitive, so ``SDK.dll`` and ``sdk.dll`` would land on
    the same ``bin\\`` path; reserved device names (``NUL.dll``) are illegal.
    Archive-member collisions need extraction and are caught (loudly) at build.
    """
    declared = config.windows_required.binaries
    if not declared:
        return CheckResult("Native binaries: collision", Status.SKIP, "not configured")
    staged: dict[str, str] = {}
    for dep in declared:
        if dep.source.lower().endswith(_ARCHIVE_SUFFIXES):
            continue
        base = dep.source.rsplit("/", 1)[-1] or dep.name
        stem = base.split(".", 1)[0].upper()
        if stem in _RESERVED:
            return CheckResult(
                "Native binaries: collision",
                Status.FAIL,
                f"{dep.name!r} stages reserved device name {base!r}",
                hint="rename the artifact; Windows forbids CON/PRN/AUX/NUL/"
                "COM1-9/LPT1-9 even with an extension.",
            )
        key = base.lower()
        prev = staged.get(key)
        if prev is not None:
            return CheckResult(
                "Native binaries: collision",
                Status.FAIL,
                f"{prev!r} and {dep.name!r} both stage bin/{base} (case-insensitive)",
                hint="two native binaries would overwrite each other in bin\\; "
                "rename one so each stages to a case-insensitively unique name.",
            )
        staged[key] = dep.name
    return CheckResult(
        "Native binaries: collision", Status.PASS, "no case/reserved-name collisions"
    )


def check_windows_native_arch(config: Config, project_root: Path) -> CheckResult:
    declared = config.windows_required.binaries
    if not declared:
        return CheckResult("Native binaries: arch", Status.SKIP, "not configured")
    bin_dir = (
        project_root.resolve() / "build" / "windows" / bundle_dir_name(config) / "bin"
    )
    if not bin_dir.is_dir():
        return CheckResult(
            "Native binaries: arch", Status.SKIP, "not built (run `kivyforge build`)"
        )
    archs = config.windows_required.archs
    problems: list[str] = []
    pe_count = 0
    for path in sorted(bin_dir.rglob("*")):
        if not path.is_file():
            continue
        for arch in archs:
            try:
                verify_pe_arch(path, arch)
            except PeArchError as exc:
                problems.append(str(exc).splitlines()[0])
        pe_count += 1
    if problems:
        return CheckResult(
            "Native binaries: arch",
            Status.FAIL,
            "; ".join(problems),
            hint=f"rebuild the native binaries for {', '.join(archs)} and re-lock.",
        )
    return CheckResult(
        "Native binaries: arch", Status.PASS, f"{pe_count} staged file(s) match"
    )


def check_windows_output_lock(
    config: Config, project_root: Path, probe: Probe
) -> CheckResult:
    """Pre-flight the exact rename ``build``/``package`` performs on the onedir.

    A running instance of the app, or an Explorer/terminal window sitting in the
    output folder, holds the tree open so the assemble step can't replace it
    (``WinError 5``). Catch that before a full build is wasted. SKIP when nothing
    is built yet; WARN (not FAIL) since it is transient, user-fixable state.
    """
    onedir = onedir_path(config, project_root)
    try:
        locked = probe.build_output_locked(onedir)
    except OSError as exc:
        return CheckResult(
            "Build output not locked",
            Status.FAIL,
            "could not restore the build output after probing its lock",
            hint=str(exc),
        )
    if locked is None:
        return CheckResult("Build output not locked", Status.SKIP, "not built")
    if locked:
        return CheckResult(
            "Build output not locked",
            Status.WARN,
            f"{onedir.name!r} is held open by another process",
            hint="a running instance of the app, or an Explorer/terminal window "
            "in build\\windows, blocks build/package from replacing the folder "
            "(WinError 5); quit the app / close the window before building.",
        )
    return CheckResult("Build output not locked", Status.PASS, "replaceable")


def check_windows_build_volume(
    config: Config, project_root: Path, probe: Probe
) -> CheckResult:
    """Advise on the build volume's filesystem (Dev Drive vs NTFS).

    Never FAILs/WARNs — a normal NTFS setup is healthy. It surfaces the sanctioned
    mitigation for repeated rename-lock churn (a trusted ReFS Dev Drive, where
    Defender scans asynchronously) in the always-shown detail rather than as noise.
    """
    onedir = onedir_path(config, project_root)
    target = onedir if onedir.exists() else project_root
    fs = probe.filesystem_type(target)
    if fs is None:
        return CheckResult("Build volume", Status.SKIP, "filesystem unknown")
    if fs.upper() == "REFS":
        return CheckResult(
            "Build volume", Status.PASS, f"{fs} (Dev Drive — async Defender scanning)"
        )
    return CheckResult(
        "Build volume",
        Status.PASS,
        f"{fs}; for repeated build-lock churn a Windows 11 Dev Drive (ReFS) "
        "enables Defender performance mode (async scanning)",
    )


def check_windows_resource_assets(config: Config, project_root: Path) -> CheckResult:
    """The inputs the launcher resource-patch needs are present.

    The patch always writes ProductName / ProductVersion (from project metadata,
    always present) and, when configured, an icon (validated by the icon check).
    """
    version = config.project.version
    source = config.windows_required.icons.source
    if source and icon_source_problem((project_root / source).resolve()):
        return CheckResult(
            "Resource assets",
            Status.WARN,
            f"icon {source!r} is invalid; the launcher will ship without one",
            hint="fix the icon source (see the App icon check) so the launcher "
            "carries it.",
        )
    icon_note = "with icon" if source else "no icon (default)"
    return CheckResult(
        "Resource assets", Status.PASS, f"version {version}, {icon_note}"
    )


def check_windows_signtool(probe: Probe, config: Config) -> CheckResult:
    signing = config.windows_required.signing
    if not signing.configured:
        return CheckResult("signtool available", Status.SKIP, "signing not configured")
    if not probe.has_signtool():
        return CheckResult(
            "signtool available",
            Status.FAIL,
            "signtool not found on PATH",
            hint="install the Windows SDK (signtool ships with it) and ensure it is "
            "on PATH, or run packaging from a Developer Command Prompt.",
        )
    return CheckResult("signtool available", Status.PASS, "found")


def check_windows_signing_cert(probe: Probe, config: Config) -> CheckResult:
    signing = config.windows_required.signing
    if not signing.configured:
        return CheckResult("Signing certificate", Status.SKIP, "signing not configured")
    want = signing.thumbprint.replace(" ", "").upper()
    scope = signing.store_scope
    thumbprints = probe.code_signing_thumbprints(scope)
    matches = [t for t in thumbprints if t == want]
    store = "LocalMachine" if scope == "machine" else "CurrentUser"
    if not matches:
        return CheckResult(
            "Signing certificate",
            Status.FAIL,
            f"no code-signing cert with thumbprint {want} in Cert:\\{store}\\My",
            hint="import the code-signing certificate into the configured "
            f"store_scope ({scope}), or fix [tool.kivy.windows.signing].thumbprint.",
        )
    if len(matches) > 1:
        return CheckResult(
            "Signing certificate",
            Status.FAIL,
            f"{len(matches)} certs share thumbprint {want} in Cert:\\{store}\\My",
            hint="remove the duplicate certificate so signtool selects unambiguously.",
        )
    return CheckResult("Signing certificate", Status.PASS, f"{want} in {scope} store")


def check_windows_find_links(config: Config, project_root: Path) -> CheckResult:
    entries = config.windows_required.find_links
    if not entries:
        return CheckResult("find_links directories", Status.SKIP, "not configured")
    root = project_root.resolve()
    problems: list[tuple[str, str | None]] = []
    warnings: list[tuple[str, str | None]] = []
    ok: list[str] = []
    for entry in entries:
        path = (root / entry).resolve()
        detail, hint = find_links_doctor_detail(root, entry, path, platform="windows")
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


def check_windows_hosts_reachable(
    probe: Probe,
    config: Config,
    lock: WindowsLockfile | None,
    *,
    offline: bool = False,
) -> CheckResult:
    if offline:
        return CheckResult("Required hosts reachable", Status.SKIP, "offline")
    # (host, port) pairs: the port comes from each URL's scheme so the HTTP
    # RFC-3161 timestamp server is probed on 80, not the wheels' HTTPS 443.
    hosts: set[tuple[str, int]] = set()
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
    for url in config.windows_required.extra_index_urls:
        _add_host(hosts, url)
    # The RFC-3161 timestamp server is fetched during signing, so its host must
    # be reachable when signing is configured.
    if config.windows_required.signing.configured:
        _add_host(hosts, config.windows_required.signing.timestamp_url)
    if not hosts:
        return CheckResult(
            "Required hosts reachable", Status.PASS, "all artifacts vendored"
        )
    unreachable = sorted(
        host for host, port in hosts if not probe.tcp_reachable(host, port)
    )
    if unreachable:
        return CheckResult(
            "Required hosts reachable",
            Status.FAIL,
            f"unreachable: {', '.join(unreachable)}",
            hint="check your network/proxy; these hosts serve pinned wheels, the "
            "runtime, native binaries, and the signing timestamp server.",
        )
    return CheckResult(
        "Required hosts reachable",
        Status.PASS,
        ", ".join(sorted({host for host, _ in hosts})),
    )


def _add_host(hosts: set[tuple[str, int]], url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if host:
        port = parsed.port or (80 if parsed.scheme == "http" else 443)
        hosts.add((host, port))


_PROJECT_CHECK_NAMES = (
    "App source directory",
    "AppUserModelID",
    "Architecture coverage",
    "App icon",
    "Native binaries: sources",
    "Native binaries: collision",
    "Native binaries: arch",
    "Build output not locked",
    "Build volume",
    "Resource assets",
    "find_links directories",
    "signtool available",
    "Signing certificate",
    "Required hosts reachable",
)


def run_windows_checks(
    probe: Probe,
    *,
    kivyforge_version: str,
    config: Config | None = None,
    project_root: Path | None = None,
    lock: WindowsLockfile | None = None,
    offline: bool = False,
) -> list[CheckResult]:
    """Run Windows doctor checks (windows-spec). Project checks SKIP without config."""
    project_root = project_root or Path.cwd()
    results = [
        check_windows_host(probe),
        check_long_path_support(probe),
        C.check_kivyforge_version(probe, kivyforge_version, offline=offline),
    ]
    if config is None:
        for name in _PROJECT_CHECK_NAMES:
            results.append(CheckResult(name, Status.SKIP, C.SKIP_NOTE))
        return results

    results += [
        C.check_app_dir(config, project_root),
        check_windows_app_id(config),
        check_windows_arch_coverage(config, lock),
        check_windows_app_icon(config, project_root),
        check_windows_native_sources(config, project_root),
        check_windows_native_collision(config),
        check_windows_native_arch(config, project_root),
        check_windows_output_lock(config, project_root, probe),
        check_windows_build_volume(config, project_root, probe),
        check_windows_resource_assets(config, project_root),
        check_windows_find_links(config, project_root),
        check_windows_signtool(probe, config),
        check_windows_signing_cert(probe, config),
        check_windows_hosts_reachable(probe, config, lock, offline=offline),
    ]
    return results


def windows_doctor(
    cwd: Path, *, kivyforge_version: str, offline: bool
) -> list[CheckResult]:
    """Load the Windows project + lock (if present) and run the Windows check set."""
    pyproject = cwd / "pyproject.toml"
    config = None
    lock = None
    parse_results: list[CheckResult] = []
    if pyproject.is_file():
        try:
            config = load_config(pyproject, require_ios=False, require_windows=True)
        except ConfigError as exc:
            parse_results.append(
                CheckResult("pyproject.toml", Status.FAIL, exc.format())
            )
        lockfile = cwd / "pylock.windows.toml"
        if lockfile.is_file():
            try:
                lock = load(lockfile)
            except LockError as exc:
                parse_results.append(C.lock_parse_fail("windows", exc))
    return parse_results + run_windows_checks(
        RealProbe(),
        kivyforge_version=kivyforge_version,
        config=config,
        project_root=cwd,
        lock=lock,
        offline=offline,
    )
