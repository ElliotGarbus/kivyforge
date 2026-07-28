"""python.org iOS xcframework URL resolution (pre-releases vs finals)."""

from __future__ import annotations

import hashlib
import io
import plistlib
import tarfile
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.platforms.ios.lock import python_meta as pm
from kivyforge.platforms.ios.lock.python_meta import (
    PythonOrgProvider,
    PythonXcframeworkError,
    archive_filename,
    python_org_ios_url,
    read_ios_floor,
)


def test_prerelease_url_under_base_release_dir():
    assert (
        python_org_ios_url("3.15.0b4")
        == "https://www.python.org/ftp/python/3.15.0/python-3.15.0b4-iOS-XCframework.tar.gz"
    )


def test_final_release_url():
    assert (
        python_org_ios_url("3.15.0")
        == "https://www.python.org/ftp/python/3.15.0/python-3.15.0-iOS-XCframework.tar.gz"
    )


def test_lock_hashes_python_xcframework_from_artifact_cache(tmp_path):
    import hashlib

    version = "3.15.0b4"
    filename = archive_filename(version)
    data = b"fake-xcframework-archive"
    sha = hashlib.sha256(data).hexdigest()
    cache = ArtifactCache(root=tmp_path)
    cache.put_bytes(data, sha, filename)

    info = PythonOrgProvider(cache=cache).get(version)

    assert info.sha256 == sha
    assert info.url == python_org_ios_url(version)
    # Fake bytes are not a valid tarball — floor falls back to the safe default.
    assert info.ios_floor == "13.0"


def test_lock_offline_requires_cached_python_xcframework(tmp_path):
    cache = ArtifactCache(root=tmp_path)
    provider = PythonOrgProvider(cache=cache)

    try:
        provider.get("3.15.0b4", offline=True)
    except PythonXcframeworkError as exc:
        assert "not in the artifact cache" in str(exc)
    else:
        raise AssertionError("expected PythonXcframeworkError")


def _make_xcframework_archive(tmp_path, *, min_os: str) -> Path:
    """Build a minimal .tar.gz containing Python.xcframework/Info.plist."""
    plist_data = plistlib.dumps(
        {
            "AvailableLibraries": [
                {
                    "LibraryIdentifier": "ios-arm64",
                    "MinimumOSVersion": min_os,
                },
                {
                    "LibraryIdentifier": "ios-arm64-simulator",
                    "MinimumOSVersion": min_os,
                },
            ]
        }
    )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("Python.xcframework/Info.plist")
        info.size = len(plist_data)
        tf.addfile(info, io.BytesIO(plist_data))
    archive = tmp_path / "python-3.15.0-iOS-XCframework.tar.gz"
    archive.write_bytes(buf.getvalue())
    return archive


def test_read_ios_floor_from_xcframework_plist(tmp_path):
    archive = _make_xcframework_archive(tmp_path, min_os="14.0")
    assert read_ios_floor(archive) == "14.0"


def test_read_ios_floor_fallback_on_invalid_archive(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    archive.write_bytes(b"not a tarball")
    assert read_ios_floor(archive) == "13.0"


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


def _xcframework_bytes(*, min_os: str) -> bytes:
    plist_data = plistlib.dumps(
        {
            "AvailableLibraries": [
                {"LibraryIdentifier": "ios-arm64", "MinimumOSVersion": min_os},
            ]
        }
    )
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("Python.xcframework/Info.plist")
        info.size = len(plist_data)
        tf.addfile(info, io.BytesIO(plist_data))
    return buf.getvalue()


class TestDownload:
    """``_download`` reads the floor from its own live temp-file handle rather
    than reopening it by path — reopening a still-open ``NamedTemporaryFile``
    by name is a documented POSIX-only guarantee (silently fails on Windows)."""

    def test_downloads_and_reads_floor(self, tmp_path, monkeypatch):
        archive_bytes = _xcframework_bytes(min_os="16.0")
        monkeypatch.setattr(
            pm.urllib.request, "urlopen", lambda url: _FakeResponse(archive_bytes)
        )
        provider = PythonOrgProvider(cache=ArtifactCache(root=tmp_path))
        sha, floor = provider._download("https://example/x.tar.gz", "3.15.0")
        assert floor == "16.0"
        assert sha == hashlib.sha256(archive_bytes).hexdigest()

    def test_retries_then_succeeds(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pm.time, "sleep", lambda s: None)
        archive_bytes = _xcframework_bytes(min_os="15.0")
        calls = {"n": 0}

        def fake_urlopen(url):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError("flaky")
            return _FakeResponse(archive_bytes)

        monkeypatch.setattr(pm.urllib.request, "urlopen", fake_urlopen)
        provider = PythonOrgProvider(cache=ArtifactCache(root=tmp_path))
        sha, floor = provider._download("https://example/x.tar.gz", "3.15.0")
        assert floor == "15.0"
        assert calls["n"] == 3

    def test_gives_up_after_all_attempts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pm.time, "sleep", lambda s: None)

        def boom(url):
            raise OSError("still flaky")

        monkeypatch.setattr(pm.urllib.request, "urlopen", boom)
        provider = PythonOrgProvider(cache=ArtifactCache(root=tmp_path))
        try:
            provider._download("https://example/x.tar.gz", "3.15.0")
        except PythonXcframeworkError as exc:
            assert "could not fetch" in str(exc)
        else:
            raise AssertionError("expected PythonXcframeworkError")
