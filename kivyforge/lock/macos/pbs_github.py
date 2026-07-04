"""GitHub-backed python-build-standalone (PBS) release metadata lookup.

PBS publishes its builds as GitHub release assets on
``astral-sh/python-build-standalone``. Each release is tagged by date and ships,
per platform, an ``install_only`` archive plus a companion ``.sha256`` file. This
fetcher finds the newest release providing the requested version + triple and
returns its download URL + pinned SHA-256.

This is the only networked part of the macOS runtime provider; it is exercised
against the live API at the Phase 3 stop rather than in hermetic unit tests
(which inject a fake ``MetadataFetcher``).
"""

from __future__ import annotations

import json
import re
import urllib.request

from .runtime import ReleaseAsset, RuntimeProviderError

_RELEASES_URL = (
    "https://api.github.com/repos/astral-sh/python-build-standalone/releases"
    "?per_page=100"
)


class GithubPbsMetadataFetcher:
    """Resolve a PBS asset by querying the GitHub releases API."""

    def __init__(self, releases_url: str = _RELEASES_URL) -> None:
        self._releases_url = releases_url

    def fetch(
        self, version: str, arch_triple: str, *, offline: bool = False
    ) -> ReleaseAsset:
        if offline:
            raise RuntimeProviderError(
                "cannot resolve a python-build-standalone runtime offline; "
                "re-run `kivyforge lock` with network access."
            )
        # install_only archive for this exact version + triple, any dated tag.
        pattern = re.compile(
            rf"^cpython-{re.escape(version)}\+\d+-{re.escape(arch_triple)}"
            r"-install_only\.tar\.gz$"
        )
        releases = self._get_json(self._releases_url)
        for release in releases:
            assets = {a["name"]: a for a in release.get("assets", [])}
            match = next((n for n in assets if pattern.match(n)), None)
            if match is None:
                continue
            url = assets[match]["browser_download_url"]
            sha256 = self._read_sha256(assets, match, url)
            return ReleaseAsset(url=url, sha256=sha256)
        raise RuntimeProviderError(
            f"no python-build-standalone install_only build found for CPython "
            f"{version} ({arch_triple}).\n"
            f"  Check available versions at "
            f"https://github.com/astral-sh/python-build-standalone/releases."
        )

    def _read_sha256(self, assets: dict, name: str, url: str) -> str:
        companion = f"{name}.sha256"
        if companion in assets:
            text = self._get_text(assets[companion]["browser_download_url"])
            # The .sha256 file is either a bare digest or "<digest>  <name>".
            return text.split()[0].strip()
        raise RuntimeProviderError(
            f"python-build-standalone asset {name!r} has no companion .sha256; "
            f"cannot pin it reproducibly ({url})."
        )

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
