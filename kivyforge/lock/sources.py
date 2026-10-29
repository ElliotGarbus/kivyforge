"""Which source each package may come from (#86).

pip ranks candidates by version and wheel tag, never by where they came from,
and of two sources with the same file it takes the one listed *last*
(docs/design/dev/package-index-proposal.md §1.2). kivyforge decides instead, by
three rules, the first that applies winning:

1. a package **pinned** to an index comes only from that index;
2. a package with any wheel in a ``find_links`` directory (a **local name**)
   comes only from ``find_links``, on every variant;
3. anything else comes from the indexes, and when two of them tie on version
   and tag, the **first listed** wins: ``extra_index_urls`` in order, then the
   named indexes, then PyPI.

``SourcePolicy`` is those rules for one resolve. The pip shim applies them
(``_pip_shim.py``) and records each candidate's source, which the resolvers read
back to fill in each package's PEP 751 ``index``.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from .. import __version__
from ..report import diagnostics
from ..report.failures import ClassifiedError
from ._pip_shim import FIND_LINKS
from .model import LockedPackage, canonical_name

PYPI = "pypi"
PYPI_URL = "https://pypi.org/simple/"

#: Where a resolver stores the shim's record inside a pip report dict, so the
#: record travels with the report it belongs to.
RECORD_KEY = "kivyforge_sources"


class SourceUnavailable(ClassifiedError):
    """A pinned or local package has no wheel for a variant in its only source."""

    code = diagnostics.LOCK_SOURCE_UNAVAILABLE


class SourceFilterUnavailable(ClassifiedError):
    """This pip cannot be patched to apply the source rules: a kivyforge bug.

    Left as ``KF-ERROR`` on purpose: the user never chose this pip (kivyforge
    depends on it), so there is nothing for them to fix but to report it.
    """


@dataclass(frozen=True)
class NamedIndex:
    """One index the rules can name: ``extra-<n>``, a declared name, or ``pypi``."""

    name: str
    url: str


@dataclass(frozen=True)
class SourcePolicy:
    """The source rules for one platform's resolve."""

    #: Absolute ``find_links`` directories.
    find_links: tuple[str, ...] = ()
    #: Canonical names with at least one wheel in ``find_links``.
    local_names: frozenset[str] = frozenset()
    #: The indexes rule 3 may use, highest priority first; PyPI is last.
    rank: tuple[NamedIndex, ...] = (NamedIndex(PYPI, PYPI_URL),)
    #: Indexes that serve only the packages pinned to them.
    explicit: tuple[NamedIndex, ...] = ()
    #: Canonical package name to the name of the index it is pinned to.
    pins: Mapping[str, str] = field(default_factory=dict)
    #: Canonical names pip must not follow as a dependency: the overlay's
    #: ``exclude``, less the direct dependencies. They come from no source at all.
    exclude: frozenset[str] = frozenset()
    #: The platform being locked, for messages that name its config table.
    platform: str = ""

    @property
    def extra_index_urls(self) -> list[str]:
        """Every index pip must search besides its own default (PyPI)."""
        urls: list[str] = []
        for index in (*self.rank, *self.explicit):
            if index.name != PYPI and index.url not in urls:
                urls.append(index.url)
        return urls

    def index(self, name: str) -> NamedIndex:
        for index in (*self.rank, *self.explicit):
            if index.name == name:
                return index
        if name == PYPI:
            return NamedIndex(PYPI, PYPI_URL)
        raise KeyError(name)

    def pinned_to(self, package: str) -> NamedIndex | None:
        name = self.pins.get(canonical_name(package))
        return self.index(name) if name is not None else None

    def is_local(self, package: str) -> bool:
        """True if ``package`` comes only from ``find_links`` (rule 2)."""
        key = canonical_name(package)
        return key in self.local_names and key not in self.pins

    def environment(self, record: Path) -> str:
        """The JSON the shim reads from ``KIVYFORGE_SOURCE_POLICY``."""
        return json.dumps(
            {
                "kivyforge": __version__,
                "record": str(record),
                "find_links": list(self.find_links),
                "local_names": sorted(self.local_names),
                "rank": [[i.name, i.url] for i in self.rank],
                "explicit": [[i.name, i.url] for i in self.explicit],
                "pins": dict(self.pins),
                "exclude": sorted(self.exclude),
            }
        )

    def unavailable(self, requirement: str, variant: str) -> SourceUnavailable | None:
        """The failure for ``requirement`` having no wheel for ``variant``, if its
        source is fixed; None when pip's own message is the right one.

        ``requirement`` is what pip said it could not satisfy, which may carry a
        specifier (``kivy==2.3.1``).
        """
        match = re.match(r"[A-Za-z0-9._-]+", requirement)
        if match is None:
            return None
        package = match.group(0)
        pinned = self.pinned_to(package)
        if pinned is not None:
            return SourceUnavailable(
                f"{package} is pinned to index {pinned.name!r} ({pinned.url}), "
                f"and that index has no wheel for {variant} that fits.\n"
                "  Fix: pin it to an index that has one, remove the pin, or "
                "add the wheel to a find_links directory.",
                context={
                    "distribution": package,
                    "source": pinned.name,
                    "variant": variant,
                },
            )
        if self.is_local(package):
            return SourceUnavailable(
                f"{package} has wheels in [tool.kivy.{self.platform or '<platform>'}]"
                ".find_links, so "
                f"it comes only from there, and none of them fits {variant}.\n"
                f"  Fix: add a {variant} wheel for it to the find_links directory, "
                "remove its wheels to take it from an index, or pin it to an "
                "index in sources.",
                context={
                    "distribution": package,
                    "source": FIND_LINKS,
                    "variant": variant,
                },
            )
        return None


def source_policy(
    find_links: Sequence[str],
    extra_index_urls: Sequence[str],
    *,
    named: Sequence[tuple[str, str, bool]] = (),
    pins: Mapping[str, str] | None = None,
    exclude: Iterable[str] = (),
    platform: str = "",
) -> SourcePolicy:
    """The rules for ``find_links`` (absolute directories), the overlay's
    ``extra_index_urls``, the effective named indexes as ``(name, url,
    explicit)``, the effective pins (package name to index name), and the
    names pip must not follow as a dependency."""
    rank = [
        NamedIndex(f"extra-{n}", index_base(url))
        for n, url in enumerate(extra_index_urls, 1)
    ]
    rank += [
        NamedIndex(name, index_base(url))
        for name, url, explicit in named
        if not explicit
    ]
    rank.append(NamedIndex(PYPI, PYPI_URL))
    return SourcePolicy(
        find_links=tuple(find_links),
        local_names=frozenset(local_names(find_links)),
        rank=tuple(rank),
        explicit=tuple(
            NamedIndex(name, index_base(url))
            for name, url, explicit in named
            if explicit
        ),
        pins={canonical_name(k): v for k, v in (pins or {}).items()},
        exclude=frozenset(canonical_name(n) for n in exclude),
        platform=platform,
    )


def index_base(url: str) -> str:
    """An index URL as the lock records it: with one trailing slash."""
    return url.rstrip("/") + "/"


def local_names(directories: Iterable[str]) -> set[str]:
    """Canonical names of the wheels in ``directories``, whatever their tags."""
    names: set[str] = set()
    for directory in directories:
        for wheel in Path(directory).glob("*.whl"):
            try:
                names.add(canonical_name(parse_wheel_filename(wheel.name)[0]))
            except InvalidWheelFilename:
                continue
    return names


def local_wheels(directories: Iterable[str], package: str) -> list[Path]:
    """The wheels for ``package`` in ``directories``."""
    key = canonical_name(package)
    found: list[Path] = []
    for directory in directories:
        for wheel in sorted(Path(directory).glob("*.whl")):
            try:
                if canonical_name(parse_wheel_filename(wheel.name)[0]) == key:
                    found.append(wheel)
            except InvalidWheelFilename:
                continue
    return found


def read_record(path: Path) -> dict[str, str | None]:
    """The shim's record: each candidate's file URL to its source."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class IndexTracker:
    """Collects, across variants, which index served each package."""

    def __init__(self) -> None:
        self._seen: dict[str, set[str | None]] = {}

    def add(self, report: Mapping) -> None:
        record = report.get(RECORD_KEY, {})
        for item in report.get("install", []):
            name = item.get("metadata", {}).get("name")
            if not name:
                continue
            url = item.get("download_info", {}).get("url", "")
            source = record.get(url.split("#", 1)[0])
            self._seen.setdefault(canonical_name(name), set()).add(
                None if source == FIND_LINKS else source
            )

    def index_of(self, name: str) -> str | None:
        """The one index every variant took ``name`` from, else None."""
        seen = self._seen.get(canonical_name(name), set())
        if len(seen) == 1:
            return next(iter(seen))
        return None


def drop_moved_pins(
    pins: Mapping[str, str], locked: Iterable[LockedPackage], policy: SourcePolicy
) -> dict[str, str]:
    """``pins`` without the packages whose locked source the rules no longer allow.

    A kept ``==version`` pin would hold a package to a file its new source does
    not have, and the resolve would fail with ``KF-LOCK-PINS-CONFLICT``; the
    remedy, ``--update``, would move every other package too. Dropping it moves
    only the package whose source changed (§5.2).
    """
    kept = dict(pins)
    for package in locked:
        key = canonical_name(package.name)
        if key not in kept:
            continue
        from_path = any(w.path for w in package.wheels)
        pinned = policy.pinned_to(key)
        if pinned is not None:
            moved = from_path or package.source_index != pinned.url
        elif policy.is_local(key):
            moved = not from_path
        else:
            moved = from_path
        if moved:
            del kept[key]
    return kept


def _source_label(package: LockedPackage) -> str:
    if any(w.path for w in package.wheels):
        return FIND_LINKS
    return package.source_index or "an index"


def source_changes(
    old: Iterable[LockedPackage], new: Iterable[LockedPackage]
) -> list[str]:
    """``--check`` lines for packages whose version held but whose source moved."""
    old_by_name = {canonical_name(p.name): p for p in old}
    out: list[str] = []
    for package in sorted(new, key=lambda p: canonical_name(p.name)):
        before = old_by_name.get(canonical_name(package.name))
        if before is None or before.version != package.version:
            continue
        was, now = _source_label(before), _source_label(package)
        if was != now:
            out.append(f"  ~ {package.name}: from {was} -> from {now}")
    return out


def wheel_changes(
    old: Iterable[LockedPackage], new: Iterable[LockedPackage]
) -> list[str]:
    """``--check`` lines for a wheel whose version and filename held but whose hash moved.

    A wheel rebuilt into ``find_links`` from a newer commit usually keeps its
    filename (every commit on a branch builds as the same ``.devN``), so
    without this line ``--check`` failed with an empty diff.
    """
    old_by_name = {canonical_name(p.name): p for p in old}
    out: list[str] = []
    for package in sorted(new, key=lambda p: canonical_name(p.name)):
        before = old_by_name.get(canonical_name(package.name))
        if before is None or before.version != package.version:
            continue
        hashes = {w.name: w.sha256 for w in before.wheels}
        for wheel in sorted(package.wheels, key=lambda w: w.name):
            was = hashes.get(wheel.name)
            if was is not None and was != wheel.sha256:
                out.append(
                    f"  ~ {package.name}: {wheel.name} changed "
                    f"(sha256 {was[:12]} -> {wheel.sha256[:12]})"
                )
    return out


def changed_local_wheels(
    packages: Iterable[LockedPackage], project_root: Path
) -> dict[str, list[str]]:
    """The locked ``find_links`` wheels that are missing or no longer match their hash.

    ``lock_inputs_sha256`` sees the ``find_links`` *setting*, not the files in
    it, so replacing a wheel with one of the same name left a lock that read
    as in sync and a build that failed its hash check. Keyed by canonical
    package name; each value is the ``lock`` progress lines for that package.
    """
    from ..artifacts.verify import sha256_file

    root = project_root.resolve()
    changed: dict[str, list[str]] = {}
    for package in packages:
        if not isinstance(package, LockedPackage):
            continue
        for wheel in package.wheels:
            if not wheel.path:
                continue
            path = root / wheel.path
            if not path.is_file():
                line = f"  - {package.name}: {wheel.path} is missing"
            elif sha256_file(path) != wheel.sha256:
                line = f"  ~ {package.name}: {wheel.path} changed since it was locked"
            else:
                continue
            changed.setdefault(canonical_name(package.name), []).append(line)
    return changed


def ignore_unrecorded_indexes[L](existing: L, candidate: L) -> L:
    """``candidate`` without the indexes ``existing`` never recorded.

    A lock written before #86 has no ``index`` on any package, so without this
    every such lock would fail ``lock --check`` until re-locked, though nothing
    it installs has changed. The index arrives with the next real re-lock.
    """
    if not dataclasses.is_dataclass(candidate) or isinstance(candidate, type):
        return candidate
    recorded = {
        canonical_name(p.name)
        for p in getattr(existing, "packages", ())
        if isinstance(p, LockedPackage) and p.source_index is not None
    }
    packages = tuple(
        dataclasses.replace(p, source_index=None)
        if isinstance(p, LockedPackage)
        and p.source_index is not None
        and canonical_name(p.name) not in recorded
        else p
        for p in getattr(candidate, "packages", ())
    )
    return dataclasses.replace(candidate, packages=packages)


def overlay_policy(
    overlay: object,
    find_links: Sequence[str],
    *,
    platform: str,
    exclude: Iterable[str] = (),
) -> SourcePolicy:
    """The rules for a platform overlay: its ``extra_index_urls``, and the
    effective named ``indexes`` and ``sources`` the loader computed for it.

    ``exclude`` is passed in rather than read from the overlay because the
    builder decides it: direct dependencies, and on Android pyjnius, are
    never excluded."""
    return source_policy(
        find_links,
        tuple(getattr(overlay, "extra_index_urls", ()) or ()),
        named=[(i.name, i.url, i.explicit) for i in getattr(overlay, "indexes", ())],
        pins=dict(getattr(overlay, "sources", ())),
        exclude=exclude,
        platform=platform,
    )


def pinned_local_warnings(policy: SourcePolicy, project_root: Path) -> list[str]:
    """One warning per pinned package whose ``find_links`` wheels the pin hides.

    The pin wins (rule 1), which is how you switch from your own build to an
    index's without deleting it. Said out loud, so a pin left behind, or a
    wheel you forgot, does not go unnoticed.
    """
    root = project_root.resolve()
    out: list[str] = []
    for package, index_name in sorted(policy.pins.items()):
        if package not in policy.local_names:
            continue
        index = policy.index(index_name)
        wheels = []
        for wheel in local_wheels(policy.find_links, package):
            try:
                wheels.append(wheel.resolve().relative_to(root).as_posix())
            except ValueError:
                wheels.append(str(wheel))
        listed = "".join(f"\n  {w}" for w in wheels)
        out.append(
            f"{package} is pinned to index {index.name!r} in sources, so its "
            f"wheels in find_links are ignored:{listed}\n"
            "  Remove the pin to use them again."
        )
    return out


def unused_explicit_indexes(config: object) -> list[str]:
    """A warning per explicit index that no target's ``sources`` pins to.

    It would serve nothing, which is most likely a pin that was forgotten or
    misspelt. Not an error: the target that uses it may not be configured yet.
    """
    kivy = getattr(config, "kivy", None)
    explicit = [i for i in getattr(kivy, "indexes", ()) if i.explicit]
    if not explicit:
        return []
    used = {name for _package, name in getattr(kivy, "sources", ())}
    for platform in ("ios", "macos", "linux", "windows", "android"):
        overlay = getattr(config, platform, None)
        used |= {name for _package, name in getattr(overlay, "sources", ())}
    return [
        f"index {index.name!r} is explicit, but no sources table pins a package "
        "to it, so nothing comes from it. Pin a package to it, or remove "
        "`explicit = true`."
        for index in explicit
        if index.name not in used
    ]
