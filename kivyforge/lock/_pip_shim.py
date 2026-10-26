"""Run pip with the *target's* PEP 508 marker environment and kivyforge's source rules.

kivyforge invokes this instead of ``-m pip`` when resolving a lock. It patches
two pip internals, then hands control to pip unchanged:

- **Markers.** It replaces ``packaging.markers.default_environment`` — the
  single function every ``Marker.evaluate()`` consults — with the target
  environment supplied as JSON in ``KIVYFORGE_TARGET_MARKER_ENV``. A desktop
  lock, which evaluates markers for the host on purpose, says so with
  ``KIVYFORGE_HOST_MARKERS=1`` instead.
- **Sources** (``KIVYFORGE_SOURCE_POLICY``, optional). It wraps
  ``PackageFinder.find_all_candidates`` so each project only sees candidates
  from the sources it may use: a pinned index, else the ``find_links``
  directories when they hold a wheel for it, else the indexes. The survivors
  are ordered so the first-listed index wins a tie, and every survivor's
  source is written to a record file so the lock can name each package's index
  (docs/design/dev/package-index-proposal.md §4).

pip still performs the whole resolution, including backtracking and platform
wheel-tag expansion; only what it is allowed to see changes. kivyforge
deliberately does not reimplement any of that.

This file imports nothing from kivyforge: it is run by path, sometimes with an
interpreter that only has pip installed.

Both patches depend on pip internals, so they fail loudly rather than falling
back: a quiet fallback would reintroduce exactly the host-dependent or
wrong-source lock this exists to prevent.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlparse
from urllib.request import url2pathname

MARKER_ENV_VAR = "KIVYFORGE_TARGET_MARKER_ENV"
HOST_MARKERS_ENV_VAR = "KIVYFORGE_HOST_MARKERS"
SOURCE_POLICY_ENV_VAR = "KIVYFORGE_SOURCE_POLICY"

#: Exit status when this pip cannot be patched to apply the source rules. pip
#: never returns it, so the resolver can tell it from a resolution failure.
SOURCE_FILTER_UNAVAILABLE = 97

#: A candidate's source in the record, for a wheel from a find_links directory.
FIND_LINKS = "find_links"


def main(argv: list[str]) -> int:
    status = _apply_markers()
    if status:
        return status

    raw_policy = os.environ.get(SOURCE_POLICY_ENV_VAR)
    record: dict[str, str | None] | None = None
    policy: _Policy | None = None
    if raw_policy:
        policy = _Policy(json.loads(raw_policy))
        record = {}
        missing = _install_source_filter(policy, record)
        if missing:
            sys.stderr.write(
                f"kivyforge {policy.kivyforge} cannot apply its source rules with "
                f"pip {_pip_version()}: pip has no {missing}. This is a kivyforge "
                "bug; please report it. Until it is fixed, install an older pip "
                "in kivyforge's environment.\n"
            )
            return SOURCE_FILTER_UNAVAILABLE

    from pip._internal.cli.main import main as pip_main

    try:
        return pip_main(argv)
    finally:
        if policy is not None and record is not None and policy.record:
            with open(policy.record, "w", encoding="utf-8") as f:
                json.dump(record, f)


def _apply_markers() -> int:
    if os.environ.get(HOST_MARKERS_ENV_VAR) == "1":
        return 0
    raw = os.environ.get(MARKER_ENV_VAR)
    if not raw:
        sys.stderr.write(
            f"{MARKER_ENV_VAR} is not set; refusing to resolve with the "
            "host's marker environment.\n"
        )
        return 2
    environment = json.loads(raw)

    try:
        from pip._vendor.packaging import markers
    except ImportError:
        sys.stderr.write(
            "this pip does not vendor packaging.markers where kivyforge "
            "expects it, so environment markers cannot be evaluated for the "
            "target platform. Please report the pip version.\n"
        )
        return 3
    if not hasattr(markers, "default_environment"):
        sys.stderr.write(
            "pip's vendored packaging has no default_environment(); kivyforge "
            "cannot retarget marker evaluation. Please report the pip version.\n"
        )
        return 3

    markers.default_environment = lambda: dict(environment)
    return 0


class _Policy:
    """The source rules for one resolve, as kivyforge's ``SourcePolicy`` wrote them."""

    def __init__(self, data: dict) -> None:
        self.kivyforge: str = data.get("kivyforge", "?")
        self.record: str | None = data.get("record")
        self.find_links = tuple(
            os.path.normcase(os.path.abspath(p)) for p in data.get("find_links", ())
        )
        self.local_names = frozenset(data.get("local_names", ()))
        # Highest priority first; PyPI is in here, last.
        self.rank = tuple(_base(url) for _name, url in data.get("rank", ()))
        self.explicit = tuple(_base(url) for _name, url in data.get("explicit", ()))
        urls = {name: _base(url) for name, url in data.get("rank", ())}
        urls.update({name: _base(url) for name, url in data.get("explicit", ())})
        self.pins = {pkg: urls[index] for pkg, index in data.get("pins", {}).items()}
        # Longest first, so an index nested under another's URL wins.
        self.indexes = sorted(
            set(self.rank) | set(self.explicit), key=len, reverse=True
        )

    def source(self, link) -> str | None:
        """The index base URL ``link`` was found on, ``FIND_LINKS``, or None."""
        url = link.url
        if url.startswith("file:") and self.find_links:
            path = os.path.normcase(os.path.abspath(url2pathname(urlparse(url).path)))
            if any(path.startswith(d + os.sep) for d in self.find_links):
                return FIND_LINKS
        page = link.comes_from
        # The page object, not str(): str() redacts a password in the URL.
        page_url = getattr(page, "url", page)
        if isinstance(page_url, str):
            for base in self.indexes:
                if page_url.startswith(base):
                    return base
        return None

    def select(self, name: str, candidates: list) -> list:
        """The candidates ``name`` may use, lowest-ranked source first."""
        sources = [(c, self.source(c.link)) for c in candidates]
        pinned = self.pins.get(name)
        if pinned is not None:
            kept = [(c, s) for c, s in sources if s == pinned]
        elif name in self.local_names:
            kept = [(c, s) for c, s in sources if s == FIND_LINKS]
        else:
            # A candidate from no configured source (an index whose pages
            # redirect elsewhere, say) is kept, ranked last: dropping it would
            # break a lock that resolves today.
            explicit = set(self.explicit) - set(self.rank)
            kept = [(c, s) for c, s in sources if s not in explicit]
        # pip sorts stably by version and tag and takes the *last* of equals,
        # so lowest-ranked first makes the first-listed index win a tie.
        kept.sort(key=lambda pair: self._rank(pair[1]), reverse=True)
        return kept

    def _rank(self, source: str | None) -> int:
        if source in self.rank:
            return self.rank.index(source)
        return 0 if source == FIND_LINKS else len(self.rank)


def _install_source_filter(policy: _Policy, record: dict[str, str | None]) -> str:
    """Wrap ``find_all_candidates``; return what is missing, or ``""``."""
    try:
        from pip._internal.index.package_finder import PackageFinder
        from pip._internal.models.candidate import InstallationCandidate
        from pip._internal.models.link import Link
        from pip._vendor.packaging.utils import canonicalize_name
    except ImportError as exc:
        return f"importable {exc.name or 'module'}"
    original = getattr(PackageFinder, "find_all_candidates", None)
    if original is None:
        return "PackageFinder.find_all_candidates"
    if not hasattr(InstallationCandidate, "link"):
        return "InstallationCandidate.link"
    if not hasattr(Link, "comes_from"):
        return "Link.comes_from"

    def find_all_candidates(self, project_name):
        selected = policy.select(
            canonicalize_name(project_name), original(self, project_name)
        )
        for candidate, source in selected:
            record[candidate.link.url.split("#", 1)[0]] = source
        kept = [candidate for candidate, _source in selected]
        # pip caches per project; keep the filtered list there too, so every
        # later lookup sees the same candidates.
        cache = getattr(self, "_all_candidates", None)
        if isinstance(cache, dict):
            cache[project_name] = kept
        return kept

    PackageFinder.find_all_candidates = find_all_candidates
    return ""


def _base(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def _pip_version() -> str:
    try:
        from pip import __version__
    except ImportError:
        return "?"
    return __version__


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
