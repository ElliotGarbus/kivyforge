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

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from kivyforge.report.failures import ClassifiedError, spawn_failure
from kivyforge.report.streams import stderr_for_child


class PycompileError(ClassifiedError):
    """Byte-compilation failed, or the compiler could not be run."""


def select_compiler(
    *, staged_interpreter: Path, native: bool, python_version: str
) -> tuple[str, ...] | None:
    """Pick the interpreter argv to byte-compile the staged payload with.

    The staged interpreter is the one actually shipped, so it is the first
    choice — but only when *native*, i.e. the caller has confirmed it can run
    on this host without emulation, which kivyforge never depends on. When it
    can't run here, fall back to any **final** CPython of the target's minor
    this host can offer (:func:`find_interpreter`): a ``.pyc``'s magic number is
    keyed to CPython's *minor* version, never architecture, so an interpreter of
    the right minor will do regardless of which arch it runs on.
    Returns ``None`` when neither works, telling the caller to degrade (skip
    compiling, ship source) rather than write a ``.pyc`` nothing can load.
    """
    if native and staged_interpreter.is_file():
        return (str(staged_interpreter),)
    return find_interpreter(python_version)


def find_interpreter(python_version: str) -> tuple[str, ...] | None:
    """Find an interpreter on this host able to write ``.pyc`` for *python_version*.

    kivyforge is installed under whatever Python the user happens to have, which
    is usually *not* the version being shipped to the target, so this looks for
    a matching one rather than insisting on being run under it. That is what
    every backend's error message already promises ("kivyforge finds it
    automatically"), and until this was shared it was only true on Android.

    A ``.pyc`` is keyed to one exact CPython magic number, frozen at each
    minor's first release candidate — so any *final* ``3.x.z`` will do, but a
    different minor will not. A pre-release of the *right* minor is the trap it
    has to exclude; see :func:`is_final_release`.

    Returns ``()`` for "this interpreter", an argv prefix for another one, or
    ``None`` when there is no match to be found.
    """
    target = target_minor(python_version)
    if sys.version_info[:2] == target and is_final_release():
        return ()
    tag = f"{target[0]}.{target[1]}"
    candidates: list[tuple[str, ...]] = []
    if os.name == "nt":
        # The PEP 397 launcher is the reliable way to reach a specific version
        # on Windows; versioned executables are usually not on PATH there.
        candidates.append(("py", f"-{tag}"))
    candidates += [(f"python{tag}",), (f"python{target[0]}",), ("python",)]
    for candidate in candidates:
        if _reports_version(candidate, tag):
            return candidate
    return None


def _reports_version(argv: tuple[str, ...], tag: str) -> bool:
    """Whether *argv* is a **final** release of CPython minor *tag*.

    The releaselevel half is load-bearing, not belt-and-braces: an alpha of the
    right minor passes a bare version check and then writes ``.pyc`` the
    shipped runtime cannot import (see :func:`find_interpreter`).
    """
    try:
        proc = subprocess.run(
            [
                *argv,
                "-c",
                "import sys;print('%d.%d %s' % (sys.version_info[0],"
                " sys.version_info[1], sys.version_info.releaselevel))",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    parts = proc.stdout.split()
    return len(parts) == 2 and parts[0] == tag and parts[1] == "final"


def is_final_release() -> bool:
    """Whether *this* interpreter can write ``.pyc`` a release runtime loads.

    Matching the CPython *minor* version is necessary but not sufficient: the
    magic number is bumped repeatedly through the alpha/beta cycle and is only
    frozen at the first release candidate. So a 3.14 alpha writes bytecode a
    shipped 3.14.6 rejects at import, even though both are "3.14" — and with
    the source stripped, that is an app that cannot boot.

    Release candidates are excluded too. The freeze makes them safe in
    principle, but the margin is not worth the risk when the fallback is
    simply shipping readable source.
    """
    return sys.version_info.releaselevel == "final"


def target_minor(python_version: str) -> tuple[int, int]:
    """The ``(major, minor)`` a ``.pyc``'s magic number is keyed to."""
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
    # compileall reports errors on stdout, which is the command's product; they
    # are build log, so they go to stderr in both branches.
    if not compiler:
        import compileall
        import contextlib
        import py_compile

        with contextlib.redirect_stdout(sys.stderr):
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
        with stderr_for_child() as err:
            return (
                subprocess.run(argv, check=False, stdout=err, stderr=err).returncode
                == 0
            )
    except OSError as exc:
        raise PycompileError(
            f"could not run {' '.join(compiler)} to byte-compile {target.name}: {exc}",
            **spawn_failure(compiler[0], exc),
        ) from exc
