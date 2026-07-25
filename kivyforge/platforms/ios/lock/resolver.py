"""iOS dependency resolver (spec 02 §"Resolution semantics").

The resolver turns ``[project].dependencies`` into a fully-pinned set of
per-slice iOS wheels, **host-independent** — every compiled package is pinned
for the device slice (arm64) plus one slice per configured simulator
architecture, regardless of the architecture of the host running ``lock``. The
simulator architectures default to ``arm64`` + ``x86_64`` and are configurable
via ``[tool.kivy.ios].simulator_archs`` (a project that no longer needs the
Intel-host simulator can drop ``x86_64``).

Host-independence covers *marker evaluation*, not just wheel tags. pip's
``--platform`` selects acceptable tags but leaves ``sys_platform`` and friends
describing the macOS host running pip, which would wrongly admit
``sys_platform == "darwin"`` dependencies and — silently — drop
``sys_platform == "ios"`` ones. Resolution therefore runs through
``lock/_pip_shim.py``, which retargets ``packaging``'s marker environment at
the iOS slice (see ``markers.py``) before handing off to pip.

``pip`` is the backend (validated by the Phase 0 spike: see
docs/dev/resolver-findings.md). The backend is abstracted behind the
``Resolver`` protocol so unit tests can inject a fake resolver and stay hermetic.
The platform-neutral pip helpers are shared from ``kivyforge.lock.resolver``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from kivyforge.lock import _pip_shim
from kivyforge.lock._pip_shim import MARKER_ENV_VAR
from kivyforge.lock.model import canonical_name
from kivyforge.lock.resolver import (
    MIN_PIP_VERSION,
    abi_tags,
    dep_names_for_environment,
    pip_python_version,
    pip_version,
    version_str,
)

from .markers import ios_marker_environment

# Run by path, not ``-m``: the shim imports nothing from kivyforge, so it also
# works when resolving with an interpreter that only has pip installed.
_SHIM = Path(_pip_shim.__file__)

# iOS build slices (spec 02). The device slice is always arm64 — there is no
# 32-bit iOS — while the simulator slices are driven by the project's configured
# simulator architectures. ``DEFAULT_SIMULATOR_ARCHS`` mirrors
# ``config.model.DEFAULT_SIMULATOR_ARCHS``; the builder always passes the
# validated config value, so this default only serves direct/test callers. Tag
# templates are formatted with the deployment target (dots -> underscores).
DEVICE_SLICE_SUFFIX = "arm64_iphoneos"
DEFAULT_SIMULATOR_ARCHS = ("arm64", "x86_64")


class ResolverError(Exception):
    """A resolution failure (missing slice, no matching wheel, backend error)."""


@dataclass(frozen=True)
class ResolvedWheel:
    filename: str
    url: str
    sha256: str
    upload_time: str | None = None
    size: int | None = None


@dataclass
class ResolvedPackage:
    name: str
    version: str
    wheels: list[ResolvedWheel] = field(default_factory=list)
    requires_python: str | None = None
    dependencies: list[str] = field(default_factory=list)
    source_index: str | None = None


def slice_suffixes(
    simulator_archs: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """The arch+sdk suffixes for the slices a build targets.

    Always the device slice (arm64) plus one simulator slice per configured
    simulator architecture. Single source of truth for both ``slice_tags`` (lock
    resolution) and the builder's slice-coverage check.
    """
    archs = simulator_archs if simulator_archs is not None else DEFAULT_SIMULATOR_ARCHS
    return (DEVICE_SLICE_SUFFIX, *(f"{arch}_iphonesimulator" for arch in archs))


def slice_tags(
    deployment_target: str,
    simulator_archs: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    dt = deployment_target.replace(".", "_")
    return tuple(f"ios_{dt}_{suffix}" for suffix in slice_suffixes(simulator_archs))


class Resolver(Protocol):
    def resolve(
        self,
        requirements: list[str],
        *,
        python_version: str,
        deployment_target: str,
        extra_index_urls: list[str],
        find_links: list[str] | None = None,
        offline: bool = False,
        simulator_archs: tuple[str, ...] | None = None,
    ) -> list[ResolvedPackage]:
        """Resolve requirements to per-slice iOS wheels (all slices pinned)."""
        ...


class PipResolver:
    """Default backend: stock pip cross-resolution via ``pip install --report``.

    For each iOS slice we run pip in dry-run report mode with the slice's
    platform tag; the JSON report yields each resolved wheel's URL + sha256.
    Results are merged across slices into one ``ResolvedPackage`` per
    distribution. A package missing any compiled slice raises ``ResolverError``
    (fail fast at lock time, host-independent).
    """

    def __init__(self, python_executable: str | None = None) -> None:
        self._python = python_executable or sys.executable

    def resolve(
        self,
        requirements: list[str],
        *,
        python_version: str,
        deployment_target: str,
        extra_index_urls: list[str],
        find_links: list[str] | None = None,
        offline: bool = False,
        simulator_archs: tuple[str, ...] | None = None,
    ) -> list[ResolvedPackage]:
        if not requirements:
            return []
        self._require_modern_pip()
        suffixes = slice_suffixes(simulator_archs)
        tags = slice_tags(deployment_target, simulator_archs)
        abis = abi_tags(python_version)
        # name -> ResolvedPackage (merged across slices)
        merged: dict[str, ResolvedPackage] = {}
        seen_filenames: dict[str, set[str]] = {}

        for suffix, tag in zip(suffixes, tags):
            # Markers are evaluated for the *target* slice, not the macOS host
            # running pip (see markers.py); platform_machine differs between
            # the arm64 and x86_64 simulator slices.
            environment = ios_marker_environment(
                python_version=python_version, slice_suffix=suffix
            )
            report = self._run_report(
                requirements,
                python_version=python_version,
                platform_tag=tag,
                abis=abis,
                extra_index_urls=extra_index_urls,
                find_links=find_links or [],
                offline=offline,
                marker_environment=environment,
            )
            for item in report.get("install", []):
                self._absorb(item, merged, seen_filenames, environment)

        return list(merged.values())

    def _require_modern_pip(self) -> None:
        version = pip_version(self._python)
        if version is not None and version < MIN_PIP_VERSION:
            raise ResolverError(
                f"kivyforge needs pip >= {version_str(MIN_PIP_VERSION)} to resolve "
                f"iOS wheels, but {self._python} has pip {version_str(version)}.\n"
                "  pip < 24.3 predates PEP 730 iOS platform tags, so compatible "
                "wheels (e.g. ios_13_0_*) are reported as missing.\n"
                f"  Upgrade it: {self._python} -m pip install --upgrade pip"
            )

    def _absorb(self, item, merged, seen_filenames, environment) -> None:
        meta = item.get("metadata", {})
        name = meta.get("name")
        version = meta.get("version")
        download = item.get("download_info", {})
        url = download.get("url", "")
        if not url.endswith(".whl"):
            # sdist/vcs/directory are refused (spec 02): wheels only.
            raise ResolverError(
                f"{name} {version} resolved to a non-wheel source ({url}); "
                "kivyforge installs only iOS wheels (no on-device compile)."
            )
        archive = download.get("archive_info", {})
        hashes = archive.get("hashes", {})
        sha256 = hashes.get("sha256", "")
        filename = url.rsplit("/", 1)[-1]
        key = canonical_name(name)
        pkg = merged.get(key)
        if pkg is None:
            pkg = ResolvedPackage(
                name=name,
                version=version,
                requires_python=meta.get("requires_python"),
                dependencies=dep_names_for_environment(
                    meta.get("requires_dist", []), environment
                ),
            )
            merged[key] = pkg
            seen_filenames[key] = set()
        elif version != pkg.version:
            # pip resolves each iOS slice independently; if upstream only
            # published some slices for a release, a later slice can resolve to
            # a different version. Merging those would silently produce a
            # lockfile that looks pinned but installs mismatched binaries across
            # device and simulator. Fail fast, like the missing-slice case.
            raise ResolverError(
                f"{name} resolved to inconsistent versions across iOS slices: "
                f"{pkg.version!r} and {version!r}. This usually means the slices "
                "were published at different times upstream; kivyforge requires "
                "every slice of a package to pin the same version."
            )
        if filename not in seen_filenames[key]:
            seen_filenames[key].add(filename)
            pkg.wheels.append(ResolvedWheel(filename=filename, url=url, sha256=sha256))

    def _run_report(
        self,
        requirements: list[str],
        *,
        python_version: str,
        platform_tag: str,
        abis: tuple[str, ...],
        extra_index_urls: list[str],
        find_links: list[str],
        offline: bool,
        marker_environment: dict[str, str],
    ) -> dict:
        with tempfile.TemporaryDirectory(prefix="kivy-lock-") as tmp:
            report_path = Path(tmp) / "report.json"
            # Not "-m pip": the shim retargets marker evaluation at the iOS
            # slice first, then runs pip unchanged (see lock/_pip_shim.py).
            cmd = [
                self._python,
                str(_SHIM),
                "install",
                "--dry-run",
                "--ignore-installed",
                "--only-binary=:all:",
                "--python-version",
                pip_python_version(python_version),
                "--implementation",
                "cp",
                "--platform",
                platform_tag,
                "--target",
                str(Path(tmp) / "target"),
                "--report",
                str(report_path),
            ]
            for abi in abis:
                cmd += ["--abi", abi]
            for index in extra_index_urls:
                cmd += ["--extra-index-url", index]
            for link in find_links:
                cmd += ["--find-links", link]
            if offline:
                cmd += ["--no-index"]
            cmd += list(requirements)

            env = dict(os.environ)
            env[MARKER_ENV_VAR] = json.dumps(marker_environment)
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.returncode != 0:
                raise ResolverError(
                    f"pip could not resolve the iOS slice {platform_tag!r}.\n"
                    f"  This usually means a dependency has no wheel for that "
                    f"slice upstream.\n  pip said:\n{_indent(proc.stderr or proc.stdout)}"
                )
            try:
                # pip writes the report as UTF-8; never trust the locale codec
                # (cp1252 on Windows chokes on non-ASCII package metadata).
                return json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ResolverError(f"could not read pip report: {exc}") from exc


def get_resolver(backend: str = "pip", **kwargs) -> Resolver:
    if backend == "pip":
        return PipResolver(**kwargs)
    raise ResolverError(f"unknown resolver backend {backend!r} (expected pip)")


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in (text or "").splitlines())
