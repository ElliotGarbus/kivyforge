"""Byte-compile a staged Python payload, optionally stripping the sources.

Shared by every backend that ships a Python tree: Android's asset bundle and
the three desktop bundles. The mechanics below are identical everywhere; what
differs per platform is only *which* trees get compiled and *which* interpreter
does the compiling, both of which the caller supplies.

Two layouts, and the difference matters:

- Keeping the source, the ``.pyc`` goes in ``__pycache__/`` as usual, so imports
  find it next to the ``.py`` it was built from.
- Shipping ``.pyc`` only requires the *legacy* layout — PEP 3147 sourceless
  imports look for ``foo.pyc`` at the source's own path, never inside
  ``__pycache__/``. Compiling to ``__pycache__/`` and then deleting the ``.py``
  would produce a tree that imports nothing at all.

Hash-based, unchecked invalidation (PEP 552) is used rather than the default
mtime+size: it saves a stat per import for a payload that cannot have a newer
source than the one shipped, and it keeps an mtime out of every ``.pyc``.

Paths are stripped to be payload-relative because a ``.pyc`` records the path it
was compiled from: the default would leak local host paths into the shipped
artifact and make otherwise-identical builds differ per machine.

``compiler`` is an interpreter argv prefix whose CPython *minor* matches the
target runtime — empty means "this interpreter". Establishing that match is the
caller's job, because a ``.pyc`` is only loadable by the exact CPython minor
that wrote it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


class PycompileError(Exception):
    """Byte-compilation failed, or the compiler could not be run."""


def select_compiler(
    *, staged_interpreter: Path, native: bool, python_version: str
) -> tuple[str, ...] | None:
    """Pick the interpreter argv to byte-compile the staged payload with.

    The staged interpreter is the one actually shipped, so it is the first
    choice — but only when *native*, i.e. the caller has confirmed it can run
    on this host without emulation, which kivyforge never depends on. When it
    can't run here, fall back to this process's own interpreter: a ``.pyc``'s
    magic number is keyed to CPython's *minor* version only, never
    architecture, so any interpreter of the right minor will do regardless of
    which arch it runs on. Returns ``None`` when neither works, telling the
    caller to degrade (skip compiling, ship source) rather than write a
    ``.pyc`` nothing can load.
    """
    if native and staged_interpreter.is_file():
        return (str(staged_interpreter),)
    if sys.version_info[:2] == _target_minor(python_version):
        return ()
    return None


def _target_minor(python_version: str) -> tuple[int, int]:
    parts = python_version.split(".")[:2]
    return (int(parts[0].split("rc")[0]), int(parts[1].split("rc")[0]))


def byte_compile(
    trees: Sequence[Path],
    *,
    compiler: Sequence[str] = (),
    strip_source: bool = False,
    stripdir: Path,
) -> None:
    """Compile every tree in *trees* in place; strip ``.py`` when asked.

    Missing trees are skipped (a backend may stage some payload areas only
    conditionally). Raises :class:`PycompileError` naming the tree that failed.
    """
    for tree in trees:
        if not tree.is_dir():
            continue
        if not compile_tree(
            tree, compiler=compiler, legacy=strip_source, stripdir=stripdir
        ):
            raise PycompileError(
                f"byte-compiling {tree.name}/ failed; the output above names the "
                "file.\n"
                "  A syntax error in app code fails here rather than at runtime."
            )
        if strip_source:
            strip_sources(tree)


def strip_sources(tree: Path) -> None:
    """Delete every ``.py`` that has a sibling ``.pyc``, and all ``__pycache__``.

    Only sources with a compiled counterpart are removed, so a file the
    compiler skipped is never silently dropped from the payload. The
    ``__pycache__`` sweep matters because nothing can import from it once the
    sources are gone — leaving it behind would ship dead weight.
    """
    for source in tree.rglob("*.py"):
        if source.with_suffix(".pyc").is_file():
            source.unlink()
    for cache in tree.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def compile_tree(
    target: Path,
    *,
    compiler: Sequence[str] = (),
    legacy: bool = False,
    stripdir: Path,
) -> bool:
    """Byte-compile *target*; return whether it succeeded.

    Uses ``compileall`` in-process when *compiler* is empty, otherwise shells
    out to the named interpreter so the ``.pyc`` carries the target runtime's
    magic number.
    """
    if not compiler:
        import compileall
        import py_compile

        return bool(
            compileall.compile_dir(
                target,
                quiet=1,
                legacy=legacy,
                optimize=0,
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
                force=True,
                stripdir=str(stripdir),
            )
        )

    argv = [
        *compiler,
        "-m",
        "compileall",
        "-q",
        "-f",
        "--invalidation-mode",
        "unchecked-hash",
        "-s",
        str(stripdir),
    ]
    if legacy:
        argv.append("-b")
    argv.append(str(target))
    try:
        return subprocess.run(argv, check=False).returncode == 0
    except OSError as exc:
        raise PycompileError(
            f"could not run {' '.join(compiler)} to byte-compile {target.name}: {exc}"
        ) from exc
