"""python.org Android runtime metadata resolution (android/02).

Cache-hit paths use a real ``ArtifactCache``; the network paths (release
listing discovery, chunked download with retry) stub ``urllib.request.urlopen``
so no real network access happens and retry backoff sleeps are neutralized.
"""

from __future__ import annotations

import hashlib
import io
import tarfile

import pytest

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.platforms.android.lock import python_meta as pm
from kivyforge.platforms.android.lock.python_meta import (
    PythonAndroidError,
    PythonOrgAndroidProvider,
    read_min_api,
)


def _make_runtime_archive(tmp_path, *, min_api: int | None, name="rt.tar.gz"):
    """A minimal .tar.gz with (or without) ``android-env.sh``."""
    archive = tmp_path / name
    with tarfile.open(archive, "w:gz") as tf:
        if min_api is not None:
            content = f"ANDROID_API_LEVEL:={min_api}\n".encode()
            info = tarfile.TarInfo("python-android/android-env.sh")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        else:
            content = b"nothing relevant here"
            info = tarfile.TarInfo("python-android/README.md")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return archive


def _archive_bytes(*, min_api: int) -> bytes:
    buf = io.BytesIO()
    content = f"ANDROID_API_LEVEL:={min_api}\n".encode()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("python-android/android-env.sh")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, data: bytes):
        self._buf = data

    def read(self, n=None):
        if n is None or n < 0:
            data, self._buf = self._buf, b""
            return data
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestReadMinApi:
    def test_reads_declared_level(self, tmp_path):
        archive = _make_runtime_archive(tmp_path, min_api=26)
        assert read_min_api(archive) == 26

    def test_fallback_when_script_missing(self, tmp_path):
        archive = _make_runtime_archive(tmp_path, min_api=None)
        assert read_min_api(archive) == 24

    def test_fallback_on_corrupt_archive(self, tmp_path):
        archive = tmp_path / "bad.tar.gz"
        archive.write_bytes(b"not a tarball")
        assert read_min_api(archive) == 24

    def test_fallback_on_missing_file(self, tmp_path):
        assert read_min_api(tmp_path / "does-not-exist.tar.gz") == 24


class TestProviderCacheAndOffline:
    def test_unknown_abi_raises(self, tmp_path):
        provider = PythonOrgAndroidProvider(cache=ArtifactCache(root=tmp_path))
        with pytest.raises(PythonAndroidError, match="unknown Android ABI"):
            provider.get("3.14.6", "mips", offline=True)

    def test_offline_cache_hit_uses_fallback_filename(self, tmp_path):
        cache = ArtifactCache(root=tmp_path)
        filename = "python-3.14.6-aarch64-linux-android.tar.gz"
        data = _archive_bytes(min_api=26)
        sha = hashlib.sha256(data).hexdigest()
        cache.put_bytes(data, sha, filename)

        info = PythonOrgAndroidProvider(cache=cache).get(
            "3.14.6", "arm64_v8a", offline=True
        )
        assert info.sha256 == sha
        assert info.min_api == 26
        assert info.url.endswith(filename)
        assert info.abi == "arm64_v8a"

    def test_offline_without_cache_raises(self, tmp_path):
        provider = PythonOrgAndroidProvider(cache=ArtifactCache(root=tmp_path))
        with pytest.raises(PythonAndroidError, match="not in the artifact cache"):
            provider.get("3.14.6", "arm64_v8a", offline=True)


class TestProviderOnline:
    def test_listing_hit_then_downloads(self, tmp_path, monkeypatch):
        html = '<a href="python-3.14.6-aarch64-linux-android.tar.gz">...</a>'
        archive_bytes = _archive_bytes(min_api=26)
        responses = iter([_FakeResponse(html.encode()), _FakeResponse(archive_bytes)])
        monkeypatch.setattr(pm.urllib.request, "urlopen", lambda url: next(responses))

        provider = PythonOrgAndroidProvider(cache=ArtifactCache(root=tmp_path))
        info = provider.get("3.14.6", "arm64_v8a")
        assert info.min_api == 26
        assert info.url.endswith("python-3.14.6-aarch64-linux-android.tar.gz")

    def test_listing_unreachable_falls_back_to_conventional_name(
        self, tmp_path, monkeypatch
    ):
        def boom(url):
            raise OSError("no network")

        monkeypatch.setattr(pm.urllib.request, "urlopen", boom)
        cache = ArtifactCache(root=tmp_path)
        filename = "python-3.14.6-aarch64-linux-android.tar.gz"
        data = _archive_bytes(min_api=24)
        sha = hashlib.sha256(data).hexdigest()
        cache.put_bytes(data, sha, filename)

        # Listing fetch fails (-> {}), falls back to the conventional filename,
        # which is a cache hit — so _download (a second urlopen) is never hit.
        info = PythonOrgAndroidProvider(cache=cache).get("3.14.6", "arm64_v8a")
        assert info.sha256 == sha

    def test_listing_caches_per_version(self, tmp_path, monkeypatch):
        html = '<a href="python-3.14.6-aarch64-linux-android.tar.gz">...</a>'
        calls = {"n": 0}

        def fake_urlopen(url):
            calls["n"] += 1
            return _FakeResponse(html.encode())

        monkeypatch.setattr(pm.urllib.request, "urlopen", fake_urlopen)
        cache = ArtifactCache(root=tmp_path)
        data = _archive_bytes(min_api=24)
        sha = hashlib.sha256(data).hexdigest()
        cache.put_bytes(data, sha, "python-3.14.6-aarch64-linux-android.tar.gz")

        provider = PythonOrgAndroidProvider(cache=cache)
        provider.get("3.14.6", "arm64_v8a")
        provider.get("3.14.6", "arm64_v8a")
        assert calls["n"] == 1  # the listing fetch is memoized per version


class TestDownloadRetry:
    def test_retries_then_succeeds(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pm.time, "sleep", lambda s: None)
        # A non-default value: confirms min_api is genuinely read back from the
        # downloaded archive (via the live file handle) rather than coincidentally
        # matching the _MIN_API_FALLBACK default.
        archive_bytes = _archive_bytes(min_api=27)
        calls = {"n": 0}

        def fake_urlopen(url):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("flaky")
            return _FakeResponse(archive_bytes)

        monkeypatch.setattr(pm.urllib.request, "urlopen", fake_urlopen)
        provider = PythonOrgAndroidProvider(cache=ArtifactCache(root=tmp_path))
        sha, min_api = provider._download(
            "https://example/x.tar.gz", "3.14.6", "arm64_v8a"
        )
        assert min_api == 27
        assert calls["n"] == 3
        assert sha == hashlib.sha256(archive_bytes).hexdigest()

    def test_gives_up_after_all_attempts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pm.time, "sleep", lambda s: None)

        def boom(url):
            raise OSError("still flaky")

        monkeypatch.setattr(pm.urllib.request, "urlopen", boom)
        provider = PythonOrgAndroidProvider(cache=ArtifactCache(root=tmp_path))
        with pytest.raises(PythonAndroidError, match="could not fetch"):
            provider._download("https://example/x.tar.gz", "3.14.6", "arm64_v8a")
