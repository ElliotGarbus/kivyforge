"""Acquire the bundled CPython runtime for the AppDir (linux-spec).

Consumes the provider-agnostic runtime pin from ``pylock.linux.toml`` (the
single ``x86_64`` artifact this phase — one arch per AppImage), fetches +
verifies its archive, extracts it, and materializes the relocatable CPython tree
at ``usr/python``. The extracted archive is normalized to its canonical root via
``normalized_runtime_root`` keyed on the lock's recorded ``provider`` — staging
never hard-codes a provider's archive internals (spec 07). The PBS linux-gnu
``install_only`` archive is the same unix-prefix layout as the darwin ones and
uses ``$ORIGIN``-relative rpaths, so it is relocatable as-shipped — no patchelf
pass, and (unlike macOS) no ``lipo`` merge, since Linux ships one arch per
AppImage.
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from pathlib import Path

from ..artifacts.cache import ArtifactCache
from ..artifacts.download import DownloadError, fetch_artifact
from ..lock.wheelruntime.model import PythonRuntime
from ..lock.wheelruntime.runtime import (
    RuntimeProviderError,
    normalized_runtime_root,
)
from . import AppDirError


def stage_runtime(
    runtime: PythonRuntime,
    arch: str,
    home: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
) -> Path:
    """Materialize the runtime for *arch* at *home*; return *home*.

    *home* is the final CPython home directory (whose ``bin/python3`` ``AppRun``
    execs). It is emptied and recreated.
    """
    cache = cache or ArtifactCache()
    artifact = runtime.artifact_for(arch)
    if artifact is None:
        raise AppDirError(
            f"the lock has no {arch} runtime artifact; re-run "
            f"`kivyforge lock -p linux` (locked archs: "
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
        return home
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
        raise AppDirError(str(exc)) from exc


def _extract(archive: Path, into: Path, provider: str) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:*") as tf:
            _safe_extractall(tf, into)
    except (tarfile.TarError, OSError) as exc:
        raise AppDirError(f"failed to extract {archive.name}: {exc}") from exc
    try:
        return normalized_runtime_root(provider, into)
    except RuntimeProviderError as exc:
        raise AppDirError(f"{archive.name}: {exc}") from exc


def _safe_extractall(tf: tarfile.TarFile, into: Path) -> None:
    """Extract, rejecting members that would escape *into* (path traversal)."""
    base = into.resolve()
    for member in tf.getmembers():
        target = (into / member.name).resolve()
        if not (target == base or base in target.parents):
            raise AppDirError(f"unsafe path in archive: {member.name!r}")
    tf.extractall(into)  # noqa: S202 — members validated just above
