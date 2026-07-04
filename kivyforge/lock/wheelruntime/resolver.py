"""Generic wheel resolver for the wheel+runtime family.

Resolves ``[project].dependencies`` to fully-pinned wheels, host-independent: pip
runs once per *variant* (an arch/ABI + its pip ``--platform`` tag) and the
results are merged. A wheel that satisfies several variants (e.g. macOS
``universal2``) is deduplicated by filename. The pip mechanics are identical to
the iOS resolver (dry-run ``--report`` per platform tag); only the tag list — and
the coverage rule, which lives in the platform profile — differ. The
platform-neutral pip helpers are shared from ``kivyforge.lock.resolver``.
"""

from __future__ import annotations

import json
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


class WheelResolverError(Exception):
    """A resolution failure (missing variant, non-wheel, backend error)."""


@dataclass(frozen=True)
class Variant:
    """One build variant: an arch/ABI identifier + its pip ``--platform`` tag."""

    arch: str
    platform_tag: str


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


class WheelResolver(Protocol):
    def resolve(
        self,
        requirements: list[str],
        *,
        python_version: str,
        variants: tuple[Variant, ...],
        extra_index_urls: list[str],
        find_links: list[str] | None = None,
        offline: bool = False,
    ) -> list[ResolvedPackage]:
        """Resolve requirements to wheels covering every requested variant."""
        ...


class PipWheelResolver:
    """Default backend: stock pip cross-resolution via ``pip install --report``."""

    def __init__(self, python_executable: str | None = None) -> None:
        self._python = python_executable or sys.executable

    def resolve(
        self,
        requirements: list[str],
        *,
        python_version: str,
        variants: tuple[Variant, ...],
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

        for variant in variants:
            report = self._run_report(
                requirements,
                python_version=python_version,
                platform_tag=variant.platform_tag,
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
            raise WheelResolverError(
                f"kivyforge needs pip >= {version_str(MIN_PIP_VERSION)} to resolve "
                f"wheels, but {self._python} has pip {version_str(version)}.\n"
                f"  Upgrade it: {self._python} -m pip install --upgrade pip"
            )

    def _absorb(self, item, merged, seen_filenames) -> None:
        meta = item.get("metadata", {})
        name = meta.get("name")
        version = meta.get("version")
        download = item.get("download_info", {})
        url = download.get("url", "")
        if not url.endswith(".whl"):
            raise WheelResolverError(
                f"{name} {version} resolved to a non-wheel source ({url}); "
                "kivyforge installs only wheels (no on-host compile)."
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
            raise WheelResolverError(
                f"{name} resolved to inconsistent versions across variants: "
                f"{pkg.version!r} and {version!r}. Every variant of a package "
                "must pin the same version."
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
        with tempfile.TemporaryDirectory(prefix="kivy-wheel-lock-") as tmp:
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
                raise WheelResolverError(
                    f"pip could not resolve wheels for {platform_tag!r}.\n"
                    f"  This usually means a dependency has no wheel for that "
                    f"variant upstream.\n"
                    f"  pip said:\n{_indent(proc.stderr or proc.stdout)}"
                )
            try:
                return json.loads(report_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                raise WheelResolverError(f"could not read pip report: {exc}") from exc


def get_wheel_resolver(backend: str = "pip", **kwargs) -> WheelResolver:
    if backend == "pip":
        return PipWheelResolver(**kwargs)
    raise WheelResolverError(f"unknown resolver backend {backend!r} (expected pip)")


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in (text or "").splitlines())
