"""Extract the python.org Android runtime per ABI (android/03 channel 2).

The tarball layout (loadmodel findings §runtime-package facts):
``README.md``, ``android-env.sh``, ``android.py``, ``prefix/``, ``testbed/``.
Only ``prefix/`` matters to the build: ``prefix/lib`` feeds ``jniLibs`` (via
``stage.jnilibs.stage_runtime_libs``) and ``prefix/lib/pythonX.Y`` (minus
``lib-dynload``) feeds the asset bundle.
"""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path


class RuntimeStageError(Exception):
    pass


def extract_runtime(tarball: Path, dest: Path) -> Path:
    """Extract ``tarball`` into ``dest`` and return the ``prefix`` directory.

    Idempotent per destination: an existing extraction is replaced (the
    tarball's SHA-256 was verified by the collect step before this runs).
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(dest, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeStageError(
            f"could not extract the python.org runtime {tarball.name}: {exc}"
        ) from exc
    prefix = dest / "prefix"
    if not prefix.is_dir():
        # Tolerate a single wrapping directory around the documented layout.
        candidates = [p / "prefix" for p in dest.iterdir() if p.is_dir()]
        matches = [c for c in candidates if c.is_dir()]
        if len(matches) == 1:
            prefix = matches[0]
        else:
            raise RuntimeStageError(
                f"{tarball.name} does not contain the documented prefix/ "
                f"layout (android/03 channel 2); found: "
                f"{[p.name for p in dest.iterdir()]}"
            )
    return prefix


def stdlib_dir(prefix: Path, python_stem: str) -> Path:
    """``prefix`` -> the pure-Python stdlib tree (``lib/pythonX.Y``)."""
    lib = prefix / "lib" / python_stem
    if not lib.is_dir():
        raise RuntimeStageError(
            f"runtime prefix has no stdlib at {lib}; the embeddable package "
            f"layout changed — re-lock and report if this persists."
        )
    return lib
