"""macOS wheel resolver (macos-spec §"pylock.macos.toml").

Resolves ``[project].dependencies`` to fully-pinned macOS wheels, host- and
arch-independent: pip runs once per requested architecture with that arch's
macOS platform tag, and the results are merged. A ``universal2`` wheel satisfies
either arch. A compiled package missing a required arch (with no universal2
fallback) is a fail-fast at lock time — the macOS analog of a missing iOS slice.

The pip mechanics mirror the iOS resolver (dry-run ``--report`` per platform
tag); the shared, platform-neutral helpers live in ``kivyforge.lock.resolver``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..model import canonical_name
from ..resolver import (
    MIN_PIP_VERSION,
    _dep_names,
    abi_tags,
    pip_python_version,
    pip_version,
    version_str,
)

# Default macOS deployment floor used to build the pip ``--platform`` request
# when the project sets no ``minimum_system_version``. pip matches wheels tagged
# at or below this floor (plus universal2), so a conservative floor maximizes
# compatible wheels while still excluding wheels that need a newer OS.
DEFAULT_MACOS_FLOOR = "11.0"

VALID_WHEEL_ARCHS = frozenset({"arm64", "x86_64", "universal2"})


class MacosResolverError(Exception):
    """A macOS resolution failure (missing arch, non-wheel, backend error)."""


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


def macos_platform_tag(floor: str, arch: str) -> str:
    """The pip ``--platform`` tag for a macOS deployment floor + arch."""
    return f"macosx_{floor.replace('.', '_')}_{arch}"


def wheel_arch(platform_tag: str) -> str | None:
    """The architecture a macOS wheel platform tag targets, or ``None``.

    ``macosx_11_0_arm64`` -> ``arm64``; ``macosx_11_0_x86_64`` -> ``x86_64``;
    ``..._universal2`` -> ``universal2``. A non-macOS/pure-python tag returns
    ``None``. The arch is what follows the ``macosx_<major>_<minor>_`` prefix
    (note ``x86_64`` itself contains an underscore, so a naive rsplit is wrong).
    """
    match = re.fullmatch(r"macosx_\d+_\d+_(.+)", platform_tag)
    if match is None:
        return None
    arch = match.group(1)
    return arch if arch in VALID_WHEEL_ARCHS else None


class MacosResolver(Protocol):
    def resolve(
        self,
        requirements: list[str],
        *,
        python_version: str,
        archs: tuple[str, ...],
        floor: str,
        extra_index_urls: list[str],
        find_links: list[str] | None = None,
        offline: bool = False,
    ) -> list[ResolvedPackage]:
        """Resolve requirements to macOS wheels for every requested arch."""
        ...


class PipMacosResolver:
    """Default backend: stock pip cross-resolution via ``pip install --report``."""

    def __init__(self, python_executable: str | None = None) -> None:
        self._python = python_executable or sys.executable

    def resolve(
        self,
        requirements: list[str],
        *,
        python_version: str,
        archs: tuple[str, ...],
        floor: str,
        extra_index_urls: list[str],
        find_links: list[str] | None = None,
        offline: bool = False,
    ) -> list[ResolvedPackage]:
        if not requirements:
            return []
        self._require_modern_pip()
        abis = abi_tags(python_version)
        merged: dict[str, ResolvedPackage] = {}
        seen_filenames: dict[str, set[str]] = {}

        for arch in archs:
            tag = macos_platform_tag(floor, arch)
            report = self._run_report(
                requirements,
                python_version=python_version,
                platform_tag=tag,
                abis=abis,
                extra_index_urls=extra_index_urls,
                find_links=find_links or [],
                offline=offline,
            )
            for item in report.get("install", []):
                self._absorb(item, merged, seen_filenames)

        return list(merged.values())

    def _require_modern_pip(self) -> None:
        version = pip_version(self._python)
        if version is not None and version < MIN_PIP_VERSION:
            raise MacosResolverError(
                f"kivyforge needs pip >= {version_str(MIN_PIP_VERSION)} to resolve "
                f"macOS wheels, but {self._python} has pip {version_str(version)}.\n"
                f"  Upgrade it: {self._python} -m pip install --upgrade pip"
            )

    def _absorb(self, item, merged, seen_filenames) -> None:
        meta = item.get("metadata", {})
        name = meta.get("name")
        version = meta.get("version")
        download = item.get("download_info", {})
        url = download.get("url", "")
        if not url.endswith(".whl"):
            raise MacosResolverError(
                f"{name} {version} resolved to a non-wheel source ({url}); "
                "kivyforge installs only macOS wheels (no on-host compile)."
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
                dependencies=_dep_names(meta.get("requires_dist", [])),
            )
            merged[key] = pkg
            seen_filenames[key] = set()
        elif version != pkg.version:
            raise MacosResolverError(
                f"{name} resolved to inconsistent versions across macOS arches: "
                f"{pkg.version!r} and {version!r}. Every arch of a package must "
                "pin the same version."
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
    ) -> dict:
        with tempfile.TemporaryDirectory(prefix="kivy-macos-lock-") as tmp:
            report_path = Path(tmp) / "report.json"
            cmd = [
                self._python,
                "-m",
                "pip",
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

            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise MacosResolverError(
                    f"pip could not resolve macOS wheels for {platform_tag!r}.\n"
                    f"  This usually means a dependency has no macOS wheel for "
                    f"that arch upstream.\n"
                    f"  pip said:\n{_indent(proc.stderr or proc.stdout)}"
                )
            try:
                return json.loads(report_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise MacosResolverError(f"could not read pip report: {exc}") from exc


def get_macos_resolver(backend: str = "pip", **kwargs) -> MacosResolver:
    if backend == "pip":
        return PipMacosResolver(**kwargs)
    raise MacosResolverError(f"unknown resolver backend {backend!r} (expected pip)")


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in (text or "").splitlines())
