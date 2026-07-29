"""macOS-specific doctor checks (macos-spec).

Reuses the platform-neutral checks (pip, toolchain version, app source dir) from
``checks`` and adds the macOS environment (host + codesign) and project checks
(arch coverage, runtime floor, icon, find_links, reachable hosts) over the
``pylock.macos.toml`` model.
"""

from __future__ import annotations

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

from .lock import MacosLockfile, load, wheel_arch
from .machotools import is_macho, macho_arches


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


def check_macos_not_root(probe: Probe) -> CheckResult:
    """Apple DTS: signing as root/sudo mixes execution contexts and is a common
    source of keychain errors (e.g. ``errSecInternalComponent``) — see
    "Resolving errSecInternalComponent errors during code signing".
    """
    if probe.is_root():
        return CheckResult(
            "Not running as root",
            Status.WARN,
            "running as root/sudo",
            hint="codesign relies on the keychain, which is tied to a login "
            "security context; running as root (or via sudo) often breaks "
            "that context. Run `kivyforge package` as your normal user.",
        )
    return CheckResult("Not running as root", Status.PASS, "normal user")


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
        detail, hint = find_links_doctor_detail(root, entry, path, platform="macos")
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
    if lock is None:
        return CheckResult("Architecture coverage", Status.SKIP, "no pylock.macos.toml")
    # macOS is arm64-only, so this is a single-arch check: every compiled
    # dependency needs an arm64 or universal2 wheel (universal2 contains arm64).
    target = config.macos_required.archs[0]

    if target not in {a.arch for a in lock.python_runtime.artifacts}:
        return CheckResult(
            "Architecture coverage",
            Status.FAIL,
            f"runtime missing arch: {target}",
            hint="re-run `kivyforge lock -p macos`.",
        )

    for pkg in lock.packages:
        if any(w.is_pure_python for w in pkg.wheels):
            continue
        if not any(
            wheel_arch(w.platform_tag) in ("universal2", target) for w in pkg.wheels
        ):
            return CheckResult(
                "Architecture coverage",
                Status.FAIL,
                f"{pkg.name} has no {target} wheel",
                hint=f"a compiled dep needs a {target} or universal2 wheel; re-lock.",
            )
    return CheckResult("Architecture coverage", Status.PASS, f"all deps cover {target}")


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
    """When Developer ID signing is configured, the identity is in the keychain.

    Also nudges towards Apple's "Care and Feeding of Developer ID" best practice
    of keeping the identity out of ``login.keychain-db``: a dedicated keychain
    isolates the private key from unrelated login-keychain churn (password
    resets, iCloud Keychain sync, etc.) that can corrupt its ACL and produce a
    hard-to-diagnose ``errSecInternalComponent`` from ``codesign`` (see FAQ).
    """
    signing = config.macos_required.signing
    if not signing.configured:
        return CheckResult(
            "Signing identity",
            Status.SKIP,
            "not configured (ad-hoc floor applies)",
        )
    identities = probe.keychain_identities()
    matches = [line for line in identities if signing.identity in line]
    if not matches:
        return CheckResult(
            "Signing identity",
            Status.FAIL,
            f"identity {signing.identity!r} not in keychain",
            hint="import your 'Developer ID Application' certificate (Xcode -> "
            "Settings -> Accounts -> Manage Certificates), or fix "
            "[tool.kivy.macos.signing].identity.",
        )
    if len(matches) > 1:
        return CheckResult(
            "Signing identity",
            Status.FAIL,
            f"{len(matches)} certificates match {signing.identity!r} across your "
            "keychains",
            hint="codesign refuses to pick between identically-named "
            "certificates in different keychains ('ambiguous'). Delete the "
            "stale/duplicate copy (Keychain Access -> Certificates tab) so "
            "only one remains.",
        )
    login_identities = probe.login_keychain_identities()
    if any(signing.identity in line for line in login_identities):
        return CheckResult(
            "Signing identity",
            Status.WARN,
            f"{signing.identity} is in your login keychain",
            hint="Apple recommends keeping Developer ID identities out of "
            "login.keychain-db in a dedicated keychain, so unrelated login-"
            "keychain issues can't corrupt the signing key. See FAQ.md "
            "('macOS Developer ID signing fails with errSecInternalComponent') "
            "for the migration steps.",
        )
    return CheckResult("Signing identity", Status.PASS, signing.identity)


def check_macos_signing_identity_type(config: Config) -> CheckResult:
    """Notarization only accepts a 'Developer ID Application' identity (or
    'Developer ID Installer' for pkgs); other identity types (e.g. 'Apple
    Development', used for day-to-day debugging) fail with "The binary is not
    signed with a valid Developer ID certificate." — see Apple's "Resolving
    common notarization issues".
    """
    signing = config.macos_required.signing
    if not signing.configured:
        return CheckResult(
            "Signing identity type",
            Status.SKIP,
            "not configured (ad-hoc floor applies)",
        )
    if (
        "Developer ID Application" in signing.identity
        or "Developer ID Installer" in signing.identity
    ):
        return CheckResult("Signing identity type", Status.PASS, "Developer ID")
    return CheckResult(
        "Signing identity type",
        Status.WARN,
        f"{signing.identity!r} doesn't look like a Developer ID identity",
        hint="notarization requires a 'Developer ID Application' (or "
        "'Developer ID Installer') certificate — not 'Apple Development' or "
        "another type, which is for local debugging only.",
    )


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


def check_macos_native_binaries(config: Config, project_root: Path) -> CheckResult:
    """Vendored native-binary sources exist and (once built) cover the archs.

    SKIPs when no ``[tool.kivy.macos.native.binaries]`` are declared. Vendored
    (repo-relative) sources must be present on disk; URL sources are re-checked
    for reachability by ``check_macos_hosts_reachable``. No two single-file
    (non-zip) sources may share a staged basename (they would overwrite each
    other in ``bin/``; zip-member collisions are caught at build time). When the
    bundle has been built, each Mach-O staged under ``Resources/bin`` must carry
    the target arch.
    """
    declared = config.macos_required.binaries
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
            "`kivyforge lock -p macos`.",
        )

    # Statically-detectable staging collisions: two single-file (non-zip)
    # sources whose basenames match land on the same bin/<name> and the second
    # silently clobbers the first. Zip-member collisions need extraction and are
    # caught (loudly) at build time.
    staged: dict[str, str] = {}
    for dep in declared:
        if dep.source.lower().endswith(".zip"):
            continue
        base = dep.source.rsplit("/", 1)[-1] or dep.name
        prev = staged.get(base)
        if prev is not None:
            return CheckResult(
                "Native binaries",
                Status.FAIL,
                f"{prev!r} and {dep.name!r} both stage bin/{base}",
                hint="two native binaries would overwrite each other in "
                "Contents/Resources/bin; rename one artifact/source so each "
                "stages to a unique name.",
            )
        staged[base] = dep.name

    target = config.macos_required.archs[0]
    bin_dir = (
        root
        / "build"
        / "macos"
        / f"{config.display_name}.app"
        / "Contents"
        / "Resources"
        / "bin"
    )
    if bin_dir.is_dir():
        problems: list[str] = []
        machos = 0
        for p in sorted(bin_dir.rglob("*")):
            if not is_macho(p):
                continue
            machos += 1
            if target not in set(macho_arches(p)):
                problems.append(f"{p.name} missing {target}")
        if problems:
            return CheckResult(
                "Native binaries",
                Status.FAIL,
                "; ".join(problems),
                hint=f"rebuild the native binaries for {target} "
                f"(e.g. clang -arch {target}), then re-lock.",
            )
        return CheckResult(
            "Native binaries",
            Status.PASS,
            f"{machos} Mach-O cover {target}",
        )
    return CheckResult(
        "Native binaries",
        Status.PASS,
        f"{len(declared)} declared; sources present (build to verify arch coverage)",
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
    for nb in lock.native_binaries:
        if nb.url:
            _add_host(hosts, nb.url)
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


def run_macos_checks(
    probe: Probe,
    *,
    kivyforge_version: str,
    config: Config | None = None,
    project_root: Path | None = None,
    lock: MacosLockfile | None = None,
    offline: bool = False,
) -> list[CheckResult]:
    """Run macOS doctor checks (macos-spec). Project checks SKIP without config."""
    project_root = project_root or Path.cwd()
    results = [
        check_macos_host(probe),
        check_codesign(probe),
        check_macos_not_root(probe),
        C.check_pip_version(probe),
        C.check_kivyforge_version(probe, kivyforge_version, offline=offline),
    ]

    if config is None:
        for name in (
            "App source directory",
            "Architecture coverage",
            "Runtime floor",
            "App icon",
            "find_links directories",
            "Native binaries",
            "Signing identity",
            "Signing identity type",
            "Notary setup",
            "Required hosts reachable",
        ):
            results.append(CheckResult(name, Status.SKIP, C.SKIP_NOTE))
        return results

    results += [
        C.check_app_dir(config, project_root),
        check_macos_arch_coverage(config, lock),
        check_macos_runtime_floor(config, lock),
        check_macos_app_icon(config, project_root),
        check_macos_find_links(config, project_root),
        check_macos_native_binaries(config, project_root),
        check_macos_signing_identity(probe, config),
        check_macos_signing_identity_type(config),
        check_macos_notary_setup(probe, config),
        check_macos_hosts_reachable(probe, lock),
    ]
    return results


def macos_doctor(
    cwd: Path, *, kivyforge_version: str, offline: bool
) -> list[CheckResult]:
    """Load the macOS project + lock (if present) and run the macOS check set."""
    pyproject = cwd / "pyproject.toml"
    config = None
    lock = None
    parse_results: list[CheckResult] = []
    if pyproject.is_file():
        try:
            config = load_config(pyproject, require_ios=False, require_macos=True)
        except ConfigError as exc:
            parse_results.append(
                CheckResult("pyproject.toml", Status.FAIL, exc.format())
            )
        lockfile = cwd / "pylock.macos.toml"
        if lockfile.is_file():
            try:
                lock = load(lockfile)
            except LockError as exc:
                parse_results.append(C.lock_parse_fail("macos", exc))
    return parse_results + run_macos_checks(
        RealProbe(),
        kivyforge_version=kivyforge_version,
        config=config,
        project_root=cwd,
        lock=lock,
        offline=offline,
    )
