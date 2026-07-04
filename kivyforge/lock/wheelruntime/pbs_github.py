"""GitHub-backed python-build-standalone (PBS) release metadata lookup.

PBS publishes builds as GitHub release assets on
``astral-sh/python-build-standalone``. Each release is tagged by date and ships,
per platform, an ``install_only`` archive plus a companion ``.sha256`` file. This
fetcher finds the newest release providing the requested version + target triple
and returns its download URL + pinned SHA-256. It is triple-agnostic, so macOS
and (later) Linux share it unchanged.

This is the only networked part of the runtime provider; it is exercised against
the live API at the phase stop rather than in hermetic unit tests (which inject a
fake ``MetadataFetcher``).
"""

from __future__ import annotations

import json
import re
import urllib.request

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


class GithubPbsMetadataFetcher:
    """Resolve a PBS asset by querying the GitHub releases API."""

    def __init__(self, latest_url: str = _LATEST_URL) -> None:
        self._latest_url = latest_url

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
        for release in self._candidate_releases():
            asset = self._match_release(release, pattern)
            if asset is not None:
                return asset
        raise RuntimeProviderError(
            f"no python-build-standalone install_only build found for CPython "
            f"{version} ({target_triple}).\n"
            f"  Check available versions at "
            f"https://github.com/astral-sh/python-build-standalone/releases."
        )

    def _candidate_releases(self):
        """Yield the latest release, then older releases page by page."""
        yield self._get_json(self._latest_url)
        for page in range(1, _MAX_PAGES + 1):
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

    def _get_json(self, url: str):
        return json.loads(self._get_text(url))

    def _get_text(self, url: str) -> str:
        req = urllib.request.Request(  # noqa: S310 — https GitHub API only
            url, headers={"Accept": "application/vnd.github+json"}
        )
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310
                return resp.read().decode("utf-8")
        except (OSError, ValueError) as exc:
            raise RuntimeProviderError(
                f"failed to query python-build-standalone metadata ({url}): {exc}"
            ) from exc
