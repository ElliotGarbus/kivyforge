"""Assemble an ``AndroidLockfile`` from a validated ``Config`` (android/02).

Resolution semantics, in the documented order: runtime per ABI (with the
``min_sdk >= min_api`` check), per-ABI wheels (fail-fasts live in the
resolver + the completeness check here), ``.aar``/``.jar`` pins, Gradle/Maven
pins (skipped without declared coordinates), ``include_files`` hashes.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from kivyforge import __version__
from kivyforge.artifacts.verify import sha256_file
from kivyforge.config.model import AndroidConfig, Config
from kivyforge.lock.find_links import (
    FindLinksError,
    find_links_resolution_hint,
    resolve_find_links,
    validate_find_links,
    wheel_path_from_project_root,
)
from kivyforge.lock.model import (
    LockedPackage,
    LockedWheel,
    PackageDep,
    canonical_name,
)
from kivyforge.lock.reader import compute_pyproject_sha256

from .archives import ArchiveResolverError, resolve_android_libs
from .maven import GradleMavenResolver, MavenResolverError, resolve_gradle_pins
from .model import (
    DEFAULT_REQUIRES_PYTHON,
    AndroidLockfile,
    LockedIncludeFile,
    PythonAndroidRuntime,
)
from .python_meta import (
    PythonAndroidError,
    PythonAndroidProvider,
    PythonOrgAndroidProvider,
)
from .resolver import Resolver, ResolverError, get_resolver

if TYPE_CHECKING:
    from kivyforge.artifacts.download import Downloader


class BuildError(Exception):
    """A lock build failure surfaced with an actionable message."""


def build_lockfile(
    config: Config,
    pyproject_text: str,
    *,
    project_root: Path | None = None,
    resolver: Resolver | None = None,
    python_provider: PythonAndroidProvider | None = None,
    maven_resolver: GradleMavenResolver | None = None,
    lib_downloader: Downloader | None = None,
    offline: bool = False,
    now: datetime | None = None,
) -> AndroidLockfile:
    if config.android is None:
        raise BuildError(
            "pyproject.toml has no [tool.kivy.android] table; nothing to lock."
        )
    android = config.android
    resolver = resolver or get_resolver("pip")
    python_provider = python_provider or PythonOrgAndroidProvider()
    root = (project_root or Path.cwd()).resolve()

    python_version = android.python_required.version

    find_links_entries = android.find_links
    try:
        validate_find_links(root, find_links_entries, platform="android")
    except FindLinksError as exc:
        raise BuildError(str(exc)) from exc
    find_links = resolve_find_links(root, find_links_entries)

    runtimes = _resolve_runtimes(
        android, python_version, python_provider, offline=offline
    )

    direct = {canonical_name(_req_name(d)) for d in config.project.dependencies}
    excluded = {canonical_name(e) for e in android.exclude}
    # You can't exclude what you explicitly depend on (android/01 §exclude).
    excluded -= direct

    try:
        resolved = resolver.resolve(
            list(config.project.dependencies),
            python_version=python_version,
            min_sdk=android.min_sdk,
            abis=tuple(android.abis),
            extra_index_urls=list(android.extra_index_urls),
            find_links=find_links,
            offline=offline,
        )
    except ResolverError as exc:
        hint = find_links_resolution_hint(
            root, find_links_entries, pip_stderr=str(exc), platform="android"
        )
        if hint:
            raise BuildError(f"{exc}\n{hint}") from exc
        raise BuildError(str(exc)) from exc

    packages = []
    for rp in resolved:
        if canonical_name(rp.name) in excluded:
            continue
        wheels = tuple(
            _locked_wheel_from_resolved(w, project_root=root) for w in rp.wheels
        )
        _check_abis_complete(rp.name, wheels, android.min_sdk, android.abis)
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

    try:
        android_libs = resolve_android_libs(
            android.aars + android.jars,
            project_root=root,
            downloader=lib_downloader,
            offline=offline,
        )
    except ArchiveResolverError as exc:
        raise BuildError(str(exc)) from exc

    try:
        gradle_pins = resolve_gradle_pins(
            android.gradle, resolver=maven_resolver, offline=offline
        )
    except MavenResolverError as exc:
        raise BuildError(str(exc)) from exc

    include_files = _hash_include_files(android, root)

    return AndroidLockfile(
        requires_python=config.project.requires_python or DEFAULT_REQUIRES_PYTHON,
        packages=tuple(packages),
        python_android=tuple(runtimes),
        kivyforge_version=__version__,
        generated_at=(now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        pyproject_sha256=compute_pyproject_sha256(pyproject_text),
        tool_kivy_android_schema_version=android.schema_version,
        sdl=android.sdl,
        android_libs=tuple(android_libs),
        gradle=gradle_pins,
        include_files=tuple(include_files),
    )


def _resolve_runtimes(
    android: AndroidConfig,
    python_version: str,
    provider: PythonAndroidProvider,
    *,
    offline: bool,
) -> list[PythonAndroidRuntime]:
    runtimes: list[PythonAndroidRuntime] = []
    for abi in android.abis:
        try:
            info = provider.get(python_version, abi, offline=offline)
        except PythonAndroidError as exc:
            raise BuildError(str(exc)) from exc
        if android.min_sdk < info.min_api:
            raise BuildError(
                f"[tool.kivy.android].min_sdk {android.min_sdk} is below the "
                f"python.org runtime's minimum API {info.min_api} "
                f"(Python {python_version}, {abi}).\n"
                f"  Raise min_sdk to at least {info.min_api}."
            )
        runtimes.append(
            PythonAndroidRuntime(
                version=info.version,
                abi=info.abi,
                url=info.url,
                sha256=info.sha256,
                min_api=info.min_api,
            )
        )
    return runtimes


def _hash_include_files(android: AndroidConfig, root: Path) -> list[LockedIncludeFile]:
    """One pin per staged file; a directory source expands to its files."""
    pins: list[LockedIncludeFile] = []
    for entry in android.include_files:
        for source in entry.sources:
            local = (root / source).resolve()
            if local.is_dir():
                for child in sorted(local.rglob("*")):
                    if child.is_file():
                        rel = (Path(source) / child.relative_to(local)).as_posix()
                        pins.append(
                            LockedIncludeFile(
                                source=rel,
                                dest=entry.dest,
                                sha256=sha256_file(child),
                            )
                        )
            elif local.is_file():
                pins.append(
                    LockedIncludeFile(
                        source=Path(source).as_posix(),
                        dest=entry.dest,
                        sha256=sha256_file(local),
                    )
                )
            else:
                raise BuildError(
                    f"include_files source does not exist: {source} "
                    f"(resolved to {local})"
                )
    pins.sort(key=lambda p: (p.dest, p.source))
    return pins


def _locked_wheel_from_resolved(w, *, project_root: Path) -> LockedWheel:
    url, path = _normalize_wheel_source(w.url, project_root=project_root)
    sha256 = w.sha256
    if not sha256 and path:
        sha256 = sha256_file((project_root / path).resolve())
    if not sha256:
        raise BuildError(
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
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    if url.startswith(("http://", "https://")):
        return url, None
    if url.startswith("file:"):
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
            f"(e.g. examples/wheels/android/)."
        ) from exc
    return None, rel


def _check_abis_complete(
    name: str,
    wheels: tuple[LockedWheel, ...],
    min_sdk: int,
    abis: tuple[str, ...],
) -> None:
    """Fail fast if a compiled package is missing a targeted ABI (android/02).

    Compatibility rule: an ``android_<api>_<abi>`` wheel covers a targeted ABI
    when its tag API level is <= ``min_sdk`` (the tag is a floor, android/01
    §find_links) and the ABI matches exactly. Pure-Python packages are complete
    with their single ``py3-none-any`` entry.
    """
    if any(w.is_pure_python for w in wheels):
        return
    covered: set[str] = set()
    for wheel in wheels:
        tag = wheel.platform_tag  # e.g. "android_24_arm64_v8a"
        parts = tag.split("_", 2)  # ["android", "24", "arm64_v8a"]
        if parts[0] != "android" or len(parts) != 3:
            continue
        try:
            api = int(parts[1])
        except ValueError:
            continue
        if api <= min_sdk and parts[2] in abis:
            covered.add(parts[2])
    missing = [abi for abi in abis if abi not in covered]
    if missing:
        tags = ", ".join(f"android_{min_sdk}_{abi}" for abi in missing)
        raise BuildError(
            f"{name} is missing Android wheel slice(s): {tags}.\n"
            f"  A compiled package must publish (or vendor via find_links) a "
            f"wheel for every targeted ABI to be locked reproducibly; narrow "
            f"[tool.kivy.android].abis or supply the missing wheel (android/03)."
        )


def semantic_equal(a: AndroidLockfile, b: AndroidLockfile) -> bool:
    """Compare two lockfiles ignoring the volatile ``generated_at`` field."""
    return dataclasses.replace(a, generated_at="") == dataclasses.replace(
        b, generated_at=""
    )


def diff_summary(old: AndroidLockfile, new: AndroidLockfile) -> list[str]:
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
    old_rt = {r.abi: r.version for r in old.python_android}
    new_rt = {r.abi: r.version for r in new.python_android}
    if old_rt != new_rt:
        out.append(f"  ~ python.org Android runtime: {old_rt} -> {new_rt}")
    return out


def _req_name(requirement: str) -> str:
    from packaging.requirements import InvalidRequirement, Requirement

    try:
        return Requirement(requirement).name
    except InvalidRequirement:
        return requirement
