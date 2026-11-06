"""The pinned host CPython that byte-compiles, installed from the lock.

iOS and Android, and a Linux ``aarch64`` target built on x86_64, write their
``.pyc`` with a CPython that runs on the build machine. ``lock`` pins one
python-build-standalone (PBS) build of it per host
(:mod:`kivyforge.lock.host_python`); this module turns this host's entry into
a runnable interpreter, and nothing else is ever used to compile those
platforms (``docs/design/dev/host-python-download-proposal.md``, Q5).

Two states on disk. The **archive** is a pinned artifact in the artifact cache,
fetched and verified like any other. The **install** is that archive extracted
to ``<cache>/host-python/<sha256>/``, complete only once its
``.kivyforge-complete`` marker exists, written after the interpreter has
answered a probe. A directory without the marker, or whose interpreter no
longer runs, is rebuilt from the archive. Extracting a cached archive needs no
network, so it is allowed with downloads off.

Two environment variables, both for the machine rather than the project, and
both for this interpreter only (runtimes and wheels download as before):

- ``KIVYFORGE_HOST_PYTHON_DOWNLOADS``: ``automatic`` (default) or ``never``.
- ``KIVYFORGE_HOST_PYTHON_MIRROR``: replaces the PBS release-download base in
  a pinned URL; the pinned SHA-256 still verifies what it serves.
"""

from __future__ import annotations

import os
import platform as _platform
import tarfile
import tempfile
import time
import urllib.parse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..artifacts.cache import ArtifactCache
from ..artifacts.download import Downloader, DownloadError, fetch_artifact
from ..artifacts.verify import HashMismatch
from ..lock import host_python as hp
from ..report import diagnostics, exit_codes
from ..report.failures import Classification, ClassifiedError, os_failure

DOWNLOADS_VAR = "KIVYFORGE_HOST_PYTHON_DOWNLOADS"
MIRROR_VAR = "KIVYFORGE_HOST_PYTHON_MIRROR"
PBS_DOWNLOAD_BASE = (
    "https://github.com/astral-sh/python-build-standalone/releases/download"
)
MARKER = ".kivyforge-complete"
#: How long a build waits for another one installing the same pin.
LOCK_TIMEOUT_S = 600.0

#: The three build hosts kivyforge supports (``docs/guides/get-started/hosts.md``),
#: keyed as ``(platform.system(), host_machine())``.
HOST_TRIPLES = {
    ("Darwin", "arm64"): hp.MACOS_ARM64,
    ("Linux", "x86_64"): hp.LINUX_X86_64,
    ("Windows", "amd64"): hp.WINDOWS_AMD64,
}


class HostPythonError(ClassifiedError):
    """The pinned host CPython could not be provided. Exit 3 unless set."""

    exit_code = exit_codes.ENVIRONMENT_ERROR


@dataclass(frozen=True)
class Unavailable:
    """Why this host has no compiler, worded for every call site and ``doctor``.

    Each backend chooses what to do with it: ``byte_compile = "release"``
    ships source with a warning, ``true`` fails with *classification*.
    """

    headline: str
    #: The detail and the ``Fix:`` line.
    lines: tuple[str, ...]
    classification: Classification

    @property
    def code(self) -> str:
        return self.classification.get("code", diagnostics.BYTECOMPILE_NO_INTERP)

    def detail(self, indent: str = "  ") -> str:
        return "\n".join(indent + line for line in self.lines)

    def required(self, table: str) -> str:
        """The message for ``byte_compile = true``, which fails the build."""
        return f"[{table}].byte_compile = true, but {self.headline}.\n{self.detail()}"


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
    removes them with the archives they came from."""
    return (cache or ArtifactCache()).root / "host-python"


def downloads_allowed() -> bool:
    """``KIVYFORGE_HOST_PYTHON_DOWNLOADS``, read; an unknown value is exit 1."""
    value = os.environ.get(DOWNLOADS_VAR, "").strip().lower() or "automatic"
    if value not in ("automatic", "never"):
        raise HostPythonError(
            f"{DOWNLOADS_VAR}={value!r} is not valid.\n"
            "Fix: set it to `automatic` or `never`, or unset it.",
            exit_code=exit_codes.CONFIG_ERROR,
        )
    return value == "automatic"


def download_url(entry: hp.HostPython) -> str:
    """The pinned URL, with ``KIVYFORGE_HOST_PYTHON_MIRROR`` applied."""
    assert entry.url is not None
    mirror = os.environ.get(MIRROR_VAR, "").strip().rstrip("/")
    if mirror and entry.url.startswith(PBS_DOWNLOAD_BASE + "/"):
        return mirror + entry.url[len(PBS_DOWNLOAD_BASE) :]
    return entry.url


def archive_filename(entry: hp.HostPython) -> str:
    assert entry.url is not None
    return urllib.parse.unquote(PurePosixPath(entry.url).name)


def install_dir(entry: hp.HostPython, cache: ArtifactCache | None = None) -> Path:
    """The install for *entry*, keyed by its full SHA-256."""
    assert entry.sha256 is not None
    return install_root(cache) / entry.sha256


def interpreter_in(directory: Path, minor: str) -> Path:
    """PBS ``install_only`` layout: ``python/python.exe`` on Windows,
    ``python/bin/python3.X`` everywhere else."""
    if _platform.system() == "Windows":
        return directory / "python" / "python.exe"
    return directory / "python" / "bin" / f"python{minor}"


def installed(entry: hp.HostPython, cache: ArtifactCache | None = None) -> Path | None:
    """The interpreter if *entry* is installed and complete, else ``None``."""
    directory = install_dir(entry, cache)
    exe = interpreter_in(directory, entry.minor)
    if (directory / MARKER).is_file() and exe.is_file():
        return exe
    return None


def archive_cached(entry: hp.HostPython, cache: ArtifactCache | None = None) -> bool:
    assert entry.sha256 is not None
    store = cache or ArtifactCache()
    return store.get(entry.sha256, archive_filename(entry)) is not None


def compiler_for(
    entries: tuple[hp.HostPython, ...] | None,
    *,
    platform: str,
    python_version: str,
    cache: ArtifactCache | None = None,
    downloader: Downloader | None = None,
    no_cache: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[str, ...] | Unavailable:
    """The argv that compiles *platform*'s payload on this host, or why not.

    *entries* is the lock's ``[[tool.kivyforge.host_python]]`` table. Only this
    host's ``pinned`` entry ever compiles; with none, the answer says why, so
    the caller can ship source or fail. A disk or permission failure, and an
    invalid setting, raise instead: they would break the rest of the build too.
    """
    progress = on_progress or (lambda _line: None)
    minor = hp.minor_of(python_version)
    lockfile = f"pylock.{platform}.toml"
    relock = f"kivyforge lock -p {platform}"
    triple = host_triple()
    # The lock first: a lock without the table is incomplete on every host.
    if entries is not None and triple is None:
        return _no_interp(
            f"this host ({_platform.system()} {_platform.machine()}) has no "
            "python-build-standalone build to compile with",
            "kivyforge builds on macOS arm64, Linux x86_64 and Windows amd64.",
            minor,
        )
    entry = hp.entry_for(entries, triple or "")
    if entries is None or entry is None or entry.state == hp.UNRESOLVED_OFFLINE:
        why = (
            "it predates the host CPython pin"
            if entries is None
            else f"it has no host CPython for {triple}"
            if entry is None
            else f"its host CPython for {triple} was locked offline"
        )
        return Unavailable(
            headline=f"{lockfile} has no host CPython to compile with ({why})",
            lines=(
                f"Fix: run `{relock}`; it adds the host CPython and keeps every "
                "other pin. Or set byte_compile = false.",
            ),
            classification={
                "code": diagnostics.LOCK_INCOMPLETE,
                "exit_code": exit_codes.LOCK_DRIFT,
            },
        )
    if entry.state == hp.NO_BUILD:
        return _no_interp(
            f"python-build-standalone had no final CPython {entry.minor} build "
            f"for {triple} when the lock was written",
            f"Fix: once one is published, run `{relock}`. Or set byte_compile = false.",
            entry.minor,
        )
    allowed = downloads_allowed()
    if no_cache and not allowed:
        raise HostPythonError(
            f"--no-cache asks to download the host CPython again, and "
            f"{DOWNLOADS_VAR}=never forbids downloading it.\n"
            "Fix: drop --no-cache, or unset the variable.",
            exit_code=exit_codes.CONFIG_ERROR,
        )
    try:
        exe = _ensure(
            entry,
            cache=cache or ArtifactCache(),
            downloader=downloader,
            no_cache=no_cache,
            allowed=allowed,
            progress=progress,
        )
    except _NotCached:
        return _no_interp(
            f"the locked host CPython {entry.version} ({triple}) isn't in the "
            f"cache, and {DOWNLOADS_VAR}=never",
            f"Fix: run `kivyforge upgrade -p {platform}` on a machine with network "
            f"access, unset {DOWNLOADS_VAR}, or set byte_compile = false.",
            entry.minor,
        )
    except HostPythonError as exc:
        lines = str(exc).splitlines()
        return Unavailable(
            headline=lines[0],
            lines=tuple(line.strip() for line in lines[1:]),
            classification={"code": exc.code, "exit_code": exc.exit_code},
        )
    except OSError as exc:
        raise HostPythonError(
            os_failure("install the host CPython", exc),
            code=diagnostics.UNSPECIFIED,
            exit_code=exit_codes.CONFIG_ERROR,
        ) from exc
    return (str(exe),)


def pinned_compiler(
    entries: tuple[hp.HostPython, ...] | None,
    *,
    platform: str,
    python_version: str,
    byte_compile: bool | str,
    table: str,
    what: str,
    error: type[ClassifiedError],
    echo: Callable[[str], None],
    note: Callable[..., None],
    context: dict[str, str | None] | None = None,
    no_cache: bool = False,
    cache: ArtifactCache | None = None,
    downloader: Downloader | None = None,
) -> tuple[str, ...] | None:
    """:func:`compiler_for`, with the setting's policy applied: one copy for
    every call site.

    Returns the argv to compile with, or ``None`` to ship source. With
    ``byte_compile = true`` a missing compiler raises *error*, carrying the
    reason's classification; with ``"release"`` it prints the reason and
    records a warning note (*what* names the payload, for example
    ``" app sources"``). A failure that would break the build anyway (a disk
    error, an invalid setting) raises *error* whatever the setting.
    """
    try:
        compiler = compiler_for(
            entries,
            platform=platform,
            python_version=python_version,
            cache=cache,
            downloader=downloader,
            no_cache=no_cache,
            on_progress=echo,
        )
    except HostPythonError as exc:
        raise error(str(exc), code=exc.code, exit_code=exc.exit_code) from exc
    if not isinstance(compiler, Unavailable):
        return compiler
    if byte_compile is True:
        raise error(compiler.required(table), **compiler.classification)
    echo(f"[stage] not byte-compiling{what}: {compiler.headline}.\n{compiler.detail()}")
    if context:
        note(compiler.code, f"not byte-compiling{what}: {compiler.headline}.", context)
    else:
        note(compiler.code, f"not byte-compiling{what}: {compiler.headline}.")
    return None


def ensure_archive(
    entry: hp.HostPython,
    *,
    cache: ArtifactCache | None = None,
    downloader: Downloader | None = None,
    no_cache: bool = False,
) -> Path:
    """Fetch *entry*'s archive into the cache, for ``kivyforge upgrade``.

    The first build extracts it, offline if need be. Raises
    :class:`HostPythonError`.
    """
    return _fetch(entry, cache or ArtifactCache(), downloader, no_cache=no_cache)


class _NotCached(Exception):
    """Downloads are off and the pinned archive isn't in the cache."""


def _ensure(
    entry: hp.HostPython,
    *,
    cache: ArtifactCache,
    downloader: Downloader | None,
    no_cache: bool,
    allowed: bool,
    progress: Callable[[str], None],
) -> Path:
    """Return the installed interpreter, installing it under a per-pin lock."""
    if not no_cache:
        exe = installed(entry, cache)
        if exe is not None and _runs_as(exe, entry.minor):
            return exe
    if not allowed and (no_cache or not archive_cached(entry, cache)):
        raise _NotCached
    root = install_root(cache)
    root.mkdir(parents=True, exist_ok=True)
    assert entry.sha256 is not None
    with _install_lock(root / f"{entry.sha256}.lock", entry):
        # Another build may have finished it while this one waited.
        if not no_cache:
            exe = installed(entry, cache)
            if exe is not None and _runs_as(exe, entry.minor):
                return exe
        progress(
            f"[stage] host CPython {entry.version} ({entry.triple}): "
            "installing from the lock"
        )
        archive = _fetch(entry, cache, downloader, no_cache=no_cache)
        return _install_archive(archive, entry, install_dir(entry, cache))


def _fetch(
    entry: hp.HostPython,
    cache: ArtifactCache,
    downloader: Downloader | None,
    *,
    no_cache: bool,
) -> Path:
    url = download_url(entry)
    assert entry.sha256 is not None
    mirror = os.environ.get(MIRROR_VAR, "").strip()
    try:
        return fetch_artifact(
            name=f"host CPython {entry.version} ({entry.triple})",
            sha256=entry.sha256,
            filename=archive_filename(entry),
            url=url,
            cache=cache,
            downloader=downloader,
            no_cache=no_cache,
        )
    except HashMismatch as exc:
        # A retry rarely helps: the bytes served are not the bytes locked.
        raise HostPythonError(
            f"the host CPython archive doesn't match the lock's SHA-256 ({url})\n"
            + (
                f"Fix: check that {MIRROR_VAR} serves the pinned file unchanged; "
                if mirror
                else "Fix: "
            )
            + "if the release was replaced, re-lock with `kivyforge lock --update`; "
            "otherwise report it.",
            code=diagnostics.HOST_PYTHON_FETCH,
            context={"url": url},
        ) from exc
    except DownloadError as exc:
        raise HostPythonError(
            f"could not download the host CPython: {exc}\n"
            "Fix: retry with network access"
            + (f", or check {MIRROR_VAR}" if mirror else "")
            + ".",
            code=diagnostics.HOST_PYTHON_FETCH,
            context={"url": url},
        ) from exc


def _install_archive(archive: Path, entry: hp.HostPython, final: Path) -> Path:
    """Extract beside *final*, probe, mark complete, then swap into place."""
    parent = final.parent
    with tempfile.TemporaryDirectory(prefix=f".{final.name[:12]}-", dir=parent) as tmp:
        staged = Path(tmp) / "new"
        _safe_extract(archive, staged)
        exe = interpreter_in(staged, entry.minor)
        if not (exe.is_file() and _runs_as(exe, entry.minor)):
            raise HostPythonError(
                f"the host CPython {entry.version} from the lock did not run as a "
                f"final CPython {entry.minor} after extracting it\n"
                "Fix: retry; if it persists, run `kivyforge clean --cache`.",
                code=diagnostics.BYTECOMPILE_NO_INTERP,
            )
        (staged / MARKER).write_text(f"{entry.sha256}\n", encoding="utf-8")
        old = Path(tmp) / "old"
        if final.exists():
            final.rename(old)
        staged.rename(final)
    return interpreter_in(final, entry.minor)


def _runs_as(exe: Path, minor: str) -> bool:
    from .pycompile import _probe_version

    probed = _probe_version((str(exe),))
    return (
        probed is not None
        and f"{probed[0]}.{probed[1]}" == minor
        and probed[3] == "final"
    )


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
                        f"unsafe path in {archive.name}: {member.name!r}\n"
                        "Fix: report it; the archive matched the lock's hash.",
                        code=diagnostics.BYTECOMPILE_NO_INTERP,
                    )
            tf.extractall(into, filter="fully_trusted")  # noqa: S202 - checked above
    except tarfile.TarError as exc:
        raise HostPythonError(
            f"failed to extract {archive.name}: {exc}\n"
            "Fix: retry; if it persists, run `kivyforge clean --cache`.",
            code=diagnostics.BYTECOMPILE_NO_INTERP,
        ) from exc


@contextmanager
def _install_lock(path: Path, entry: hp.HostPython) -> Iterator[None]:
    """An exclusive lock on *path* for one pin's install, across processes.

    An OS lock (``fcntl``/``msvcrt``), so a build that dies releases it.
    Waits up to :data:`LOCK_TIMEOUT_S` for another build installing the same
    pin, then gives up rather than racing it.
    """
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    with open(path, "a+b") as handle:
        while not _try_lock(handle):
            if time.monotonic() > deadline:
                raise HostPythonError(
                    f"another build has been installing the host CPython "
                    f"{entry.version} for over {int(LOCK_TIMEOUT_S)} s ({path})\n"
                    "Fix: retry once it finishes.",
                    code=diagnostics.HOST_PYTHON_FETCH,
                )
            time.sleep(0.5)
        try:
            yield
        finally:
            _unlock(handle)


def _try_lock(handle) -> bool:
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # pyright: ignore[reportAttributeAccessIssue]
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # pyright: ignore[reportAttributeAccessIssue]
    except BlockingIOError:
        return False
    return True


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # pyright: ignore[reportAttributeAccessIssue]
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # pyright: ignore[reportAttributeAccessIssue]


def _no_interp(headline: str, fix: str, minor: str) -> Unavailable:
    return Unavailable(
        headline=headline,
        lines=(fix,),
        classification={
            "code": diagnostics.BYTECOMPILE_NO_INTERP,
            "exit_code": exit_codes.ENVIRONMENT_ERROR,
            "context": {"tool": f"python{minor}"},
        },
    )
