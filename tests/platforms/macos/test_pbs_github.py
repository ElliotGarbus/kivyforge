"""PBS GitHub metadata resolution: candidate order + SHA-256 precedence."""

from __future__ import annotations

import urllib.error
import urllib.request
from email.message import Message

import pytest

from kivyforge.lock.wheelruntime.pbs_github import (
    GithubPbsMetadataFetcher,
    _is_rate_limited,
    _request_headers,
)
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


def _http_error(url: str, code: int, reason: str) -> urllib.error.HTTPError:
    """An ``HTTPError`` with real headers.

    ``hdrs`` is typed as ``email.message.Message``; a bare ``{}`` works at
    runtime but pyright rejects it, and `pythonPlatform: All` means that
    error shows up for every contributor rather than only on one host.
    """
    return urllib.error.HTTPError(url, code, reason, Message(), None)


class TestAuthentication:
    """GitHub's API budget is 60/hour per IP unauthenticated, 5000 with a token.

    One `fetch()` can spend up to 16 of those, which is how a `lock --check`
    on a *committed* lock managed to fail CI with `HTTP Error 403: rate limit`
    (test-matrix.md §7, 2026-09-22) — two concurrently-triggered workflow runs
    on shared runner egress.
    """

    def test_no_authorization_header_without_a_token(self, monkeypatch):
        for var in ("GH_TOKEN", "GITHUB_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        assert "Authorization" not in _request_headers()

    def test_github_token_is_sent_as_a_bearer_token(self, monkeypatch):
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "ghs_example")
        assert _request_headers()["Authorization"] == "Bearer ghs_example"

    def test_gh_token_wins_over_github_token(self, monkeypatch):
        """Matches the `gh` CLI's own precedence, so a dev box agrees with it."""
        monkeypatch.setenv("GH_TOKEN", "from-gh")
        monkeypatch.setenv("GITHUB_TOKEN", "from-actions")
        assert _request_headers()["Authorization"] == "Bearer from-gh"

    def test_a_blank_token_is_ignored_rather_than_sent(self, monkeypatch):
        """`env: GH_TOKEN: ${{ secrets.MISSING }}` sets it to the empty string.

        Sending `Authorization: Bearer ` would turn a would-be anonymous
        request into a 401, converting a working call into a broken one.
        """
        monkeypatch.setenv("GH_TOKEN", "   ")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert "Authorization" not in _request_headers()

    def test_the_accept_header_is_kept_alongside_the_token(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "t")
        assert _request_headers()["Accept"] == "application/vnd.github+json"


class TestRateLimitHint:
    def test_a_403_earns_the_hint(self):
        err = _http_error("u", 403, "rate limit exceeded")
        assert _is_rate_limited(err)

    def test_a_429_earns_the_hint(self):
        """GitHub returns 429 for secondary rate limits."""
        err = _http_error("u", 429, "too many requests")
        assert _is_rate_limited(err)

    def test_an_ordinary_failure_does_not(self):
        """A 404 or a DNS error must not be explained as a rate limit."""
        assert not _is_rate_limited(_http_error("u", 404, "not found"))
        assert not _is_rate_limited(OSError("name resolution failed"))

    def test_the_hint_reaches_the_raised_error(self, monkeypatch):
        """End to end: a rate-limited fetch says what to do about it."""
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        def _429(req, *a, **kw):
            raise _http_error(req.full_url, 403, "rate limit exceeded")

        monkeypatch.setattr(urllib.request, "urlopen", _429)
        with pytest.raises(RuntimeProviderError) as excinfo:
            GithubPbsMetadataFetcher().fetch("3.13.14", "x86_64-unknown-linux-gnu")
        message = str(excinfo.value)
        assert "rate limit" in message
        assert "GH_TOKEN" in message

    def test_an_unrelated_failure_is_not_given_the_hint(self, monkeypatch):
        def _404(req, *a, **kw):
            raise _http_error(req.full_url, 404, "nope")

        monkeypatch.setattr(urllib.request, "urlopen", _404)
        with pytest.raises(RuntimeProviderError) as excinfo:
            GithubPbsMetadataFetcher().fetch("3.13.14", "x86_64-unknown-linux-gnu")
        assert "GH_TOKEN" not in str(excinfo.value)
