"""A host CPython that byte-compiles, installed by ``kivyforge bytecompiler``.

Writing ``.pyc`` for a target needs a final CPython of the shipped minor on the
build machine (``docs/design/common/10-byte-compile.md``). iOS and Android never
ship one that runs here, so the user installs one, or runs ``kivyforge
bytecompiler`` and kivyforge installs a python-build-standalone (PBS) build
for this host: verified against its release's ``SHA256SUMS``, kept in the
artifact cache, and extracted to one directory per minor, where the search in
:mod:`kivyforge.bundle.pycompile` finds it. ``build`` and ``package`` never call
:func:`install`; only the verb does
(``docs/design/dev/host-python-download-proposal.md``).

The downloaded interpreter never ships and no lock records it: any final
release of the minor writes ``.pyc`` the runtime loads, so which one it is
doesn't change the build's output.
"""

from __future__ import annotations

import platform as _platform
import tarfile
import tempfile
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from ..artifacts.cache import ArtifactCache
from ..artifacts.download import Downloader, DownloadError, fetch_artifact
from ..artifacts.verify import HashMismatch
from ..lock.wheelruntime.runtime import ReleaseAsset, RuntimeProviderError
from ..report import diagnostics, exit_codes, failures
from ..report.failures import ClassifiedError
from ..status import LockState, LockStatus

#: The three build hosts kivyforge supports
#: (``docs/guides/get-started/hosts.md``), keyed as
#: ``(platform.system(), host_machine())``. Any other host has no build here.
HOST_TRIPLES = {
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Windows", "amd64"): "x86_64-pc-windows-msvc",
}


class HostPythonError(ClassifiedError):
    """A host CPython could not be installed. Always about the machine: exit 3."""

    exit_code = exit_codes.ENVIRONMENT_ERROR


class InstallFetcher(Protocol):
    """The one fetcher method :func:`install` needs, so tests can stand in."""

    def find_install_only(
        self, minor: str, target_triple: str, *, prefer: str | None = None
    ) -> tuple[str, ReleaseAsset] | None: ...


@dataclass(frozen=True)
class ByteCompileNeed:
    """What byte-compiling one platform's build needs from this host.

    Each backend reports it from its own config and lock
    (:meth:`kivyforge.platforms.base.Platform.byte_compile_need`), so the verb
    stays backend-agnostic.
    """

    platform: str
    #: ``byte_compile`` as configured: ``True``, ``False`` or ``"release"``.
    byte_compile: bool | str
    #: Whether the build compiles with a host interpreter at all. Always true
    #: for iOS and Android; on desktop only for a target arch this host can't
    #: run (Linux ``aarch64`` from x86_64).
    host_compiler: bool
    #: The runtime version the lock ships, or ``None`` when the lock is missing,
    #: unreadable or stale (``lock_problem`` says which).
    python_version: str | None
    #: ``None`` when the lock is usable; otherwise the failure to report.
    lock_problem: ClassifiedError | None = None


def byte_compile_need(
    platform: str,
    *,
    byte_compile: bool | str,
    host_compiler: bool,
    lock: LockStatus,
    lock_version: Callable[[], str],
) -> ByteCompileNeed:
    """Build a :class:`ByteCompileNeed` from a backend's own lock status.

    *lock_version* reads the shipped runtime version from the lock, and is
    called only when the lock is in sync: a stale lock's version may not be
    what the next build ships.
    """
    if lock.in_sync:
        return ByteCompileNeed(
            platform, byte_compile, host_compiler, python_version=lock_version()
        )
    preset = {
        LockState.MISSING: failures.LOCK_MISSING,
        LockState.UNREADABLE: failures.LOCK_UNREADABLE,
        LockState.OUT_OF_DATE: failures.LOCK_DRIFT,
    }[lock.state]
    problem = ClassifiedError(
        f"pylock.{platform}.toml is {lock.state.value}, so the version {platform} "
        f"ships is unknown.\n  Fix: run `{lock.relock_command}`.",
        **preset,
    )
    return ByteCompileNeed(
        platform, byte_compile, host_compiler, python_version=None, lock_problem=problem
    )


@dataclass(frozen=True)
class Installed:
    """A host CPython kivyforge installed: its exact version and interpreter."""

    version: str
    interpreter: Path


def host_triple(*, system: str | None = None, machine: str | None = None) -> str | None:
    """This host's PBS triple, or ``None`` on a host kivyforge doesn't build on."""
    from ..host import host_machine

    key = (
        system if system is not None else _platform.system(),
        machine if machine is not None else host_machine(),
    )
    return HOST_TRIPLES.get(key)


def install_root(cache: ArtifactCache | None = None) -> Path:
    """Where installs live: inside the artifact cache, so ``clean --cache``
    removes them along with the archives they came from."""
    return (cache or ArtifactCache()).root / "host-python"


def installed_interpreter(minor: str, *, root: Path | None = None) -> Path | None:
    """The interpreter kivyforge installed for *minor*, if there is one."""
    exe = _interpreter_in(Path(root or install_root()) / minor, minor)
    return exe if exe.is_file() else None


def _interpreter_in(directory: Path, minor: str) -> Path:
    """PBS ``install_only`` layout: ``python/python.exe`` on Windows,
    ``python/bin/python3.X`` everywhere else."""
    if _platform.system() == "Windows":
        return directory / "python" / "python.exe"
    return directory / "python" / "bin" / f"python{minor}"


def install(
    minor: str,
    *,
    prefer: str | None = None,
    fetcher: InstallFetcher | None = None,
    cache: ArtifactCache | None = None,
    downloader: Downloader | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> Installed:
    """Download, verify and install a final CPython *minor* for this host.

    *prefer* is the exact version the lock ships; it is installed when PBS has
    it for this host, otherwise the newest final release of the minor
    (proposal Q4). An install already in place is replaced only once the new
    one has been extracted and probed, so a failed install never leaves the
    old one broken.
    """
    progress = on_progress or (lambda _line: None)
    triple = host_triple()
    if triple is None:
        raise HostPythonError(
            f"there is no python-build-standalone build for this host "
            f"({_platform.system()} {_platform.machine()}). kivyforge builds on "
            "macOS arm64, Linux x86_64 and Windows amd64.\n"
            f"  Fix: install any final CPython {minor}.x yourself.",
            code=diagnostics.HOST_INCAPABLE,
        )
    fetcher = fetcher or _default_fetcher(progress)
    try:
        found = fetcher.find_install_only(minor, triple, prefer=prefer)
    except RuntimeProviderError as exc:
        raise HostPythonError(
            f"could not look up CPython {minor} builds: {exc}\n"
            "  Fix: retry with network access, or install a final CPython "
            f"{minor}.x yourself.",
            code=diagnostics.HOST_PYTHON_FETCH,
        ) from exc
    if found is None:
        raise HostPythonError(
            f"python-build-standalone has no final CPython {minor} build for "
            f"{triple}.\n  Fix: install a final CPython {minor}.x yourself, or "
            "set byte_compile = false.",
            code=diagnostics.BYTECOMPILE_NO_INTERP,
            context={"tool": f"python{minor}"},
        )
    version, asset = found
    progress(f"[bytecompiler] installing CPython {version} ({triple})")
    filename = urllib.parse.unquote(PurePosixPath(asset.url).name)
    cache = cache or ArtifactCache()
    try:
        archive = fetch_artifact(
            name=f"CPython {version} ({triple})",
            sha256=asset.sha256,
            filename=filename,
            url=asset.url,
            cache=cache,
            downloader=downloader,
        )
    except (DownloadError, HashMismatch) as exc:
        raise HostPythonError(
            f"{exc}\n  Fix: retry with network access, or install a final "
            f"CPython {minor}.x yourself.",
            code=diagnostics.HOST_PYTHON_FETCH,
            context={"url": asset.url},
        ) from exc
    interpreter = _install_archive(archive, minor, version, install_root(cache))
    return Installed(version=version, interpreter=interpreter)


def _install_archive(archive: Path, minor: str, version: str, root: Path) -> Path:
    """Extract *archive* beside the install, probe it, then swap it into place."""
    from .pycompile import _probe_version

    root.mkdir(parents=True, exist_ok=True)
    final = root / minor
    with tempfile.TemporaryDirectory(prefix=f".{minor}-", dir=root) as tmp:
        staged = Path(tmp) / "new"
        _safe_extract(archive, staged)
        exe = _interpreter_in(staged, minor)
        probed = _probe_version((str(exe),)) if exe.is_file() else None
        if (
            probed is None
            or f"{probed[0]}.{probed[1]}" != minor
            or probed[3] != "final"
        ):
            raise HostPythonError(
                f"the downloaded CPython {version} did not run as a final "
                f"CPython {minor} ({exe}).\n  Fix: run `kivyforge bytecompiler "
                f"--force` to download it again, or install a final CPython "
                f"{minor}.x yourself."
            )
        old = Path(tmp) / "old"
        if final.exists():
            final.rename(old)
        staged.rename(final)
    return _interpreter_in(final, minor)


def _safe_extract(archive: Path, into: Path) -> None:
    """Extract, rejecting members that would escape *into* (path traversal).

    ``fully_trusted`` keeps the interpreter's permissions and symlinks
    (``bin/python3`` points at ``python3.X``), which the restrictive filters
    would rewrite. The members are checked first, as the desktop backends'
    runtime staging does.
    """
    into.mkdir(parents=True)
    base = into.resolve()
    try:
        with tarfile.open(archive, "r:*") as tf:
            for member in tf.getmembers():
                target = (into / member.name).resolve()
                if not (target == base or base in target.parents):
                    raise HostPythonError(
                        f"unsafe path in {archive.name}: {member.name!r}"
                    )
            tf.extractall(into, filter="fully_trusted")  # noqa: S202 - checked above
    except (tarfile.TarError, OSError) as exc:
        raise HostPythonError(f"failed to extract {archive.name}: {exc}") from exc


def _default_fetcher(progress: Callable[[str], None]) -> InstallFetcher:
    from ..lock.wheelruntime.pbs_github import GithubPbsMetadataFetcher

    return GithubPbsMetadataFetcher(on_progress=progress)
