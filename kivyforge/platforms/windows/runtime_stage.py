"""Stage the bundled CPython runtime into the onedir ``python\\`` prefix.

Consumes the provider-agnostic runtime pin from ``pylock.windows.toml`` (a single
``amd64`` artifact this phase), fetches + SHA-256-verifies its archive, extracts
it, and materializes the **whole** python-build-standalone prefix at
``<bundle>\\python`` — never flattened or pruned. The Windows PBS layout keeps
``python.exe`` at the prefix root alongside ``python3xx.dll``, with ``DLLs\\``,
``Lib\\``, ``Scripts\\`` etc. beneath it; the launcher points ``PYTHONHOME`` here.

VC++ runtime (Phase 0 finding — resolved): the PBS ``install_only`` Windows
archive ships ``vcruntime140.dll`` and ``vcruntime140_1.dll`` next to
``python.exe`` but **not** ``msvcp140.dll`` (the C++ runtime some native deps
need). :func:`ensure_vc_runtime` verifies the core CPython DLLs are present
(a no-op for stock PBS, with an app-local fallback should a future PBS build
drop them) and best-effort places ``msvcp140.dll`` app-local when the runtime
itself omits it — never relying on a system-installed VCRedist, which is the
classic clean-machine failure.
"""

from __future__ import annotations

import os
import shutil
import struct
import tarfile
import tempfile
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.lock.wheelruntime.model import PythonRuntime
from kivyforge.lock.wheelruntime.runtime import (
    RuntimeProviderError,
    normalized_runtime_root,
)

from . import WindowsBundleError
from .petools import machine_for_arch, read_pe_machine

# CPython itself links these; without them python.exe will not start. PBS ships
# them, so the check is normally a no-op.
CORE_VC_RUNTIME = ("vcruntime140.dll", "vcruntime140_1.dll")
# The C++ runtime; PBS does NOT ship it. Native deps (SDL, codecs) may need it.
# Placed app-local best-effort when neither the runtime nor a dep provides it.
CXX_VC_RUNTIME = "msvcp140.dll"

# The host location the redistributable VC++ runtime DLLs live in, used only as
# a fallback source when the runtime archive omits one.
DEFAULT_SYSTEM_DIR = Path(r"C:\Windows\System32")


def stage_runtime(
    runtime: PythonRuntime,
    arch: str,
    home: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
    system_dir: Path | None = None,
) -> Path:
    """Materialize the whole runtime prefix for *arch* at *home*; return *home*.

    *home* is the final CPython prefix (``<bundle>\\python``). It is emptied and
    recreated, then the conditional VC-runtime step runs.
    """
    cache = cache or ArtifactCache()
    artifact = runtime.artifact_for(arch)
    if artifact is None:
        raise WindowsBundleError(
            f"the lock has no {arch} runtime artifact; re-run "
            f"`kivyforge lock -p windows` (locked archs: "
            f"{', '.join(a.arch for a in runtime.artifacts)})."
        )

    tmp = Path(tempfile.mkdtemp(prefix="kivy-runtime-"))
    try:
        archive = _fetch(artifact, arch, project_root, cache, no_cache)
        extracted = _extract(archive, tmp, runtime.provider)
        if home.exists():
            shutil.rmtree(home)
        home.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(extracted, home, symlinks=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ensure_vc_runtime(home, arch=arch, system_dir=system_dir)
    return home


def ensure_vc_runtime(
    home: Path, *, arch: str = "amd64", system_dir: Path | None = None
) -> tuple[str, ...]:
    """Guarantee the VC++ runtime DLLs the prefix needs sit next to python.exe.

    Returns the DLLs this step placed app-local (empty when the runtime already
    provides everything, the common PBS case). Raises if a *core* CPython DLL is
    missing and cannot be sourced — python.exe could not start otherwise.

    Any DLL taken from the host fallback is checked against *arch*: under a
    32-bit Python process ``C:\\Windows\\System32`` is WOW64-redirected to the
    x86 ``SysWOW64``, so a naive copy could put an x86 runtime into an amd64
    bundle. Mismatched host DLLs are refused (core) or skipped (msvcp140).
    """
    source = system_dir if system_dir is not None else _default_system_dir()
    placed: list[str] = []

    for dll in CORE_VC_RUNTIME:
        if (home / dll).is_file():
            continue
        if _copy_from(source, dll, home, arch):
            placed.append(dll)
        else:
            raise WindowsBundleError(
                f"the staged runtime is missing {dll} and no {arch} copy was "
                f"found in {source}. python.exe cannot start without the VC++ "
                "runtime; the runtime archive or a matching-architecture VC++ "
                "redistributable is required."
            )

    # Best-effort: only place the C++ runtime app-local when the runtime omits
    # it. A dep wheel may still ship it into site-packages; that is fine.
    if not (home / CXX_VC_RUNTIME).is_file() and _copy_from(
        source, CXX_VC_RUNTIME, home, arch
    ):
        placed.append(CXX_VC_RUNTIME)

    return tuple(placed)


def _copy_from(source: Path, name: str, home: Path, arch: str) -> bool:
    """Copy *source*/*name* to *home* iff it matches *arch*; return if copied.

    A host DLL whose PE machine type does not match the target architecture is
    treated as absent — never copied — so a WOW64-redirected (x86) fallback or
    any other wrong-arch source cannot poison the bundle.
    """
    candidate = source / name
    if not candidate.is_file():
        return False
    expected = machine_for_arch(arch)
    machine = read_pe_machine(candidate)
    if expected is not None and machine is not None and machine != expected:
        return False
    shutil.copy2(candidate, home / name)
    return True


def _default_system_dir() -> Path:
    """The host source for VC-runtime fallbacks, WOW64-redirection aware.

    A 32-bit Python process has ``System32`` file-system-redirected to the x86
    ``SysWOW64``; the ``Sysnative`` pseudo-directory reaches the real 64-bit
    ``System32`` from such a process. On a 64-bit interpreter ``System32`` is
    already correct.
    """
    if struct.calcsize("P") == 4:  # 32-bit interpreter
        root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        sysnative = root / "Sysnative"
        if sysnative.is_dir():
            return sysnative
    return DEFAULT_SYSTEM_DIR


def _fetch(artifact, arch, project_root, cache, no_cache) -> Path:
    filename = artifact.url.rsplit("/", 1)[-1] or f"python-{arch}.tar.gz"
    try:
        return fetch_artifact(
            name=f"python runtime ({arch})",
            sha256=artifact.sha256,
            filename=filename,
            url=artifact.url,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )
    except DownloadError as exc:
        raise WindowsBundleError(str(exc)) from exc


def _extract(archive: Path, into: Path, provider: str) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:*") as tf:
            _safe_extractall(tf, into)
    except (tarfile.TarError, OSError) as exc:
        raise WindowsBundleError(f"failed to extract {archive.name}: {exc}") from exc
    try:
        return normalized_runtime_root(provider, into)
    except RuntimeProviderError as exc:
        raise WindowsBundleError(f"{archive.name}: {exc}") from exc


def _safe_extractall(tf: tarfile.TarFile, into: Path) -> None:
    """Extract, rejecting members that would escape *into*.

    The explicit name check gives a clear message for the common ``../`` case;
    ``filter="data"`` then provides the protection the name check cannot — it
    validates symlink/hardlink *targets* (a safely named link pointing outside,
    written through by a later member, would otherwise escape) and strips device
    nodes and other special files. ``filter="fully_trusted"`` restored links
    verbatim and did none of this.
    """
    base = into.resolve()
    for member in tf.getmembers():
        target = (into / member.name).resolve()
        if not (target == base or base in target.parents):
            raise WindowsBundleError(f"unsafe path in archive: {member.name!r}")
    try:
        tf.extractall(into, filter="data")  # noqa: S202 — hardened filter (validates links)
    except tarfile.FilterError as exc:
        raise WindowsBundleError(f"unsafe member in archive: {exc}") from exc
