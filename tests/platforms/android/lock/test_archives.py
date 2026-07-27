"""``.aar``/``.jar`` archive resolution to lock pins (android/02, channel 3)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError
from kivyforge.config.model import AndroidArchiveDep
from kivyforge.platforms.android.lock.archives import (
    ArchiveResolverError,
    resolve_android_libs,
)


def _dep(name="Sdk", version="3.1.0", source="vendor/Sdk.aar", kind="aar"):
    return AndroidArchiveDep(name=name, version=version, source=source, kind=kind)


class FakeDownloader:
    def __init__(self, content: bytes = b"fake-archive-bytes"):
        self.content = content
        self.calls: list[tuple[str, Path]] = []

    def fetch_to(self, url, dest):
        self.calls.append((url, dest))
        dest.write_bytes(self.content)


class FailingDownloader:
    def fetch_to(self, url, dest):
        raise DownloadError(f"connection refused for {url}")


class TestLocalVendoredSource:
    def test_hashes_existing_file(self, tmp_path):
        (tmp_path / "vendor").mkdir()
        content = b"aar-bytes"
        (tmp_path / "vendor" / "Sdk.aar").write_bytes(content)
        [lib] = resolve_android_libs((_dep(),), project_root=tmp_path)
        assert lib.path == "vendor/Sdk.aar"
        assert lib.url is None
        assert lib.sha256 == hashlib.sha256(content).hexdigest()

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(ArchiveResolverError, match="does not exist"):
            resolve_android_libs((_dep(),), project_root=tmp_path)


class TestRemoteSource:
    def _remote_dep(self):
        return _dep(source="https://cdn.example/libs/Sdk-3.1.0.aar")

    def test_cache_hit_skips_download(self, tmp_path):
        cache = ArtifactCache(root=tmp_path / "cache")
        data = b"cached-bytes"
        sha = hashlib.sha256(data).hexdigest()
        cache.put_bytes(data, sha, "Sdk-3.1.0.aar")
        downloader = FakeDownloader()

        [lib] = resolve_android_libs(
            (self._remote_dep(),),
            project_root=tmp_path,
            downloader=downloader,
            cache=cache,
        )
        assert lib.sha256 == sha
        assert lib.url == "https://cdn.example/libs/Sdk-3.1.0.aar"
        assert not downloader.calls  # never touched the network

    def test_offline_without_cache_raises(self, tmp_path):
        cache = ArtifactCache(root=tmp_path / "cache")
        with pytest.raises(ArchiveResolverError, match="not in the artifact cache"):
            resolve_android_libs(
                (self._remote_dep(),),
                project_root=tmp_path,
                cache=cache,
                offline=True,
            )

    def test_downloads_and_hashes_on_cache_miss(self, tmp_path):
        cache = ArtifactCache(root=tmp_path / "cache")
        downloader = FakeDownloader(b"downloaded-bytes")

        [lib] = resolve_android_libs(
            (self._remote_dep(),),
            project_root=tmp_path,
            downloader=downloader,
            cache=cache,
        )
        assert lib.sha256 == hashlib.sha256(b"downloaded-bytes").hexdigest()
        assert downloader.calls == [
            ("https://cdn.example/libs/Sdk-3.1.0.aar", downloader.calls[0][1])
        ]

    def test_download_failure_wrapped(self, tmp_path):
        cache = ArtifactCache(root=tmp_path / "cache")
        with pytest.raises(ArchiveResolverError, match="could not fetch"):
            resolve_android_libs(
                (self._remote_dep(),),
                project_root=tmp_path,
                downloader=FailingDownloader(),
                cache=cache,
            )


class TestOrdering:
    def test_sorted_by_name_then_version(self, tmp_path):
        (tmp_path / "vendor").mkdir()
        for name, version in (("Zeta", "1.0"), ("alpha", "2.0"), ("Alpha", "1.0")):
            (tmp_path / "vendor" / f"{name}-{version}.aar").write_bytes(b"x")
        deps = tuple(
            _dep(name=name, version=version, source=f"vendor/{name}-{version}.aar")
            for name, version in (("Zeta", "1.0"), ("alpha", "2.0"), ("Alpha", "1.0"))
        )
        libs = resolve_android_libs(deps, project_root=tmp_path)
        assert [(lib.name, lib.version) for lib in libs] == [
            ("Alpha", "1.0"),
            ("alpha", "2.0"),
            ("Zeta", "1.0"),
        ]
