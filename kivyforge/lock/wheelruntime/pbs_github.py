"""GitHub-backed python-build-standalone (PBS) release metadata lookup.

PBS publishes builds as GitHub release assets on
``astral-sh/python-build-standalone``. Each release is tagged by date and ships,
per platform, an ``install_only`` archive plus a release-wide ``SHA256SUMS``. This
fetcher finds the newest release providing the requested version + target triple
and returns its download URL + pinned SHA-256: from the release tags and each
release's ``SHA256SUMS`` first, then, as a fallback, from the full release
records the releases API pages through. It is triple-agnostic, so macOS
and (later) Linux share it unchanged.

This is the only networked part of the runtime provider; it is exercised against
the live API at the phase stop rather than in hermetic unit tests (which inject a
fake ``MetadataFetcher``).
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ...net import USER_AGENT
from .runtime import ReleaseAsset, RuntimeProviderError

_API = "https://api.github.com/repos/astral-sh/python-build-standalone"
# Each PBS release bundles *every* supported version × platform (hundreds of
# assets), so listing many full release objects at once makes the API 504. The
# newest release already contains every actively-supported CPython, so we check
# `releases/latest` first and only fall back to small paged scans for an older
# pin. Keep the page size small for the same 504-avoidance reason.
_LATEST_URL = f"{_API}/releases/latest"
_RELEASES_URL = f"{_API}/releases?per_page={{per_page}}&page={{page}}"
_PAGE_SIZE = 10
_MAX_PAGES = 15

# The fast path. Every PBS release is tagged by date (YYYYMMDD) and ships a
# small SHA256SUMS listing each archive and its hash, so a build is found by
# listing tags (one API call, ~50 KB) and reading SHA256SUMS newest first
# (~130 KB each, not the API, so no rate limit). Measured on Windows for
# CPython 3.13.14, twelve releases back, 2026-10-20: 6.5 s one at a time, where
# the release pages (~15 MB each) took 10 to 30 s. Read in batches in parallel.
_TAGS_URL = f"{_API}/tags?per_page=100&page={{page}}"
_TAG_PAGES = 2
_DOWNLOAD = "https://github.com/astral-sh/python-build-standalone/releases/download"
_SUMS_BATCH = 8
_DATE_TAG = re.compile(r"^\d{8}$")


# GitHub's API allows 60 requests/hour per IP unauthenticated and 5000/hour
# with a token. One `fetch()` can spend up to _MAX_PAGES + 1 of those, so an
# unauthenticated CI runner on a shared egress IP exhausts the budget quickly
# — which is exactly how it failed: `lock --check` on a committed lock, in two
# concurrently-triggered workflow runs, returning `HTTP Error 403: rate limit`
# (test-matrix.md §7, 2026-09-22).
#
# Every CI provider already exposes a token, and GitHub Actions injects
# GITHUB_TOKEN for free, so honoring it costs the caller nothing and removes
# the ceiling. Read from the environment rather than taking a parameter: this
# fetcher is constructed deep inside the lock pipeline, and threading a
# credential through that call chain to reach one header would be a worse
# trade than reading the variable the surrounding tool already set.
#
# GH_TOKEN first, matching the `gh` CLI's own precedence, so a developer who
# has set it for `gh` gets the higher limit locally too.
_TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN")

_RATE_LIMIT_HINT = (
    "\n  GitHub rate-limits unauthenticated API calls to 60/hour per IP. "
    "Set GH_TOKEN or GITHUB_TOKEN to raise it to 5000/hour — in GitHub "
    "Actions, `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` needs no "
    "extra setup."
)


def _github_token() -> str:
    for var in _TOKEN_VARS:
        token = os.environ.get(var, "").strip()
        if token:
            return token
    return ""


def _request_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    token = _github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_rate_limited(exc: BaseException) -> bool:
    """Whether *exc* is GitHub's rate-limit rejection, so the hint is earned.

    403 is the status GitHub uses for an exhausted rate limit; it also uses it
    for genuine authorization failures, which is why the hint is phrased as a
    possibility to check rather than as the diagnosis. 429 is included because
    GitHub has begun returning it for secondary limits.
    """
    status = getattr(exc, "code", None)
    return status in (403, 429)


class GithubPbsMetadataFetcher:
    """Resolve a PBS asset by querying the GitHub releases API."""

    def __init__(
        self,
        latest_url: str = _LATEST_URL,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._latest_url = latest_url
        self._on_progress = on_progress

    def fetch(
        self, version: str, target_triple: str, *, offline: bool = False
    ) -> ReleaseAsset:
        if offline:
            raise RuntimeProviderError(
                "cannot resolve a python-build-standalone runtime offline; "
                "re-run `kivyforge lock` with network access."
            )
        pattern = re.compile(
            rf"^cpython-{re.escape(version)}\+\d+-{re.escape(target_triple)}"
            r"-install_only\.tar\.gz$"
        )
        asset = self._from_checksums(version, pattern)
        if asset is not None:
            return asset
        # A release without SHA256SUMS (PBS before it published one), or a
        # build older than the tags read: search the release records.
        for release in self._candidate_releases(version):
            asset = self._match_release(release, pattern)
            if asset is not None:
                return asset
        raise RuntimeProviderError(
            f"no python-build-standalone install_only build found for CPython "
            f"{version} ({target_triple}).\n"
            f"  Check available versions at "
            f"https://github.com/astral-sh/python-build-standalone/releases."
        )

    def _from_checksums(self, version: str, pattern) -> ReleaseAsset | None:
        """The newest release whose SHA256SUMS lists the build, or ``None``."""
        tags = self._release_tags()
        for start in range(0, len(tags), _SUMS_BATCH):
            batch = tags[start : start + _SUMS_BATCH]
            if self._on_progress is not None and start:
                self._on_progress(
                    f"[lock] CPython {version}: checking releases "
                    f"{start + 1}-{start + len(batch)}"
                )
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                sums = list(pool.map(self._release_sums, batch))
            # Newest first: the first release in tag order that has it wins.
            for tag, listing in zip(batch, sums):
                if listing is None:
                    continue
                for line in listing.splitlines():
                    parts = line.split()
                    if len(parts) == 2 and pattern.match(parts[1]):
                        # Quoted as GitHub's browser_download_url is ("+" as
                        # "%2B"), so a lock reads the same whichever path found it.
                        name = urllib.parse.quote(parts[1])
                        return ReleaseAsset(
                            url=f"{_DOWNLOAD}/{tag}/{name}", sha256=parts[0]
                        )
        return None

    def _release_tags(self) -> list[str]:
        """Release tags, newest first; empty if they cannot be listed."""
        tags: list[str] = []
        try:
            for page in range(1, _TAG_PAGES + 1):
                names = [t["name"] for t in self._get_json(_TAGS_URL.format(page=page))]
                tags += [n for n in names if _DATE_TAG.match(n)]
                if len(names) < 100:
                    break
        except RuntimeProviderError:
            return []  # the release-page search reports the failure
        # Date tags sort chronologically as text.
        return sorted(set(tags), reverse=True)

    def _release_sums(self, tag: str) -> str | None:
        """A release's SHA256SUMS, or ``None`` if it has none."""
        try:
            return self._get_download_text(f"{_DOWNLOAD}/{tag}/SHA256SUMS")
        except RuntimeProviderError:
            return None

    def _candidate_releases(self, version: str):
        """Yield the latest release, then older releases page by page.

        Each page lists every asset of its releases, so one is large and slow:
        a pin a few releases back took 10 to 40 s with nothing shown (#88).
        """
        yield self._get_json(self._latest_url)
        for page in range(1, _MAX_PAGES + 1):
            if self._on_progress is not None:
                self._on_progress(
                    f"[lock] CPython {version}: checking older releases (page {page})"
                )
            url = _RELEASES_URL.format(per_page=_PAGE_SIZE, page=page)
            releases = self._get_json(url)
            if not releases:
                return
            yield from releases

    def _match_release(self, release, pattern) -> ReleaseAsset | None:
        assets = {a["name"]: a for a in release.get("assets", [])}
        match = next((n for n in assets if pattern.match(n)), None)
        if match is None:
            return None
        url = assets[match]["browser_download_url"]
        sha256 = self._read_sha256(assets, match, url)
        return ReleaseAsset(url=url, sha256=sha256)

    def _read_sha256(self, assets: dict, name: str, url: str) -> str:
        """Pin the asset's SHA-256, tried most→least authoritative.

        1. GitHub's asset ``digest`` field (``sha256:<hex>``) — no extra fetch.
        2. A per-asset ``<name>.sha256`` companion.
        3. The release-wide ``SHA256SUMS`` manifest.
        """
        digest = assets[name].get("digest") or ""
        if digest.startswith("sha256:"):
            return digest.split(":", 1)[1].strip()

        companion = f"{name}.sha256"
        if companion in assets:
            text = self._get_text(assets[companion]["browser_download_url"])
            return text.split()[0].strip()

        if "SHA256SUMS" in assets:
            sha = self._sha_from_manifest(
                assets["SHA256SUMS"]["browser_download_url"], name
            )
            if sha is not None:
                return sha

        raise RuntimeProviderError(
            f"python-build-standalone asset {name!r} exposes no SHA-256 (no "
            f"digest, .sha256, or SHA256SUMS entry); cannot pin it "
            f"reproducibly ({url})."
        )

    def _sha_from_manifest(self, url: str, name: str) -> str | None:
        for line in self._get_text(url).splitlines():
            parts = line.split()
            # "<hex>  <filename>" — match the filename column exactly.
            if len(parts) == 2 and parts[1].strip() == name:
                return parts[0].strip()
        return None

    def _get_download_text(self, url: str) -> str:
        """A release file, without the API token: release downloads
        redirect to GitHub's file CDN, which has no use for it."""
        req = urllib.request.Request(  # noqa: S310 - https github.com only
            url, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310
                return resp.read().decode("utf-8")
        except (OSError, ValueError) as exc:
            raise RuntimeProviderError(
                f"failed to download python-build-standalone metadata ({url}): {exc}"
            ) from exc

    def _get_json(self, url: str):
        return json.loads(self._get_text(url))

    def _get_text(self, url: str) -> str:
        req = urllib.request.Request(  # noqa: S310 — https GitHub API only
            url, headers=_request_headers()
        )
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310
                return resp.read().decode("utf-8")
        except (OSError, ValueError) as exc:
            raise RuntimeProviderError(
                f"failed to query python-build-standalone metadata ({url}): {exc}"
                + (_RATE_LIMIT_HINT if _is_rate_limited(exc) else "")
            ) from exc
