"""The host CPython that byte-compiles, pinned in the lock.

iOS and Android, and a Linux ``aarch64`` target built on x86_64, compile their
``.pyc`` with a CPython that runs on the build machine, of the minor the app
ships. ``lock`` pins one python-build-standalone build of it for every host
that can build the platform, as ``[[tool.kivyforge.host_python]]``; ``build``
fetches the one for its host and compiles with nothing else
(``docs/design/dev/host-python-download-proposal.md``).

Every capable host always gets an entry, and the entry says what it is, so a
missing table can only mean a lock written before the table existed:

- ``pinned``: ``version``, ``variant``, ``url`` and ``sha256`` name the build;
- ``no-build``: PBS had no final build of the minor for the triple when
  ``lock`` last looked;
- ``unresolved-offline``: ``lock --offline`` had no earlier pin to keep.

Every entry records its ``minor``, so a lock whose shipped minor moved is
recognised without reading the runtime table.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..report import diagnostics, exit_codes
from ..report.failures import ClassifiedError

# The lock models import this module, and ``wheelruntime``'s package imports
# its model, so its runtime types are imported where used, not here.
if TYPE_CHECKING:
    from .wheelruntime.runtime import ReleaseAsset

PINNED = "pinned"
NO_BUILD = "no-build"
UNRESOLVED_OFFLINE = "unresolved-offline"
STATES = (PINNED, NO_BUILD, UNRESOLVED_OFFLINE)

MACOS_ARM64 = "aarch64-apple-darwin"
LINUX_X86_64 = "x86_64-unknown-linux-gnu"
WINDOWS_AMD64 = "x86_64-pc-windows-msvc"

#: Within one release, the first published variant wins. Stripped is the same
#: layout without debug symbols: 36 MB against 79 MB on Linux and 23 MB against
#: 50 MB on Windows for 3.15.0 (measured 2026-11-06), and it compiles alike.
VARIANTS = ("install_only_stripped", "install_only")


class HostPythonLockError(ClassifiedError):
    """``lock`` could not look up the host CPython builds: about the network."""

    code = diagnostics.HOST_PYTHON_FETCH
    exit_code = exit_codes.ENVIRONMENT_ERROR


@dataclass(frozen=True)
class HostPython:
    """One ``[[tool.kivyforge.host_python]]`` entry: one host's compiler."""

    triple: str
    state: str
    minor: str
    version: str | None = None
    variant: str | None = None
    url: str | None = None
    sha256: str | None = None


class CommonFetcher(Protocol):
    """The fetcher method :func:`resolve` needs, so tests can stand in."""

    def find_common_install_only(
        self,
        minor: str,
        triples: tuple[str, ...],
        *,
        prefer: str | None = None,
        variants: tuple[str, ...] = VARIANTS,
    ) -> tuple[str | None, dict[str, tuple[str, ReleaseAsset]]]: ...


def needed_triples(platform: str, archs: Iterable[str] = ()) -> tuple[str, ...]:
    """The hosts whose builds of *platform* compile with a host interpreter.

    iOS builds only on a Mac; Android on any of the three build hosts; Linux
    only for an ``aarch64`` target, which is built on x86_64 Linux. macOS and
    Windows ship only the arch they build on, so their staged runtime always
    compiles its own payload, and need none.
    """
    if platform == "ios":
        return (MACOS_ARM64,)
    if platform == "android":
        return tuple(sorted((MACOS_ARM64, LINUX_X86_64, WINDOWS_AMD64)))
    if platform == "linux" and "aarch64" in tuple(archs):
        return (LINUX_X86_64,)
    return ()


def lock_triples(platform: str, lock: object) -> tuple[str, ...]:
    """:func:`needed_triples` for a loaded lock of *platform*."""
    return needed_triples(platform, getattr(lock, "archs", ()) or ())


def shipped_version(lock: object) -> str:
    """The runtime version a lock ships, whichever lock family it is."""
    xcframework = getattr(lock, "python_xcframework", None)
    if xcframework is not None:
        return xcframework.version
    android = getattr(lock, "python_android", None)
    if android:
        return android[0].version
    runtime = getattr(lock, "python_runtime", None)
    if runtime is not None:
        return runtime.version
    raise ValueError(f"{type(lock).__name__} records no runtime version")


def is_final(version: str) -> bool:
    """``3.15.2`` is; ``3.15.0rc1`` and ``3.16.0b2`` are not."""
    parts = version.split(".")
    return len(parts) == 3 and all(p.isdigit() for p in parts)


def minor_of(version: str) -> str:
    """``3.15.2`` and ``3.15.0rc1`` -> ``3.15``."""
    major, minor = version.split(".")[:2]
    return f"{major}.{''.join(c for c in minor if c.isdigit())}"


def entry_for(entries: Iterable[HostPython] | None, triple: str) -> HostPython | None:
    """This triple's entry, or ``None`` when the lock has none for it."""
    return next((e for e in entries or () if e.triple == triple), None)


def incomplete(
    entries: tuple[HostPython, ...] | None, triples: tuple[str, ...], minor: str
) -> str | None:
    """Why a lock's table is incomplete, or ``None`` when it is complete.

    Incomplete means a plain ``lock`` has something to do: the table is missing
    (a lock written before it existed), an entry is missing or
    ``unresolved-offline``, or an entry is for a different minor. ``no-build``
    is complete: nothing can be pinned until PBS publishes, and finding out
    would need the network.
    """
    if not triples:
        return None
    if entries is None:
        return "it has no [[tool.kivyforge.host_python]] table (it predates it)"
    for triple in triples:
        entry = entry_for(entries, triple)
        if entry is None:
            return f"it has no host CPython entry for {triple}"
        if entry.minor != minor:
            return f"its host CPython for {triple} is {entry.minor}, not {minor}"
        if entry.state == UNRESOLVED_OFFLINE:
            return f"its host CPython for {triple} was not resolved (locked offline)"
    return None


def resolve(
    version: str,
    triples: tuple[str, ...],
    *,
    prefer: tuple[HostPython, ...] | None = None,
    offline: bool = False,
    retry_no_build: bool = True,
    fetcher: CommonFetcher | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[HostPython, ...] | None:
    """The table for a lock that ships *version*, one entry per triple.

    ``None`` when the platform needs none. *prefer* is the existing table:
    pinned entries of the same minor are kept when they all agree, which skips
    the lookup (``lock`` and ``lock --check``, proposal Q8); ``lock --update``
    passes none, so it re-pins. When anything is missing, every triple is
    resolved together, preferring the kept version if there is one, so all
    hosts keep sharing one version (Q3). *retry_no_build* looks a ``no-build``
    entry up again rather than keeping it.
    """
    if not triples:
        return None
    progress = on_progress or (lambda _line: None)
    minor = minor_of(version)
    if not is_final(version):
        # A pre-release's .pyc format can still change, and no host CPython
        # writes one it is guaranteed to load.
        return tuple(HostPython(t, NO_BUILD, minor) for t in triples)

    held = {e.triple: e for e in prefer or () if e.minor == minor}
    pinned = {t: e for t, e in held.items() if e.state == PINNED}
    kept_versions = {e.version for e in pinned.values()}
    settled = all(
        t in pinned or (t in held and held[t].state == NO_BUILD and not retry_no_build)
        for t in triples
    )
    if settled and len(kept_versions) <= 1:
        progress(f"[lock] host CPython {minor}: keeping the locked builds")
        return tuple(held[t] for t in triples)
    if offline:
        return tuple(
            pinned.get(t) or HostPython(t, UNRESOLVED_OFFLINE, minor) for t in triples
        )

    from .wheelruntime.runtime import RuntimeProviderError

    want = next(iter(kept_versions)) if len(kept_versions) == 1 else version
    fetcher = fetcher or _default_fetcher(progress)
    try:
        found_version, builds = fetcher.find_common_install_only(
            minor, triples, prefer=want
        )
    except RuntimeProviderError as exc:
        raise HostPythonLockError(
            f"could not look up host CPython {minor} builds for byte-compiling: "
            f"{exc}\n  Fix: retry with network access; in CI, set GITHUB_TOKEN.",
            context={"tool": f"python{minor}"},
        ) from exc
    entries = []
    for triple in triples:
        build = builds.get(triple)
        if build is None or found_version is None:
            entries.append(HostPython(triple, NO_BUILD, minor))
            continue
        variant, asset = build
        entries.append(
            HostPython(
                triple,
                PINNED,
                minor,
                version=found_version,
                variant=variant,
                url=asset.url,
                sha256=asset.sha256,
            )
        )
    if found_version is not None:
        hosts = ", ".join(e.triple for e in entries if e.state == PINNED)
        progress(f"[lock] host CPython {found_version} for byte-compiling: {hosts}")
    return tuple(entries)


def describe_gaps(entries: tuple[HostPython, ...] | None) -> list[str]:
    """One warning per entry a build can't use, for ``lock`` to report."""
    lines = []
    for entry in entries or ():
        if entry.state == NO_BUILD:
            lines.append(
                f"no final python-build-standalone CPython {entry.minor} build for "
                f"{entry.triple} yet; release builds on that host ship source until "
                "a re-lock finds one"
            )
        elif entry.state == UNRESOLVED_OFFLINE:
            lines.append(
                f"host CPython {entry.minor} for {entry.triple} not resolved "
                "(locked offline); run `kivyforge lock` with network access"
            )
    return lines


def emit(lines: list[str], entries: tuple[HostPython, ...] | None) -> None:
    """``[[tool.kivyforge.host_python]]``, one table per triple, sorted."""
    for entry in sorted(entries or (), key=lambda e: e.triple):
        lines.append("")
        lines.append("[[tool.kivyforge.host_python]]")
        lines.append(f'triple = "{entry.triple}"')
        lines.append(f'state = "{entry.state}"')
        lines.append(f'minor = "{entry.minor}"')
        if entry.state == PINNED:
            lines.append(f'version = "{entry.version}"')
            lines.append(f'variant = "{entry.variant}"')
            lines.append(f'url = "{entry.url}"')
            lines.append(f'sha256 = "{entry.sha256}"')


def parse(tool: dict) -> tuple[HostPython, ...] | None:
    """The table from a lock's ``[tool.kivyforge]``, or ``None`` when absent.

    Raises ``ValueError`` for an entry the writer would never produce, which
    each lock's reader turns into its own ``LockError``.
    """
    raw = tool.get("host_python")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("[[tool.kivyforge.host_python]] must be an array of tables")
    entries = []
    for item in raw:
        state = item.get("state")
        if state not in STATES or not item.get("triple") or not item.get("minor"):
            raise ValueError(
                f"[[tool.kivyforge.host_python]] entry is invalid: {item!r}"
            )
        fields = ("version", "variant", "url", "sha256")
        if state == PINNED and not all(item.get(f) for f in fields):
            raise ValueError(
                f"[[tool.kivyforge.host_python]] {item['triple']} is pinned but "
                f"lacks one of {', '.join(fields)}"
            )
        entries.append(
            HostPython(
                triple=item["triple"],
                state=state,
                minor=item["minor"],
                version=item.get("version"),
                variant=item.get("variant"),
                url=item.get("url"),
                sha256=item.get("sha256"),
            )
        )
    return tuple(sorted(entries, key=lambda e: e.triple))


def _default_fetcher(progress: Callable[[str], None]) -> CommonFetcher:
    from .wheelruntime.pbs_github import GithubPbsMetadataFetcher

    return GithubPbsMetadataFetcher(on_progress=progress)
