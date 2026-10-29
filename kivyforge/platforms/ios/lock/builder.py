"""Assemble a ``Lockfile`` from a validated ``Config`` (spec 02 §"Resolution semantics")."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse
from urllib.request import url2pathname

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from kivyforge import __version__
from kivyforge.artifacts import include_files
from kivyforge.artifacts.verify import sha256_file
from kivyforge.config.model import Config, SwiftPackageDep, XcframeworkDep
from kivyforge.lock.find_links import (
    FindLinksError,
    find_links_resolution_hint,
    missing_wheel_hash_message,
    resolve_find_links,
    validate_find_links,
    wheel_path_from_project_root,
)
from kivyforge.lock.inputs import lock_inputs_sha256
from kivyforge.lock.model import (
    LockedPackage,
    LockedWheel,
    PackageDep,
    canonical_name,
)
from kivyforge.lock.prefer import preferred_pins, resolve_preferring
from kivyforge.lock.sources import (
    SourceUnavailable,
    drop_moved_pins,
    overlay_policy,
    pinned_local_warnings,
    source_changes,
    wheel_changes,
)
from kivyforge.report import diagnostics
from kivyforge.report.failures import ClassifiedError

from .markers import ios_marker_environment
from .model import (
    LockedSwiftPackage,
    Lockfile,
    PythonXcframework,
)
from .python_meta import PythonOrgProvider, PythonXcframeworkProvider
from .resolver import Resolver, ResolverError, get_resolver
from .spm import (
    ResolvedSwiftPackage,
    SpmResolver,
    SpmResolverError,
    get_spm_resolver,
)
from .xcframework import XcframeworkResolverError, resolve_xcframeworks

if TYPE_CHECKING:
    from kivyforge.artifacts.download import Downloader


class BuildError(Exception):
    """A lock build failure surfaced with an actionable message."""


class KivyUnsupported(BuildError, ClassifiedError):
    """The project would run Kivy 2.x on iOS, which kivyforge does not build.

    kivyforge builds Kivy 3 only on iOS: the mobile wheel index serves no Kivy
    2.x iOS wheel, so a 2.x requirement used to fail inside pip's resolver with
    pip's wording and nothing said that 2.x is unsupported (#109). Raised by
    :func:`check_kivy_requirements` before resolving and by
    :func:`check_kivy_supported` after, and by ``build`` on the lock it reads.
    """

    code = diagnostics.IOS_KIVY_UNSUPPORTED


#: The first Kivy 3 version. Everything below it is Kivy 2.x or older.
KIVY_3 = Version("3.0.0.dev0")

_KIVY_UNSUPPORTED = (
    "Kivy 2.x is not supported on iOS; kivyforge builds Kivy 3 only there; "
    "kivy-ios serves Kivy 2.x."
)
_KIVY_FIX = (
    "Fix: require Kivy 3 in [project].dependencies (for example "
    '"kivy>=3.0,<4"), then run `kivyforge lock -p ios`.'
)


class _Pinned(Protocol):
    """What the post-resolve check reads: a resolved or a locked package."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...


def check_kivy_requirements(
    requirements: Iterable[str], *, python_version: str
) -> None:
    """Fail before resolving when ``kivy`` is required at 2.x only.

    A requirement that admits no version from ``3.0.0.dev0`` up (``kivy<3``,
    ``kivy==2.3.1``, ``kivy~=2.3``, ``kivy==2.*``) can only resolve to Kivy
    2.x, which the iOS index does not serve, so pip's "no matching
    distribution" would be the only report. A requirement whose marker does
    not apply on iOS (``kivy<3; sys_platform != "ios"``) is not an iOS
    requirement and is left alone. Raises :class:`KivyUnsupported`.
    """
    environment = ios_marker_environment(
        python_version=python_version, slice_suffix="arm64_iphoneos"
    )
    for text in requirements:
        try:
            req = Requirement(text)
        except InvalidRequirement:
            continue
        if canonical_name(req.name) != "kivy":
            continue
        if req.marker is not None:
            try:
                if not req.marker.evaluate(environment):
                    continue
            except Exception:  # noqa: BLE001 -- an odd marker is pip's to judge
                continue
        if not _admits_kivy_3(req.specifier):
            raise KivyUnsupported(
                f"[project].dependencies requires {text!r}, which admits no "
                f"Kivy 3 release.\n  {_KIVY_UNSUPPORTED}\n  {_KIVY_FIX}",
                context={"requirement": text},
            )


def _admits_kivy_3(specifier: SpecifierSet) -> bool:
    """Whether a ``kivy`` specifier set admits any version from 3.0.0.dev0 up.

    The clauses of a set are ANDed, so one clause that alone rejects every
    such version decides it. Only a cap (``<``, ``<=``), an exact pin (``==``,
    ``===``) or a compatible release (``~=``) can be that clause; a floor or a
    ``!=`` never is. ``Specifier.contains`` applies PEP 440's rule that ``<3``
    rejects 3.0.0's pre-releases while ``<3.0.0a0`` admits ``3.0.0.dev0``.
    """
    for clause in specifier:
        op, text = clause.operator, clause.version
        if op in ("<", "<="):
            if not clause.contains(KIVY_3, prereleases=True):
                return False
        elif op in ("==", "===", "~="):
            wildcard = text.endswith(".*")
            try:
                pinned = Version(text[:-2] if wildcard else text)
            except InvalidVersion:
                continue
            if op == "~=" or wildcard:
                if pinned.major < 3:
                    return False
            elif pinned < KIVY_3:
                return False
    return True


def check_kivy_supported(packages: Iterable[_Pinned], *, lockfile: str = "") -> None:
    """Fail when the resolved or locked ``kivy`` is below Kivy 3.

    Run on the resolver's result before a lock is written, and by ``build`` on
    the lock it reads, so a lock written by hand or by an older kivyforge gets
    the same error. *lockfile* names the file in the message when there is
    one. A set without ``kivy`` passes: the app does not use it. Raises
    :class:`KivyUnsupported`.
    """
    for package in packages:
        if canonical_name(package.name) != "kivy":
            continue
        try:
            version = Version(package.version)
        except InvalidVersion:
            continue
        if version < KIVY_3:
            where = f"{lockfile} pins" if lockfile else "the lock would pin"
            raise KivyUnsupported(
                f"{where} kivy {package.version}, which is Kivy 2.x.\n"
                f"  {_KIVY_UNSUPPORTED}\n  {_KIVY_FIX}",
                context={"version": package.version},
            )


def build_lockfile(
    config: Config,
    *,
    project_root: Path | None = None,
    resolver: Resolver | None = None,
    python_provider: PythonXcframeworkProvider | None = None,
    spm_resolver: SpmResolver | None = None,
    xcframework_downloader: Downloader | None = None,
    prefer: Iterable[LockedPackage] = (),
    offline: bool = False,
    now: datetime | None = None,
    on_warning: Callable[[str], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    on_transfer: Callable[[str, int, int, str], None] | None = None,
) -> Lockfile:
    if config.ios is None:
        raise BuildError(
            "pyproject.toml has no [tool.kivy.ios] table; nothing to lock."
        )

    # Progress is wired into the default resolvers only; an injected one
    # (tests) keeps its own signature. Downloads (the python.org framework,
    # xcframework archives) report through the verb's transfer sink.
    resolver = resolver or get_resolver(
        "pip", on_progress=on_progress, on_transfer=on_transfer
    )
    python_provider = python_provider or PythonOrgProvider()
    root = (project_root or Path.cwd()).resolve()

    # [tool.kivy.ios.python].version is required (the loader raises a ConfigError
    # when it is missing), so it is always set here. Never silently substitute a
    # hidden default — that would pin an unexpected (and possibly unreleased)
    # Python instead of surfacing the misconfig.
    python_version = config.ios.python_version
    if not python_version:
        raise BuildError("missing required [tool.kivy.ios.python].version")
    find_links_entries = config.ios.find_links
    try:
        validate_find_links(root, find_links_entries)
    except FindLinksError as exc:
        raise BuildError(str(exc)) from exc
    find_links = resolve_find_links(root, find_links_entries)
    py_info = python_provider.get(python_version, offline=offline)

    # Rule 11: deployment_target must not be below the xcframework floor.
    if _version_tuple(config.ios.deployment_target) < _version_tuple(py_info.ios_floor):
        raise BuildError(
            f"deployment_target {config.ios.deployment_target} is below the "
            f"minimum iOS {py_info.ios_floor} required by Python "
            f"{python_version}'s xcframework.\n"
            f"  Raise [tool.kivy.ios].deployment_target to at least "
            f"{py_info.ios_floor}."
        )

    direct = {canonical_name(_req_name(d)) for d in config.project.dependencies}
    excluded = {canonical_name(e) for e in config.ios.exclude}

    # Excluded names that are also direct requirements are silently dropped from
    # the exclusion set — you can't exclude what you explicitly depend on.
    excluded -= direct

    ios = config.ios
    requirements = list(config.project.dependencies)
    check_kivy_requirements(requirements, python_version=python_version)

    policy = overlay_policy(ios, find_links, platform="ios", exclude=excluded)
    if on_warning is not None:
        for warning in pinned_local_warnings(policy, root):
            on_warning(warning)
    prefer = tuple(prefer)

    def resolve(pins):
        return resolver.resolve(
            requirements,
            python_version=python_version,
            deployment_target=ios.deployment_target,
            extra_index_urls=list(ios.extra_index_urls),
            find_links=find_links,
            offline=offline,
            simulator_archs=tuple(ios.simulator_archs),
            constraints=pins,
            sources=policy,
        )

    try:
        resolved = resolve_preferring(
            resolve,
            drop_moved_pins(preferred_pins(prefer, requirements), prefer, policy),
            errors=(ResolverError, SourceUnavailable),
            platform="ios",
        )
    except ResolverError as exc:
        hint = find_links_resolution_hint(
            root,
            find_links_entries,
            pip_stderr=str(exc),
        )
        if hint:
            raise BuildError(f"{exc}\n{hint}") from exc
        raise BuildError(str(exc)) from exc
    check_kivy_supported(resolved)

    packages = []
    for rp in resolved:
        if canonical_name(rp.name) in excluded:
            continue
        wheels = tuple(
            _locked_wheel_from_resolved(w, project_root=root) for w in rp.wheels
        )
        _check_slices_complete(
            rp.name,
            wheels,
            config.ios.deployment_target,
            config.ios.simulator_archs,
        )
        packages.append(
            LockedPackage(
                name=rp.name,
                version=rp.version,
                wheels=wheels,
                requires_python=rp.requires_python,
                dependencies=tuple(PackageDep(name=d) for d in rp.dependencies),
                direct_requirement=canonical_name(rp.name) in direct,
                source_index=rp.source_index,
            )
        )

    xcframeworks = _resolve_native_xcframeworks(
        config.ios.xcframeworks, xcframework_downloader, root, offline
    )

    swift_packages = _resolve_swift_packages(
        config.ios.swift_packages,
        spm_resolver or get_spm_resolver(on_progress=on_progress),
        root,
        offline,
    )

    try:
        include_pins = include_files.hash_pins(config.ios.include_files, root)
    except include_files.IncludeFilesError as exc:
        raise BuildError(str(exc)) from exc

    return Lockfile(
        requires_python=config.project.requires_python or ">=3.15",
        packages=tuple(packages),
        python_xcframework=PythonXcframework(
            version=py_info.version, url=py_info.url, sha256=py_info.sha256
        ),
        kivyforge_version=__version__,
        generated_at=(now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        lock_inputs_sha256=lock_inputs_sha256(config, "ios"),
        tool_kivyforge_schema_version=config.ios.schema_version,
        xcframeworks=tuple(xcframeworks),
        swift_packages=tuple(swift_packages),
        include_files=tuple(include_pins),
    )


def _resolve_native_xcframeworks(
    declared: tuple[XcframeworkDep, ...],
    downloader: Downloader | None,
    project_root: Path,
    offline: bool,
):
    """Resolve declared native xcframeworks; surface failures as ``BuildError``.

    The resolver fetches/reads each archive, pins its SHA-256, and enumerates the
    slices it ships, so the lock fully captures user-declared native SDKs instead
    of silently dropping them.
    """
    try:
        return resolve_xcframeworks(
            declared,
            project_root=project_root,
            downloader=downloader,
            offline=offline,
        )
    except XcframeworkResolverError as exc:
        raise BuildError(str(exc)) from exc


def _resolve_swift_packages(
    declared: tuple[SwiftPackageDep, ...],
    spm_resolver: SpmResolver | None,
    project_root: Path,
    offline: bool,
) -> list[LockedSwiftPackage]:
    """Resolve remote SPM packages to pins; assemble lock entries (sorted by name).

    Local (``path``) packages need no resolution. The resolver is only built and
    invoked when at least one remote package is declared, so a pure-wheel (or
    local-only) project never requires the Swift toolchain.
    """
    if not declared:
        return []
    remote = [p for p in declared if p.url]
    resolved: dict[str, ResolvedSwiftPackage] = {}
    if remote:
        resolver = spm_resolver or get_spm_resolver()
        try:
            for r in resolver.resolve(
                remote, project_root=project_root, offline=offline
            ):
                resolved[r.name] = r
        except SpmResolverError as exc:
            raise BuildError(str(exc)) from exc

    out: list[LockedSwiftPackage] = []
    for pkg in declared:
        pin = resolved.get(pkg.name)
        if pkg.url and pin is None:
            raise BuildError(
                f"swift package {pkg.name!r} resolved to no revision; re-run lock "
                f"with network access."
            )
        out.append(
            LockedSwiftPackage(
                name=pkg.name,
                products=pkg.products,
                url=pkg.url,
                path=pkg.path,
                requirement=pkg.requirement if pkg.url else None,
                revision=pin.revision if pin else None,
                version=pin.version if pin else None,
                link=pkg.link,
                embed=pkg.embed,
            )
        )
    out.sort(key=lambda s: s.name)
    return out


def _locked_wheel_from_resolved(w, *, project_root: Path) -> LockedWheel:
    url, path = _normalize_wheel_source(w.url, project_root=project_root)
    sha256 = w.sha256
    if not sha256 and path:
        sha256 = sha256_file((project_root / path).resolve())
    if not sha256:
        raise BuildError(missing_wheel_hash_message(w.filename, url, platform="ios"))
    return LockedWheel(
        name=w.filename,
        url=url,
        path=path,
        sha256=sha256,
        upload_time=w.upload_time,
        size=w.size,
    )


def _normalize_wheel_source(
    url: str, *, project_root: Path
) -> tuple[str | None, str | None]:
    if url.startswith(("http://", "https://")):
        return url, None
    if url.startswith("file:"):
        # url2pathname turns a file URL path into a native path on every host
        # (e.g. "/C:/x" -> "C:\\x" on Windows), which plain unquote+Path does not.
        local = Path(url2pathname(urlparse(url).path))
    else:
        local = Path(url)
    resolved = local.resolve()
    root = project_root.resolve()
    try:
        rel = wheel_path_from_project_root(root, resolved)
    except FindLinksError as exc:
        raise BuildError(
            f"wheel resolved to {resolved}, which is outside the allowed "
            f"find_links scope for project directory {root}.\n"
            f"  Vendored wheels must live under the project directory, a "
            f"sibling directory, or the enclosing repository "
            f"(e.g. examples/wheels/ios/)."
        ) from exc
    return None, rel


def _check_slices_complete(
    name, wheels, deployment_target, simulator_archs=None
) -> None:
    """Fail fast if a compiled package is missing an iOS slice (spec 02).

    The required slices are the device slice plus one per configured simulator
    architecture (``[tool.kivy.ios].simulator_archs``), so a project that drops
    ``x86_64`` is not held to a slice it no longer targets.

    Compatibility rule: a wheel tagged ios_<M>_<N>_<arch>_<sdk> satisfies a
    required slice when M.N <= deployment_target AND the arch+sdk suffix
    matches exactly.  This mirrors select_wheel's logic: python.org's iOS
    Python binary always tags wheels at its own minimum OS (currently 13.0)
    regardless of IPHONEOS_DEPLOYMENT_TARGET used when compiling the extension.
    """
    if any(w.is_pure_python for w in wheels):
        return  # pure-Python: single py3-none-any entry is complete

    from .resolver import slice_suffixes

    required = slice_suffixes(simulator_archs)
    dt_parts = _version_tuple(deployment_target)
    covered: set[str] = set()
    for wheel in wheels:
        tag = wheel.platform_tag  # e.g. "ios_13_0_arm64_iphoneos"
        parts = tag.split("_")  # ["ios", "13", "0", "arm64", "iphoneos"]
        if parts[0] != "ios" or len(parts) < 3:
            continue
        # Find where the arch+sdk suffix starts (last two underscore-joined segments).
        for suffix in required:
            if tag.endswith(f"_{suffix}"):
                prefix_parts = tag[: -(len(suffix) + 1)].split("_")  # ["ios","13","0"]
                try:
                    wheel_ver = tuple(int(x) for x in prefix_parts[1:])
                except ValueError:
                    break
                if wheel_ver <= dt_parts:
                    covered.add(suffix)
                break

    missing_suffixes = set(required) - covered
    if missing_suffixes:
        dt = deployment_target.replace(".", "_")
        missing_tags = sorted(f"ios_{dt}_{s}" for s in missing_suffixes)
        raise BuildError(
            f"{name} is missing iOS wheel slice(s): {', '.join(missing_tags)}.\n"
            f"  A compiled package must publish every targeted iOS slice "
            f"(device + each configured simulator arch) to be locked reproducibly."
        )


def semantic_equal(a: Lockfile, b: Lockfile) -> bool:
    """Compare two lockfiles ignoring the volatile ``generated_at`` field.

    Used by ``lock --check`` so a re-resolve that produces identical pins (but
    a new timestamp) still reports "in sync". ``build_lockfile`` returns
    ``packages``/``xcframeworks``/``swift_packages`` (and each package's
    ``wheels``) in resolver-encounter order; only ``writer.dumps`` sorts them
    for the file on disk (module docstring: "a deterministic ordering ...
    so diffs across runs show only real changes"). Comparing the raw,
    unsorted tuples here made ``lock --check`` report drift on *every* call
    for any project whose resolver order differs from alphabetical — which is
    effectively any project with more than one package — with an empty
    ``diff_summary`` (nothing there is order-sensitive), so the false
    positive was silent. Found validating the iOS entry_point fix on
    ``hello-kivy`` (2026-09-21): a real re-resolve reproduced the exact same
    three packages/wheels as the committed lock, `--update` wrote a file
    identical modulo ``generated_at``, yet `--check` still failed. Normalizing
    to the writer's own sort order before comparing fixes it without
    weakening the check: a real content difference still fails, in any order.
    """
    return _normalized(a) == _normalized(b)


def _normalized(lock: Lockfile) -> Lockfile:
    return dataclasses.replace(
        lock,
        generated_at="",
        packages=tuple(
            sorted(
                (
                    dataclasses.replace(
                        p, wheels=tuple(sorted(p.wheels, key=lambda w: w.name))
                    )
                    for p in lock.packages
                ),
                key=lambda p: p.sort_key,
            )
        ),
        xcframeworks=tuple(
            sorted(lock.xcframeworks, key=lambda x: (x.name.lower(), x.version))
        ),
        swift_packages=tuple(sorted(lock.swift_packages, key=lambda s: s.name)),
        include_files=tuple(sorted(lock.include_files, key=lambda p: p.key)),
    )


def diff_summary(old: Lockfile, new: Lockfile) -> list[str]:
    """Human-readable summary of what changed between two locks (for --check)."""
    out: list[str] = []
    old_pkgs = {canonical_name(p.name): p for p in old.packages}
    new_pkgs = {canonical_name(p.name): p for p in new.packages}
    for name in sorted(new_pkgs.keys() - old_pkgs.keys()):
        out.append(f"  + {new_pkgs[name].name} {new_pkgs[name].version} (added)")
    for name in sorted(old_pkgs.keys() - new_pkgs.keys()):
        out.append(f"  - {old_pkgs[name].name} {old_pkgs[name].version} (removed)")
    for name in sorted(old_pkgs.keys() & new_pkgs.keys()):
        if old_pkgs[name].version != new_pkgs[name].version:
            out.append(
                f"  ~ {new_pkgs[name].name}: "
                f"{old_pkgs[name].version} -> {new_pkgs[name].version}"
            )
    out.extend(source_changes(old.packages, new.packages))
    out.extend(wheel_changes(old.packages, new.packages))
    if old.python_xcframework.version != new.python_xcframework.version:
        out.append(
            f"  ~ Python.xcframework: {old.python_xcframework.version} -> "
            f"{new.python_xcframework.version}"
        )
    out += include_files.pin_changes(old.include_files, new.include_files)
    return out


def _req_name(requirement: str) -> str:
    try:
        return Requirement(requirement).name
    except InvalidRequirement:
        return requirement


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in v.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)
