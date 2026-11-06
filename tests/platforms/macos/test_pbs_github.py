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

    def __init__(
        self, latest, pages=None, texts=None, on_progress=None, tags=(), sums=None
    ):
        super().__init__(on_progress=on_progress)
        self._latest = latest
        self._pages = pages or []
        self._texts = texts or {}
        # No tags by default: these tests exercise the release-page search.
        self._tags = list(tags)
        self._sums = sums or {}
        self.sums_read: list[str] = []

    def _release_tags(self):
        return sorted(self._tags, reverse=True)

    def _release_sums(self, tag):
        self.sums_read.append(tag)
        return self._sums.get(tag)

    def _get_json(self, url):
        if url == self._latest_url:
            return self._latest
        # paged url; return the next page or [] when exhausted
        return self._pages.pop(0) if self._pages else []

    def _get_text(self, url):
        return self._texts[url]


def _tags(n):
    """``n`` date tags, newest first, a day apart."""
    return [f"202608{d:02d}" for d in range(28, 28 - n, -1)]


class TestChecksumLookup:
    """The fast path: release tags + each release's SHA256SUMS (2026-10-20)."""

    def _sums(self, tag, version="3.14.5"):
        return (
            f"{'a' * 64}  cpython-{version}+{tag}-x86_64-unknown-linux-gnu-install_only.tar.gz\n"
            f"{'b' * 64}  cpython-{version}+{tag}-aarch64-apple-darwin-install_only.tar.gz\n"
        )

    def test_the_newest_release_listing_the_build_wins(self):
        tags = _tags(12)
        sums = {tags[10]: self._sums(tags[10]), tags[11]: self._sums(tags[11])}
        fetcher = _Fetcher({"assets": []}, tags=tags, sums=sums)
        asset = fetcher.fetch("3.14.5", "aarch64-apple-darwin")
        assert asset.sha256 == "b" * 64
        assert asset.url == (
            "https://github.com/astral-sh/python-build-standalone/releases/download/"
            f"{tags[10]}/cpython-3.14.5%2B{tags[10]}-aarch64-apple-darwin-install_only.tar.gz"
        )

    def test_reads_in_batches_and_stops_at_the_hit(self):
        tags = _tags(20)
        lines: list[str] = []
        fetcher = _Fetcher(
            {"assets": []},
            tags=tags,
            sums={tags[9]: self._sums(tags[9])},
            on_progress=lines.append,
        )
        fetcher.fetch("3.14.5", "aarch64-apple-darwin")
        assert sorted(fetcher.sums_read, reverse=True) == tags[:16]  # two batches
        assert lines == ["[lock] CPython 3.14.5: checking releases 9-16"]

    def test_a_release_without_sums_is_skipped(self):
        tags = _tags(3)
        fetcher = _Fetcher(
            {"assets": []}, tags=tags, sums={tags[2]: self._sums(tags[2])}
        )
        assert tags[2] in fetcher.fetch("3.14.5", "aarch64-apple-darwin").url

    def test_another_version_is_not_matched(self):
        tags = _tags(2)
        sums = {t: self._sums(t, version="3.14.50") for t in tags}
        latest = {"assets": [_asset(_NAME, digest="sha256:" + "c" * 64)]}
        asset = _Fetcher(latest, tags=tags, sums=sums).fetch(
            "3.14.5", "aarch64-apple-darwin"
        )
        assert asset.sha256 == "c" * 64  # from the release-page search

    def test_no_hit_falls_back_to_the_release_pages(self):
        tags = _tags(2)
        latest = {"assets": [_asset(_NAME, digest="sha256:" + "d" * 64)]}
        asset = _Fetcher(latest, tags=tags).fetch("3.14.5", "aarch64-apple-darwin")
        assert asset.sha256 == "d" * 64

    def test_tags_that_cannot_be_listed_fall_back(self, monkeypatch):
        from kivyforge.lock.wheelruntime import pbs_github

        def failing_json(self, url):
            if "/tags" in url:
                raise RuntimeProviderError("tags unavailable")
            return {"assets": [_asset(_NAME, digest="sha256:" + "e" * 64)]}

        monkeypatch.setattr(
            pbs_github.GithubPbsMetadataFetcher, "_get_json", failing_json
        )
        fetcher = pbs_github.GithubPbsMetadataFetcher()
        assert fetcher._release_tags() == []
        assert fetcher.fetch("3.14.5", "aarch64-apple-darwin").sha256 == "e" * 64


class TestDownloadRequests:
    def test_a_release_file_is_fetched_without_the_api_token(self, monkeypatch):
        """Release downloads redirect to GitHub's file CDN; the token stays home."""
        monkeypatch.setenv("GH_TOKEN", "secret-token")
        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"sums\n"

        def urlopen(req):
            seen.update({k.lower(): v for k, v in req.header_items()})
            return Response()

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        text = GithubPbsMetadataFetcher()._release_sums("20261020")
        assert text == "sums\n"
        assert "authorization" not in seen
        assert seen["user-agent"]


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

    def test_each_older_page_is_announced(self):
        """A page is slow (10 s or more), so each one says so (#88)."""
        latest = {"assets": [_asset("cpython-3.13.0+x-other-install_only.tar.gz")]}
        page1 = [{"assets": []}]
        page2 = [{"assets": [_asset(_NAME, digest="sha256:" + "d" * 64)]}]
        lines: list[str] = []
        _Fetcher(latest, pages=[page1, page2], on_progress=lines.append).fetch(
            "3.14.5", "aarch64-apple-darwin"
        )
        assert lines == [
            "[lock] CPython 3.14.5: checking older releases (page 1)",
            "[lock] CPython 3.14.5: checking older releases (page 2)",
        ]

    def test_a_build_in_the_newest_release_needs_no_lines(self):
        latest = {"assets": [_asset(_NAME, digest="sha256:" + "a" * 64)]}
        lines: list[str] = []
        _Fetcher(latest, on_progress=lines.append).fetch(
            "3.14.5", "aarch64-apple-darwin"
        )
        assert lines == []

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


class TestFindCommonInstallOnly:
    """The lock's host-CPython lookup: one version for every triple, the
    stripped variant where published, one pass over the releases."""

    MAC, LINUX, WIN = (
        "aarch64-apple-darwin",
        "x86_64-unknown-linux-gnu",
        "x86_64-pc-windows-msvc",
    )

    class _Sums(GithubPbsMetadataFetcher):
        def __init__(self, sums, *, tags_error=None):
            super().__init__()
            self._sums = sums
            self._tags_error = tags_error
            self.sums_read: list[str] = []

        def _list_release_tags(self):
            if self._tags_error is not None:
                raise self._tags_error
            return sorted(self._sums, reverse=True)

        def _release_sums(self, tag):
            self.sums_read.append(tag)
            return self._sums.get(tag)

    @staticmethod
    def _line(tag, version, triple, variant="install_only_stripped"):
        return (
            f"{version[-1] * 64}  cpython-{version}+{tag}-{triple}-{variant}.tar.gz\n"
        )

    def _fetcher(self, releases, **kw):
        sums = {
            tag: "".join(self._line(tag, v, t, *extra) for v, t, *extra in rows)
            for tag, rows in releases.items()
        }
        return self._Sums(sums, **kw)

    def test_the_shipped_version_for_every_triple(self):
        f = self._fetcher(
            {
                "20261101": [
                    ("3.15.2", self.MAC),
                    ("3.15.2", self.LINUX),
                    ("3.15.2", self.WIN),
                ]
            }
        )
        version, builds = f.find_common_install_only(
            "3.15", (self.MAC, self.LINUX, self.WIN), prefer="3.15.2"
        )
        assert version == "3.15.2"
        assert set(builds) == {self.MAC, self.LINUX, self.WIN}
        assert builds[self.MAC][1].url.endswith(
            "/20261101/cpython-3.15.2%2B20261101-aarch64-apple-darwin-install_only_stripped.tar.gz"
        )

    def test_otherwise_the_newest_version_they_all_have(self):
        """3.15.3 for macOS alone doesn't count: one version for every host."""
        f = self._fetcher(
            {
                "20261201": [("3.15.3", self.MAC)],
                "20261101": [("3.15.2", self.MAC), ("3.15.2", self.LINUX)],
            }
        )
        version, builds = f.find_common_install_only(
            "3.15", (self.MAC, self.LINUX), prefer="3.15.9"
        )
        assert version == "3.15.2"
        assert set(builds) == {self.MAC, self.LINUX}

    def _history(self, micros, triples):
        """One release per entry of *micros*, newest first, each carrying that
        patch for every one of *triples*."""
        return {
            f"2026{len(micros) - i:04d}": [(f"3.14.{m}", t) for t in triples]
            for i, m in enumerate(micros)
        }

    def test_the_shipped_version_further_back_than_one_batch(self):
        """PBS as of 2026-11-06: 3.14.6 is the 15th release down, two batches
        in. The scan once stopped after the first batch and pinned 3.14.10."""
        micros = [10, 9, 8, 8, 8, 8, 8, 7, 7, 7, 7, 7, 7, 7, 6, 6, 6, 6, 6, 5]
        f = self._fetcher(self._history(micros, (self.MAC, self.LINUX, self.WIN)))
        version, builds = f.find_common_install_only(
            "3.14", (self.MAC, self.LINUX, self.WIN), prefer="3.14.6"
        )
        assert version == "3.14.6"
        assert set(builds) == {self.MAC, self.LINUX, self.WIN}
        assert len(f.sums_read) == 16

    def test_a_host_without_a_build_still_ends_the_scan(self):
        """Windows never built the minor: give up on it one batch after the
        first match, but still find the shipped patch for the others."""
        micros = [10, 9, 8, 8, 8, 8, 8, 7, 7, 7, 7, 7, 7, 7, 6, 6, 6, 6, 6, 5] * 3
        f = self._fetcher(self._history(micros, (self.MAC, self.LINUX)))
        version, builds = f.find_common_install_only(
            "3.14", (self.MAC, self.LINUX, self.WIN), prefer="3.14.6"
        )
        assert version == "3.14.6"
        assert set(builds) == {self.MAC, self.LINUX}
        assert len(f.sums_read) == 16

    def test_without_a_preference_one_batch_is_enough(self):
        micros = [10, 9, 8, 8, 8, 8, 8, 7, 7, 7, 7, 7, 7, 7, 6, 6]
        f = self._fetcher(self._history(micros, (self.MAC, self.WIN)))
        version, _builds = f.find_common_install_only(
            "3.14", (self.MAC, self.LINUX, self.WIN)
        )
        assert version == "3.14.10"
        assert len(f.sums_read) == 8

    def test_stripped_wins_over_full_in_one_release(self):
        f = self._fetcher(
            {
                "20261101": [
                    ("3.15.2", self.LINUX, "install_only"),
                    ("3.15.2", self.LINUX, "install_only_stripped"),
                ]
            }
        )
        _version, builds = f.find_common_install_only("3.15", (self.LINUX,))
        assert builds[self.LINUX][0] == "install_only_stripped"

    def test_full_where_stripped_isnt_published(self):
        f = self._fetcher({"20261101": [("3.15.2", self.WIN, "install_only")]})
        _version, builds = f.find_common_install_only("3.15", (self.WIN,))
        assert builds[self.WIN][0] == "install_only"

    def test_a_triple_with_no_build_is_left_out(self):
        f = self._fetcher({"20261101": [("3.15.2", self.MAC)]})
        version, builds = f.find_common_install_only(
            "3.15", (self.MAC, self.WIN), prefer="3.15.2"
        )
        assert version == "3.15.2"
        assert set(builds) == {self.MAC}

    def test_no_build_of_the_minor_at_all(self):
        f = self._fetcher({"20261101": [("3.14.7", self.MAC)]})
        assert f.find_common_install_only("3.15", (self.MAC,)) == (None, {})

    def test_pre_releases_never_match(self):
        sums = {
            "20261001": f"{'a' * 64}  cpython-3.16.0rc1+20261001-{self.MAC}-install_only_stripped.tar.gz\n"
        }
        assert self._Sums(sums).find_common_install_only("3.16", (self.MAC,)) == (
            None,
            {},
        )

    def test_a_listing_failure_raises(self):
        f = self._fetcher({}, tags_error=RuntimeProviderError("rate limit"))
        with pytest.raises(RuntimeProviderError, match="rate limit"):
            f.find_common_install_only("3.15", (self.MAC,))
