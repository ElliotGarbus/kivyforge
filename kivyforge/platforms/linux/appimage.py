"""Wrap an AppDir into a single ``.AppImage`` (linux-spec, Step 5).

Acquires two **pinned build tools** through the shared ``kivyforge/artifacts``
download / cache / SHA-256-verify machinery — a static ``appimagetool`` and a
type2 **static-FUSE** runtime file — then runs ``appimagetool --runtime-file``
to produce the output. Embedding a static-FUSE runtime means the *shipped*
AppImage needs no host ``libfuse2`` *package* (it does still use the kernel's
``/dev/fuse`` to self-mount unless run with ``--appimage-extract-and-run``);
invoking appimagetool with ``APPIMAGE_EXTRACT_AND_RUN=1`` means the *build host*
needs no FUSE at all (WSL2 / containers / CI just work).

The pins are constants here (versioned with kivyforge releases): they are build
tools, not app dependencies, so they never enter the app's lockfile.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.download import DownloadError, fetch_artifact
from kivyforge.report.failures import build_tool_failed, spawn_failure

from . import AppDirError

# Pinned appimagetool (AppImage/appimagetool) and type2 static-FUSE runtime
# (AppImage/type2-runtime). Per-arch; aarch64 is a Raspberry Pi *target*
# (cross-built from x86_64). The *tool* that runs at package time is the
# host-arch appimagetool; the *runtime* embedded with --runtime-file is the
# target's. SHA-256s were hashed from the release assets on 2026-09-17.
APPIMAGETOOL_VERSION = "1.9.1"
TYPE2_RUNTIME_VERSION = "20251108"

_APPIMAGETOOL = {
    "x86_64": (
        "https://github.com/AppImage/appimagetool/releases/download/"
        f"{APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage",
        "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0",
    ),
    "aarch64": (
        "https://github.com/AppImage/appimagetool/releases/download/"
        f"{APPIMAGETOOL_VERSION}/appimagetool-aarch64.AppImage",
        "f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158",
    ),
}

_TYPE2_RUNTIME = {
    "x86_64": (
        "https://github.com/AppImage/type2-runtime/releases/download/"
        f"{TYPE2_RUNTIME_VERSION}/runtime-x86_64",
        "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d",
    ),
    "aarch64": (
        "https://github.com/AppImage/type2-runtime/releases/download/"
        f"{TYPE2_RUNTIME_VERSION}/runtime-aarch64",
        "00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444",
    ),
}


def appimagetool_asset(arch: str) -> tuple[str, str]:
    """The (url, sha256) for the pinned appimagetool for *arch*."""
    try:
        return _APPIMAGETOOL[arch]
    except KeyError:
        raise AppDirError(
            f"no pinned appimagetool for arch {arch!r} "
            f"(have: {', '.join(sorted(_APPIMAGETOOL))})."
        ) from None


def type2_runtime_asset(arch: str) -> tuple[str, str]:
    """The (url, sha256) for the pinned type2 static-FUSE runtime for *arch*."""
    try:
        return _TYPE2_RUNTIME[arch]
    except KeyError:
        raise AppDirError(
            f"no pinned type2 runtime for arch {arch!r} "
            f"(have: {', '.join(sorted(_TYPE2_RUNTIME))})."
        ) from None


def build_appimage(
    appdir: Path,
    output: Path,
    arch: str,
    *,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
    echo=lambda *a: None,
) -> Path:
    """Package *appdir* into an ``.AppImage`` at *output*; return *output*.

    ``appimagetool`` is a host binary: a cross-build from x86_64 onto aarch64
    still runs the x86_64 tool and embeds the aarch64 type2 runtime via
    ``--runtime-file``. Using the target-arch appimagetool would fail to exec.
    """
    cache = cache or ArtifactCache()
    host_arch = _host_appimagetool_arch()
    tool = _acquire(
        appimagetool_asset(host_arch),
        f"appimagetool-{APPIMAGETOOL_VERSION}-{host_arch}.AppImage",
        "appimagetool",
        project_root,
        cache,
        no_cache,
    )
    runtime = _acquire(
        type2_runtime_asset(arch),
        f"appimage-runtime-{TYPE2_RUNTIME_VERSION}-{arch}",
        "type2 runtime",
        project_root,
        cache,
        no_cache,
    )
    # appimagetool must be executable; run it from a copy so the
    # content-addressed cache entry is never mutated.
    tool = _executable_copy(tool, cache)

    output.parent.mkdir(parents=True, exist_ok=True)
    # Emit to a temp file and swap it in only on success, so a tool failure (or
    # crash) leaves any previous .AppImage intact rather than deleting it up
    # front — the write-in-place guarantee the other platforms also uphold.
    tmp_out = output.parent / f".{output.name}.tmp-{os.getpid()}"
    tmp_out.unlink(missing_ok=True)

    echo(f"Packaging {output.name} with appimagetool {APPIMAGETOOL_VERSION} ...")
    env = {
        **os.environ,
        "ARCH": arch,
        # No FUSE on the build host: appimagetool extracts + runs itself.
        "APPIMAGE_EXTRACT_AND_RUN": "1",
    }
    cmd = [
        str(tool),
        "--runtime-file",
        str(runtime),
        str(appdir),
        str(tmp_out),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL
        )
    except OSError as exc:
        tmp_out.unlink(missing_ok=True)
        raise AppDirError(
            f"failed to run appimagetool: {exc}", **spawn_failure("appimagetool", exc)
        ) from exc
    if proc.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        # The transcript is build log: both streams go to progress, and the
        # error stays a summary a --json consumer can read without a log in it.
        for stream in (proc.stdout, proc.stderr):
            if stream and stream.strip():
                echo(stream.rstrip())
        raise AppDirError(
            f"appimagetool failed to build the AppImage (exit {proc.returncode}); "
            "its output is above.",
            **build_tool_failed("appimagetool", "package"),
        )
    tmp_out.chmod(0o755)
    os.replace(tmp_out, output)
    return output


def _acquire(
    asset: tuple[str, str],
    filename: str,
    label: str,
    project_root: Path,
    cache: ArtifactCache,
    no_cache: bool,
) -> Path:
    url, sha256 = asset
    try:
        return fetch_artifact(
            name=label,
            sha256=sha256,
            filename=filename,
            url=url,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )
    except DownloadError as exc:
        raise AppDirError(str(exc)) from exc


def _host_appimagetool_arch() -> str:
    """The arch of the appimagetool this host can actually exec."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    raise AppDirError(
        f"no pinned appimagetool for this host arch ({machine}); "
        "need x86_64 or aarch64."
    )


def _executable_copy(tool: Path, cache: ArtifactCache) -> Path:
    exec_copy = cache.root.parent / "bin" / tool.name
    exec_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tool, exec_copy)
    exec_copy.chmod(0o755)
    return exec_copy
