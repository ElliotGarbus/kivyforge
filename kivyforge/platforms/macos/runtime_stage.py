"""Acquire + normalize the bundled CPython runtime for the ``.app``.

Consumes the provider-agnostic runtime pin from ``pylock.macos.toml`` (per-arch
URL + SHA-256), fetches + verifies each requested arch's archive, extracts it,
and produces a single **canonical relocatable CPython tree**: for a thin build
that is the one arch as-is; for universal2 it is the first arch's tree with every
Mach-O ``lipo``-merged with its counterpart(s) from the other arch(es). Nothing
downstream (launcher, bundler, signing) knows or cares which provider produced
it — the whole point of the runtime-provider seam.
"""

from __future__ import annotations

import shutil
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

from . import AppBundleError
from .machotools import is_macho, lipo_create


def stage_runtime(
    runtime: PythonRuntime,
    archs: tuple[str, ...],
    home: Path,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
) -> Path:
    """Materialize the runtime for *archs* at *home*; return *home*.

    *home* is the final CPython home directory (whose ``bin/python3`` the
    launcher execs). It is emptied and recreated. Deliberately placed under the
    bundle's ``Resources/`` (not ``Frameworks/``): a unix-prefix Python tree
    under ``Frameworks/`` trips ``codesign``'s framework auto-discovery on
    non-framework subdirs (e.g. ``lib/tk*``), whereas ``Resources`` content is
    sealed as data and the Mach-O files are signed individually.
    """
    if not archs:
        raise AppBundleError("stage_runtime requires at least one arch")
    cache = cache or ArtifactCache()

    per_arch: dict[str, Path] = {}
    tmp = Path(tempfile.mkdtemp(prefix="kivy-runtime-"))
    try:
        for arch in archs:
            artifact = runtime.artifact_for(arch)
            if artifact is None:
                raise AppBundleError(
                    f"the lock has no {arch} runtime artifact; re-run "
                    f"`kivyforge lock -p macos` (locked archs: "
                    f"{', '.join(a.arch for a in runtime.artifacts)})."
                )
            archive = _fetch(artifact, arch, project_root, cache, no_cache)
            per_arch[arch] = _extract(archive, tmp / arch, runtime.provider)

        if home.exists():
            shutil.rmtree(home)
        home.parent.mkdir(parents=True, exist_ok=True)

        base_arch = archs[0]
        shutil.copytree(per_arch[base_arch], home, symlinks=True)
        if len(archs) > 1:
            _merge_into(home, [per_arch[a] for a in archs[1:]])
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
        raise AppBundleError(str(exc)) from exc


def _extract(archive: Path, into: Path, provider: str) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, "r:*") as tf:
            _safe_extractall(tf, into)
    except (tarfile.TarError, OSError) as exc:
        raise AppBundleError(f"failed to extract {archive.name}: {exc}") from exc
    try:
        return normalized_runtime_root(provider, into)
    except RuntimeProviderError as exc:
        raise AppBundleError(f"{archive.name}: {exc}") from exc


def _safe_extractall(tf: tarfile.TarFile, into: Path) -> None:
    """Extract, rejecting members that would escape *into* (path traversal)."""
    base = into.resolve()
    for member in tf.getmembers():
        target = (into / member.name).resolve()
        if not (target == base or base in target.parents):
            raise AppBundleError(f"unsafe path in archive: {member.name!r}")
    tf.extractall(into)  # noqa: S202 — members validated just above


def _merge_into(base: Path, others: list[Path]) -> None:
    """lipo-merge every Mach-O in *base* with its counterpart(s) from *others*."""
    for path in sorted(base.rglob("*")):
        if not is_macho(path):
            continue
        rel = path.relative_to(base)
        inputs = [path]
        for other in others:
            counterpart = other / rel
            if is_macho(counterpart):
                inputs.append(counterpart)
        if len(inputs) < 2:
            # Present in the base arch only (rare); leave it thin.
            continue
        merged = path.with_suffix(path.suffix + ".universal")
        lipo_create(inputs, merged)
        merged.replace(path)
