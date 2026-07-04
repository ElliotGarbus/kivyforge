"""Assemble a ``MacosLockfile`` from a validated ``Config`` (macos-spec)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ... import __version__
from ...artifacts.verify import sha256_file
from ...config.model import Config
from ..find_links import (
    FindLinksError,
    find_links_resolution_hint,
    resolve_find_links,
    validate_find_links,
    wheel_path_from_project_root,
)
from ..model import LockedPackage, LockedWheel, PackageDep, canonical_name
from ..reader import compute_pyproject_sha256
from .model import MacosLockfile
from .resolver import (
    DEFAULT_MACOS_FLOOR,
    MacosResolver,
    MacosResolverError,
    get_macos_resolver,
    wheel_arch,
)
from .runtime import (
    PythonBuildStandaloneProvider,
    RuntimeProvider,
    RuntimeProviderError,
)


class MacosBuildError(Exception):
    """A macOS lock build failure surfaced with an actionable message."""


def build_macos_lockfile(
    config: Config,
    pyproject_text: str,
    *,
    project_root: Path | None = None,
    resolver: MacosResolver | None = None,
    runtime_provider: RuntimeProvider | None = None,
    offline: bool = False,
    now: datetime | None = None,
) -> MacosLockfile:
    if config.macos is None:
        raise MacosBuildError(
            "pyproject.toml has no [tool.kivy.macos] table; nothing to lock."
        )
    macos = config.macos
    resolver = resolver or get_macos_resolver("pip")
    runtime_provider = runtime_provider or PythonBuildStandaloneProvider()
    root = (project_root or Path.cwd()).resolve()

    python_version = macos.python_version or "3.15.0"
    floor = macos.minimum_system_version or DEFAULT_MACOS_FLOOR

    find_links_entries = macos.find_links
    try:
        validate_find_links(root, find_links_entries)
    except FindLinksError as exc:
        raise MacosBuildError(str(exc)) from exc
    find_links = resolve_find_links(root, find_links_entries)

    try:
        runtime = runtime_provider.resolve(python_version, macos.archs, offline=offline)
    except RuntimeProviderError as exc:
        raise MacosBuildError(str(exc)) from exc

    # A user-declared minimum must be >= the runtime's own floor (if reported).
    if (
        macos.minimum_system_version
        and runtime.floor
        and _version_tuple(macos.minimum_system_version) < _version_tuple(runtime.floor)
    ):
        raise MacosBuildError(
            f"minimum_system_version {macos.minimum_system_version} is below the "
            f"macOS {runtime.floor} floor required by the Python "
            f"{python_version} runtime.\n"
            f"  Raise [tool.kivy.macos].minimum_system_version to at least "
            f"{runtime.floor}."
        )

    direct = {canonical_name(_req_name(d)) for d in config.project.dependencies}
    excluded = {canonical_name(e) for e in macos.exclude} - direct

    try:
        resolved = resolver.resolve(
            list(config.project.dependencies),
            python_version=python_version,
            archs=tuple(macos.archs),
            floor=floor,
            extra_index_urls=list(macos.extra_index_urls),
            find_links=find_links,
            offline=offline,
        )
    except MacosResolverError as exc:
        hint = find_links_resolution_hint(root, find_links_entries, pip_stderr=str(exc))
        if hint:
            raise MacosBuildError(f"{exc}\n{hint}") from exc
        raise MacosBuildError(str(exc)) from exc

    packages = []
    for rp in resolved:
        if canonical_name(rp.name) in excluded:
            continue
        wheels = tuple(
            _locked_wheel_from_resolved(w, project_root=root) for w in rp.wheels
        )
        _check_archs_complete(rp.name, wheels, macos.archs)
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

    return MacosLockfile(
        requires_python=config.project.requires_python or ">=3.15",
        packages=tuple(packages),
        python_runtime=runtime,
        archs=tuple(macos.archs),
        kivyforge_version=__version__,
        generated_at=(now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        pyproject_sha256=compute_pyproject_sha256(pyproject_text),
        tool_kivyforge_schema_version=macos.schema_version,
    )


def _locked_wheel_from_resolved(w, *, project_root: Path) -> LockedWheel:
    url, path = _normalize_wheel_source(w.url, project_root=project_root)
    sha256 = w.sha256
    if not sha256 and path:
        sha256 = sha256_file((project_root / path).resolve())
    if not sha256:
        raise MacosBuildError(
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
    url: str, *, project_root: Path
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
        raise MacosBuildError(
            f"wheel resolved to {resolved}, which is outside the allowed "
            f"find_links scope for project directory {root}.\n"
            f"  Vendored wheels must live under the project directory, a sibling "
            f"directory, or the enclosing repository (e.g. examples/wheels/macos/)."
        ) from exc
    return None, rel


def _check_archs_complete(
    name: str, wheels: tuple[LockedWheel, ...], archs: tuple[str, ...]
) -> None:
    """Fail fast if a compiled package is missing a required macOS arch.

    A ``universal2`` wheel covers every arch; a per-arch wheel covers its own.
    Pure-Python packages (a single ``py3-none-any`` wheel) are always complete.
    """
    if any(w.is_pure_python for w in wheels):
        return
    covered: set[str] = set()
    for wheel in wheels:
        arch = wheel_arch(wheel.platform_tag)
        if arch == "universal2":
            covered.update(archs)
        elif arch is not None:
            covered.add(arch)
    missing = [a for a in archs if a not in covered]
    if missing:
        raise MacosBuildError(
            f"{name} is missing macOS wheel(s) for arch(es): {', '.join(missing)}.\n"
            f"  A compiled package must publish a per-arch or universal2 wheel for "
            f"every targeted arch to be locked reproducibly.\n"
            f"  If this dependency has no Intel wheels, set "
            f'[tool.kivy.macos].archs = ["arm64"] and re-lock.'
        )


def semantic_equal(a: MacosLockfile, b: MacosLockfile) -> bool:
    """Compare two macOS lockfiles ignoring the volatile ``generated_at`` field."""
    return dataclasses.replace(a, generated_at="") == dataclasses.replace(
        b, generated_at=""
    )


def diff_summary(old: MacosLockfile, new: MacosLockfile) -> list[str]:
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
