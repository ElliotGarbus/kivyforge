"""Resolve python.org Android runtime metadata for the lock (android/02).

``kivyforge lock`` pins, per targeted ABI, the Android embeddable package's
URL + SHA-256 and its minimum-API floor into ``[[tool.kivyforge.python_android]]``.
Modeled on the iOS ``PythonOrgProvider`` — same cache/offline/retry posture —
but per-ABI (the runtime ships one artifact per ABI, not a fat xcframework).

Artifact naming is **discovered from the release's file listing**, not
hardcoded: the observed 3.14.6 names are
``python-3.14.6-{aarch64,x86_64}-linux-android.tar.gz`` (see
docs/design/dev/android-loadmodel-findings.md §runtime-package facts, which
corrected the illustrative URL in android/02). The known pattern serves as a
fallback when the listing is unreachable but the artifact itself is.

The min-API floor is read from ``android-env.sh`` inside the tarball
(``ANDROID_API_LEVEL:=24``) — the same source python.org's own testbed Gradle
project reads it from, so there is no per-version table to maintain.
"""

from __future__ import annotations

import hashlib
import re
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.verify import sha256_file

RELEASE_LISTING_URL = "https://www.python.org/ftp/python/{version}/"

# ABI (wheel-tag spelling) -> the arch component in python.org's filenames.
ABI_TO_PYTHON_ORG_ARCH = {"arm64_v8a": "aarch64", "x86_64": "x86_64"}

_FALLBACK_NAME = "python-{version}-{arch}-linux-android.tar.gz"
_ANDROID_TARBALL_RE = re.compile(
    r'href="(python-(?P<version>[^"]+?)-(?P<arch>aarch64|x86_64)'
    r'-linux-android\.tar\.gz)"'
)
_API_LEVEL_RE = re.compile(r"ANDROID_API_LEVEL:?=\s*(\d+)")

_DOWNLOAD_ATTEMPTS = 4
_RETRY_BACKOFF_SEC = (1.0, 2.0, 4.0)
# Returned when android-env.sh is absent or unparseable; matches the runtime's
# documented floor (android/01 min_sdk).
_MIN_API_FALLBACK = 24


class PythonAndroidError(Exception):
    pass


@dataclass(frozen=True)
class PythonAndroidInfo:
    """One per-ABI runtime pin for ``[[tool.kivyforge.python_android]]``."""

    version: str
    abi: str
    url: str
    sha256: str
    min_api: int


class PythonAndroidProvider(Protocol):
    def get(
        self, version: str, abi: str, *, offline: bool = False
    ) -> PythonAndroidInfo: ...


def read_min_api(archive_path: str | Path) -> int:
    """Read ``ANDROID_API_LEVEL`` from ``android-env.sh`` inside the tarball."""
    try:
        with open(archive_path, "rb") as f:
            return _read_min_api_from_fileobj(f)
    except OSError:
        return _MIN_API_FALLBACK


def _read_min_api_from_fileobj(fileobj) -> int:
    """Same as :func:`read_min_api`, but reads an already-open, seekable file.

    ``_download`` reads it via its own live ``NamedTemporaryFile`` handle
    rather than reopening the path — reopening a still-open ``NamedTemporaryFile``
    by name is a documented POSIX-only guarantee (it silently fails on Windows).
    """
    try:
        with tarfile.open(fileobj=fileobj, mode="r:gz") as tf:
            for member in tf.getmembers():
                if not member.name.endswith("android-env.sh"):
                    continue
                f = tf.extractfile(member)
                if f is None:
                    continue
                match = _API_LEVEL_RE.search(f.read().decode("utf-8", "replace"))
                if match:
                    return int(match.group(1))
    except Exception:  # noqa: BLE001 — malformed archive, test fixture, etc.
        pass
    return _MIN_API_FALLBACK


class PythonOrgAndroidProvider:
    """Default provider: discover the artifact from the release file listing."""

    def __init__(self, *, cache: ArtifactCache | None = None) -> None:
        self._cache = cache or ArtifactCache()
        # version -> {arch -> filename}, from one listing fetch per version.
        self._listing: dict[str, dict[str, str]] = {}

    def get(
        self, version: str, abi: str, *, offline: bool = False
    ) -> PythonAndroidInfo:
        arch = ABI_TO_PYTHON_ORG_ARCH.get(abi)
        if arch is None:
            raise PythonAndroidError(
                f"unknown Android ABI {abi!r}; expected one of "
                f"{sorted(ABI_TO_PYTHON_ORG_ARCH)}"
            )
        filename = self._filename(version, arch, offline=offline)
        url = RELEASE_LISTING_URL.format(version=version) + filename

        cached = self._cache.find_by_filename(filename)
        if cached is not None:
            return PythonAndroidInfo(
                version=version,
                abi=abi,
                url=url,
                sha256=sha256_file(cached),
                min_api=read_min_api(cached),
            )
        if offline:
            raise PythonAndroidError(
                f"python.org Android runtime {version} ({abi}) is not in the "
                f"artifact cache ({filename}).\n"
                f"  Run `kivyforge lock` online once, then retry with --offline."
            )
        sha256, min_api = self._download(url, version, abi)
        return PythonAndroidInfo(
            version=version, abi=abi, url=url, sha256=sha256, min_api=min_api
        )

    # ----------------------------------------------------------------- #
    def _filename(self, version: str, arch: str, *, offline: bool) -> str:
        fallback = _FALLBACK_NAME.format(version=version, arch=arch)
        if offline:
            return fallback
        listing = self._listing.get(version)
        if listing is None:
            listing = self._fetch_listing(version)
            self._listing[version] = listing
        return listing.get(arch, fallback)

    def _fetch_listing(self, version: str) -> dict[str, str]:
        url = RELEASE_LISTING_URL.format(version=version)
        try:
            with urllib.request.urlopen(url) as resp:  # noqa: S310
                html = resp.read().decode("utf-8", "replace")
        except OSError:
            # The artifact fetch itself will surface a clear error if the
            # fallback name is also wrong.
            return {}
        found: dict[str, str] = {}
        for match in _ANDROID_TARBALL_RE.finditer(html):
            found[match.group("arch")] = match.group(1)
        return found

    def _download(self, url: str, version: str, abi: str) -> tuple[str, int]:
        last_exc: OSError | None = None
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            try:
                digest = hashlib.sha256()
                with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
                    with urllib.request.urlopen(url) as resp:  # noqa: S310
                        for chunk in iter(lambda: resp.read(1 << 20), b""):
                            digest.update(chunk)
                            tmp.write(chunk)
                    tmp.flush()
                    tmp.seek(0)
                    min_api = _read_min_api_from_fileobj(tmp)
                return digest.hexdigest(), min_api
            except OSError as exc:
                last_exc = exc
                if attempt < _DOWNLOAD_ATTEMPTS - 1:
                    time.sleep(
                        _RETRY_BACKOFF_SEC[min(attempt, len(_RETRY_BACKOFF_SEC) - 1)]
                    )
        assert last_exc is not None
        raise PythonAndroidError(
            f"could not fetch the python.org Android runtime {version} ({abi}) "
            f"from {url}: {last_exc}\n"
            f"  Check the version exists at python.org/downloads/android/ and "
            f"that you are online. Transient errors are retried "
            f"{_DOWNLOAD_ATTEMPTS} times."
        ) from last_exc
