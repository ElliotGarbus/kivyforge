"""Android dependency resolver (android/02 §"Resolution semantics").

Turns ``[project].dependencies`` into fully-pinned per-ABI Android wheels,
**host-independent**: every compiled package is pinned for every ABI in
``[tool.kivy.android].abis``, regardless of the host running ``lock``.

Host-independence covers *marker evaluation*, not just wheel tags. pip's
``--platform``/``--abi`` select acceptable tags but leave ``sys_platform`` and
friends pointing at the machine running pip, which made the same lock succeed
on Linux and fail on Windows. Resolution therefore runs through
``_pip_shim.py``, which retargets ``packaging``'s marker environment at Android
(see ``markers.py``) before handing off to pip.

Mirrors the iOS resolver (same pip ``--report`` backend, same fail-fast
semantics): a package missing any targeted ABI slice is rejected, and a
version skew across ABIs (one ABI's wheel published before another's) is
rejected rather than merged. The wheel-tag API level is a floor — pip's
PEP 738 tag expansion accepts an ``android_21_*`` wheel at ``min_sdk = 24``
(android/01 §find_links), so kivyforge never re-implements that rule.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
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
    unresolved_requirement,
    version_str,
)

from ..streaming import elapsed, run_streaming
from .markers import android_marker_environment

# Run by path, not ``-m``: the shim imports nothing from kivyforge, so it also
# works when resolving with an interpreter that only has pip installed.
_SHIM = Path(_pip_shim.__file__)

# Android wheels: android_<apilevel>_<abi> (PEP 738). pip >= 25.1 understands
# them (including cross-download); enforce the same floor everywhere.
MIN_ANDROID_PIP_VERSION = (25, 1)


class ResolverError(Exception):
    """A resolution failure (missing ABI, no matching wheel, backend error)."""


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


def abi_platform_tag(min_sdk: int, abi: str) -> str:
    """The pip ``--platform`` tag for one targeted ABI (android/06 step 4)."""
    return f"android_{min_sdk}_{abi}"


class Resolver(Protocol):
    def resolve(
        self,
        requirements: list[str],
        *,
        python_version: str,
        min_sdk: int,
        abis: tuple[str, ...],
        extra_index_urls: list[str],
        find_links: list[str] | None = None,
        offline: bool = False,
    ) -> list[ResolvedPackage]:
        """Resolve requirements to per-ABI Android wheels (all ABIs pinned)."""
        ...


class PipResolver:
    """Default backend: stock pip cross-resolution via ``pip install --report``.

    One dry-run report per targeted ABI; results merge into one
    ``ResolvedPackage`` per distribution (pure-Python wheels dedupe by
    filename across ABIs).
    """

    def __init__(
        self,
        python_executable: str | None = None,
        *,
        on_progress: Callable[[str], None] | None = None,
        on_transfer: Callable[[str, int, int, str], None] | None = None,
    ) -> None:
        self._python = python_executable or sys.executable
        self._on_progress = on_progress
        self._on_transfer = on_transfer

    def resolve(
        self,
        requirements: list[str],
        *,
        python_version: str,
        min_sdk: int,
        abis: tuple[str, ...],
        extra_index_urls: list[str],
        find_links: list[str] | None = None,
        offline: bool = False,
    ) -> list[ResolvedPackage]:
        if not requirements:
            return []
        self._require_modern_pip()
        cp_abis = abi_tags(python_version)
        merged: dict[str, ResolvedPackage] = {}
        seen_filenames: dict[str, set[str]] = {}

        for abi in abis:
            # Markers are evaluated for the *target*, per ABI: platform_machine
            # differs between arm64_v8a and x86_64, and packages do gate on it.
            environment = android_marker_environment(
                python_version=python_version, abi=abi
            )
            if self._on_progress is not None:
                self._on_progress(f"[lock] {abi}: resolving wheels")
            report = self._run_report(
                requirements,
                label=abi,
                python_version=python_version,
                platform_tag=abi_platform_tag(min_sdk, abi),
                abis=cp_abis,
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
        floor = max(MIN_PIP_VERSION, MIN_ANDROID_PIP_VERSION)
        if version is not None and version < floor:
            raise ResolverError(
                f"kivyforge needs pip >= {version_str(floor)} to resolve "
                f"Android wheels, but {self._python} has pip "
                f"{version_str(version)}.\n"
                "  pip < 25.1 predates PEP 738 android platform tags, so "
                "compatible wheels (e.g. android_24_*) are reported as missing.\n"
                f"  Upgrade it: {self._python} -m pip install --upgrade pip"
            )

    def _absorb(self, item, merged, seen_filenames, environment) -> None:
        meta = item.get("metadata", {})
        name = meta.get("name")
        version = meta.get("version")
        download = item.get("download_info", {})
        url = download.get("url", "")
        if not url.endswith(".whl"):
            # sdist/vcs/directory are refused (android/02): wheels only — the
            # backend has no on-host cross-compile step.
            raise ResolverError(
                f"{name} {version} resolved to a non-wheel source ({url}); "
                "kivyforge installs only Android wheels (no from-source "
                "pipeline — build an android_* wheel out-of-band, android/03)."
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
            # Each ABI is a separate pip resolution; if upstream published the
            # ABIs at different times they can disagree on version. Merging
            # would produce a lock that installs mismatched binaries per ABI.
            raise ResolverError(
                f"{name} resolved to inconsistent versions across Android ABIs: "
                f"{pkg.version!r} and {version!r}. Re-lock once upstream "
                "publishes the lagging ABI (android/02 fail-fast)."
            )
        if filename not in seen_filenames[key]:
            seen_filenames[key].add(filename)
            pkg.wheels.append(ResolvedWheel(filename=filename, url=url, sha256=sha256))

    def _run_report(
        self,
        requirements: list[str],
        *,
        label: str = "",
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
            # Not "-m pip": the shim retargets marker evaluation at the Android
            # environment first, then runs pip unchanged (see _pip_shim.py).
            cmd = [
                self._python,
                str(_SHIM),
                "install",
                "--no-input",
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
                # Machine-readable byte counts even when not on a terminal,
                # which is the only way to show download progress (#84).
                "--progress-bar",
                "raw",
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
            progress = _PipProgress(
                label or platform_tag, self._on_progress, self._on_transfer
            )
            returncode, transcript = run_streaming(
                cmd,
                env=env,
                on_segment=progress,
                on_quiet=progress.quiet if self._on_progress else None,
            )
            if returncode != 0:
                output = _without_progress(transcript)
                culprit = unresolved_requirement(output)
                what = (
                    f"no {platform_tag} wheel for {culprit!r}"
                    if culprit
                    else "a dependency has no android_* wheel for that ABI"
                )
                hints = []
                if not any("kivy-mobile-wheels" in u for u in extra_index_urls):
                    hints.append(
                        "  - If it is kivy or pyjnius, add the first-party mobile "
                        "wheel index under [tool.kivy.android]:\n"
                        "      extra_index_urls = "
                        '["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]'
                    )
                hints.append(
                    "  - Any other package needs an Android build: a wheel in a "
                    "directory listed in find_links (android/03), or drop the "
                    "dependency."
                )
                raise ResolverError(
                    f"pip could not resolve the Android ABI {platform_tag!r}: "
                    f"{what}.\n" + "\n".join(hints) + "\n"
                    f"  pip said:\n{_indent(output)}"
                )
            try:
                # pip writes the report as UTF-8; never trust the locale codec
                # (cp1252 on Windows chokes on non-ASCII package metadata).
                return json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ResolverError(f"could not read pip report: {exc}") from exc


_DOWNLOADING = re.compile(r"^\s*Downloading (\S+)(?: \(([^)]+)\))?")
_PROGRESS = re.compile(r"^Progress (\d+) of (\d+)$")


class _PipProgress:
    """Turn ``pip --progress-bar raw`` output into transfer events."""

    def __init__(
        self,
        label: str,
        on_progress: Callable[[str], None] | None,
        on_transfer: Callable[[str, int, int, str], None] | None,
    ) -> None:
        self._label = label
        self._on_progress = on_progress
        self._on_transfer = on_transfer
        self._current = ""

    def __call__(self, segment: str) -> bool:
        line = segment.strip()
        downloading = _DOWNLOADING.match(line)
        if downloading:
            self._current = f"[lock] {self._label}: {_short_name(downloading.group(1))}"
            return False
        progress = _PROGRESS.match(line)
        if progress and self._current and self._on_transfer is not None:
            done, total = int(progress.group(1)), int(progress.group(2))
            self._on_transfer(self._current, done, total, "bytes")
            return True
        return False

    def quiet(self, seconds: float) -> None:
        if self._on_progress is not None:
            self._on_progress(
                f"[lock] {self._label}: still resolving ({elapsed(seconds)})"
            )


def _short_name(url: str) -> str:
    """``.../Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl`` -> ``Kivy-2.3.1``.

    The ABI is already in the label, and the full filename does not fit beside
    a bar in a narrow terminal.
    """
    filename = url.rsplit("/", 1)[-1]
    if filename.endswith(".whl"):
        return "-".join(filename.split("-")[:2])
    return filename


def _without_progress(transcript: str) -> str:
    """pip's output for an error message, minus the raw byte-count lines."""
    return "\n".join(
        line for line in transcript.splitlines() if not _PROGRESS.match(line.strip())
    )


def get_resolver(backend: str = "pip", **kwargs) -> Resolver:
    if backend == "pip":
        return PipResolver(**kwargs)
    raise ResolverError(f"unknown resolver backend {backend!r} (expected pip)")


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in (text or "").splitlines())
