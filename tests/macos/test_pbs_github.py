"""PBS GitHub metadata resolution: candidate order + SHA-256 precedence."""

from __future__ import annotations

import pytest

from kivyforge.lock.wheelruntime.pbs_github import GithubPbsMetadataFetcher
from kivyforge.lock.wheelruntime.runtime import RuntimeProviderError

_NAME = "cpython-3.14.5+20260602-aarch64-apple-darwin-install_only.tar.gz"


def _asset(name, *, digest=None):
    a = {"name": name, "browser_download_url": f"https://dl/{name}"}
    if digest is not None:
        a["digest"] = digest
    return a


class _Fetcher(GithubPbsMetadataFetcher):
    """Stubs the HTTP layer with in-memory releases + text bodies."""

    def __init__(self, latest, pages=None, texts=None):
        super().__init__()
        self._latest = latest
        self._pages = pages or []
        self._texts = texts or {}

    def _get_json(self, url):
        if url == self._latest_url:
            return self._latest
        # paged url; return the next page or [] when exhausted
        return self._pages.pop(0) if self._pages else []

    def _get_text(self, url):
        return self._texts[url]


class TestFetch:
    def test_uses_asset_digest(self):
        latest = {"assets": [_asset(_NAME, digest="sha256:" + "a" * 64)]}
        asset = _Fetcher(latest).fetch("3.14.5", "aarch64-apple-darwin")
        assert asset.sha256 == "a" * 64
        assert asset.url == f"https://dl/{_NAME}"

    def test_falls_back_to_companion_sha(self):
        companion = f"{_NAME}.sha256"
        latest = {"assets": [_asset(_NAME), _asset(companion)]}
        texts = {f"https://dl/{companion}": "b" * 64 + f"  {_NAME}\n"}
        asset = _Fetcher(latest, texts=texts).fetch("3.14.5", "aarch64-apple-darwin")
        assert asset.sha256 == "b" * 64

    def test_falls_back_to_manifest(self):
        latest = {"assets": [_asset(_NAME), _asset("SHA256SUMS")]}
        texts = {
            "https://dl/SHA256SUMS": f"deadbeef  other.tar.gz\n{'c' * 64}  {_NAME}\n"
        }
        asset = _Fetcher(latest, texts=texts).fetch("3.14.5", "aarch64-apple-darwin")
        assert asset.sha256 == "c" * 64

    def test_no_sha_source_errors(self):
        latest = {"assets": [_asset(_NAME)]}
        with pytest.raises(RuntimeProviderError, match="no SHA-256"):
            _Fetcher(latest).fetch("3.14.5", "aarch64-apple-darwin")

    def test_searches_pages_when_not_in_latest(self):
        latest = {"assets": [_asset("cpython-3.13.0+x-other-install_only.tar.gz")]}
        page1 = [{"assets": [_asset(_NAME, digest="sha256:" + "d" * 64)]}]
        asset = _Fetcher(latest, pages=[page1]).fetch("3.14.5", "aarch64-apple-darwin")
        assert asset.sha256 == "d" * 64

    def test_not_found_anywhere_errors(self):
        latest = {"assets": []}
        with pytest.raises(RuntimeProviderError, match="no python-build-standalone"):
            _Fetcher(latest, pages=[]).fetch("3.14.5", "aarch64-apple-darwin")

    def test_offline_errors(self):
        with pytest.raises(RuntimeProviderError, match="offline"):
            _Fetcher({"assets": []}).fetch(
                "3.14.5", "aarch64-apple-darwin", offline=True
            )
