"""Assemble a ``WheelRuntimeLock`` from a ``Config`` + a platform profile.

Generic orchestration shared by every wheel+runtime platform: validate/resolve
find_links, pin the runtime, resolve wheels per variant, fail-fast on any variant
a compiled dependency does not cover, and assemble the lock. The only
platform-specific inputs come from the ``PlatformLockProfile``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ... import __version__
from ...artifacts.verify import sha256_file
from ...config.model import Config, NativeBinaryDep
from ..find_links import (
    FindLinksError,
    find_links_resolution_hint,
    resolve_find_links,
    validate_find_links,
    wheel_path_from_project_root,
)
from ..model import LockedPackage, LockedWheel, PackageDep, canonical_name
from ..reader import compute_pyproject_sha256
from .model import WheelRuntimeLock
from .native_binaries import NativeBinaryResolverError, resolve_native_binaries
from .profile import PlatformLockProfile
from .resolver import WheelResolver, WheelResolverError
from .runtime import RuntimeProvider, RuntimeProviderError


class WheelRuntimeBuildError(Exception):
    """A wheel+runtime lock build failure surfaced with an actionable message."""


def build_wheel_runtime_lock(
    profile: PlatformLockProfile,
    config: Config,
    pyproject_text: str,
    *,
    project_root: Path | None = None,
    resolver: WheelResolver | None = None,
    runtime_provider: RuntimeProvider | None = None,
    native_binaries: tuple[NativeBinaryDep, ...] = (),
    offline: bool = False,
    now: datetime | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> WheelRuntimeLock:
    if profile.overlay(config) is None:
        raise WheelRuntimeBuildError(profile.missing_overlay_error())

    resolver = resolver or profile.wheel_resolver()
    runtime_provider = runtime_provider or profile.runtime_provider(config)
    root = (project_root or Path.cwd()).resolve()

    python_version = profile.python_version(config)
    variants = profile.variants(config)
    archs = profile.archs(config)

    find_links_entries = profile.find_links(config)
    try:
        validate_find_links(root, find_links_entries, platform=profile.platform)
    except FindLinksError as exc:
        raise WheelRuntimeBuildError(str(exc)) from exc
    find_links = resolve_find_links(root, find_links_entries)

    try:
        runtime = runtime_provider.resolve(python_version, archs, offline=offline)
    except RuntimeProviderError as exc:
        raise WheelRuntimeBuildError(str(exc)) from exc

    try:
        locked_native_binaries = resolve_native_binaries(
            native_binaries, project_root=root, offline=offline
        )
    except NativeBinaryResolverError as exc:
        raise WheelRuntimeBuildError(str(exc)) from exc

    declared_floor = profile.declared_floor(config)
    if (
        declared_floor
        and runtime.floor
        and _version_tuple(declared_floor) < _version_tuple(runtime.floor)
    ):
        raise WheelRuntimeBuildError(
            profile.floor_error(declared_floor, runtime.floor, python_version)
        )

    direct = {canonical_name(_req_name(d)) for d in config.project.dependencies}
    excluded = {canonical_name(e) for e in profile.exclude(config)} - direct

    try:
        resolved = resolver.resolve(
            list(config.project.dependencies),
            python_version=python_version,
            variants=variants,
            extra_index_urls=list(profile.extra_index_urls(config)),
            find_links=find_links,
            offline=offline,
        )
    except WheelResolverError as exc:
        hint = find_links_resolution_hint(
            root, find_links_entries, pip_stderr=str(exc), platform=profile.platform
        )
        if hint:
            raise WheelRuntimeBuildError(f"{exc}\n{hint}") from exc
        raise WheelRuntimeBuildError(str(exc)) from exc

    packages = []
    for rp in resolved:
        if canonical_name(rp.name) in excluded:
            continue
        wheels = tuple(
            _locked_wheel_from_resolved(profile, w, project_root=root)
            for w in rp.wheels
        )
        _check_variants_complete(profile, rp.name, wheels, archs, on_warning=on_warning)
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

    return WheelRuntimeLock(
        platform=profile.platform,
        requires_python=config.project.requires_python or ">=3.15",
        # Canonical (serializer) order so a freshly built lock compares equal to
        # its round-tripped form; ``lock --check`` re-resolves and compares
        # order-sensitively against the on-disk (sorted) lock.
        packages=tuple(sorted(packages, key=lambda p: p.sort_key)),
        python_runtime=runtime,
        archs=archs,
        kivyforge_version=__version__,
        generated_at=(now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        pyproject_sha256=compute_pyproject_sha256(pyproject_text),
        tool_kivyforge_schema_version=profile.schema_version(config),
        native_binaries=locked_native_binaries,
    )


def _locked_wheel_from_resolved(
    profile: PlatformLockProfile, w, *, project_root: Path
) -> LockedWheel:
    url, path = _normalize_wheel_source(profile, w.url, project_root=project_root)
    sha256 = w.sha256
    if not sha256 and path:
        sha256 = sha256_file((project_root / path).resolve())
    if not sha256:
        raise WheelRuntimeBuildError(
            f"could not determine SHA-256 for wheel {w.filename!r}; "
            f"re-run lock with network access or check the vendored file."
        )
    return LockedWheel(
        name=w.filename,
        url=url,
        path=path,
        sha256=sha256,
        upload_time=w.upload_time,
        size=w.size,
    )


def _normalize_wheel_source(
    profile: PlatformLockProfile, url: str, *, project_root: Path
) -> tuple[str | None, str | None]:
    if url.startswith(("http://", "https://")):
        return url, None
    if url.startswith("file:"):
        local = Path(unquote(urlparse(url).path))
    else:
        local = Path(url)
    resolved = local.resolve()
    root = project_root.resolve()
    try:
        rel = wheel_path_from_project_root(root, resolved)
    except FindLinksError as exc:
        raise WheelRuntimeBuildError(
            f"wheel resolved to {resolved}, which is outside the allowed "
            f"find_links scope for project directory {root}.\n"
            f"  {profile.wheel_scope_hint()}"
        ) from exc
    return None, rel


def _check_variants_complete(
    profile: PlatformLockProfile,
    name: str,
    wheels: tuple[LockedWheel, ...],
    archs: tuple[str, ...],
    *,
    on_warning: Callable[[str], None] | None = None,
) -> None:
    """Fail fast if a compiled package is missing a required variant.

    Pure-Python packages (a single ``py3-none-any`` wheel) are always complete.
    Coverage is source-aware: a platform may decline a wheel (and/or attach a
    non-fatal warning) based on where it came from — see
    :meth:`PlatformLockProfile.wheel_coverage`.
    """
    if any(w.is_pure_python for w in wheels):
        return
    covered: set[str] = set()
    for wheel in wheels:
        wheel_archs, warning = profile.wheel_coverage(wheel, archs)
        covered.update(wheel_archs)
        if warning and on_warning is not None:
            on_warning(warning)
    missing = [a for a in archs if a not in covered]
    if missing:
        raise WheelRuntimeBuildError(profile.coverage_error(name, missing))


def semantic_equal(a: WheelRuntimeLock, b: WheelRuntimeLock) -> bool:
    """Compare two locks ignoring the volatile ``generated_at`` field."""
    return dataclasses.replace(a, generated_at="") == dataclasses.replace(
        b, generated_at=""
    )


def diff_summary(old: WheelRuntimeLock, new: WheelRuntimeLock) -> list[str]:
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
    if old.python_runtime.version != new.python_runtime.version:
        out.append(
            f"  ~ python runtime: {old.python_runtime.version} -> "
            f"{new.python_runtime.version}"
        )
    old_nb = {b.name: b for b in old.native_binaries}
    new_nb = {b.name: b for b in new.native_binaries}
    for name in sorted(new_nb.keys() - old_nb.keys()):
        out.append(
            f"  + native binary {new_nb[name].name} {new_nb[name].version} (added)"
        )
    for name in sorted(old_nb.keys() - new_nb.keys()):
        out.append(
            f"  - native binary {old_nb[name].name} {old_nb[name].version} (removed)"
        )
    for name in sorted(old_nb.keys() & new_nb.keys()):
        o, n = old_nb[name], new_nb[name]
        if o.version != n.version or o.sha256 != n.sha256:
            out.append(f"  ~ native binary {n.name}: {o.version} -> {n.version}")
    return out


def _req_name(requirement: str) -> str:
    from packaging.requirements import InvalidRequirement, Requirement

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
