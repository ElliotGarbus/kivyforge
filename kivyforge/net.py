"""Outgoing HTTP requests identify themselves as kivyforge.

Python's default agent, ``Python-urllib/3.x``, is refused outright by some
hosts: Cloudflare R2's public bucket URLs answer it with 403. A wheel that pip
resolved (pip sends its own agent) would then fail to download at build time.
"""

from __future__ import annotations

import urllib.request

from . import __version__

USER_AGENT = f"kivyforge/{__version__}"


def request(url: str, headers: dict[str, str] | None = None) -> urllib.request.Request:
    """A ``Request`` for *url* carrying kivyforge's User-Agent."""
    return urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
