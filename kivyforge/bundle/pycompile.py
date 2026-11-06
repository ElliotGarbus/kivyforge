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
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.failures import (
    Classification,
    ClassifiedError,
    spawn_failure,
)
from kivyforge.report.streams import stderr_for_child


class PycompileError(ClassifiedError):
    """Byte-compilation failed, or the compiler could not be run."""


def select_compiler(
    *,
    staged_interpreter: Path,
    native: bool,
    python_version: str,
    searched: list[Candidate] | None = None,
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
    *searched* is passed through to :func:`find_interpreter`.
    """
    if native and staged_interpreter.is_file():
        return (str(staged_interpreter),)
    return find_interpreter(python_version, searched=searched)


@dataclass(frozen=True)
class Candidate:
    """One interpreter :func:`find_interpreter` looked at, and what it was.

    Kept so a failure can say what was searched. "No final CPython 3.15 found"
    alone was read as kivyforge believing 3.15 unreleased (issue #209), when the
    host simply had no 3.15 on ``PATH``.
    """

    #: How it was reached: an argv, or ``("uv", "python", "find")``.
    label: str
    #: ``"3.14.7"``, ``"3.15.0rc1"``; ``None`` when it was absent or would not run.
    version: str | None


def find_interpreter(
    python_version: str, *, searched: list[Candidate] | None = None
) -> tuple[str, ...] | None:
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

    Used only by a desktop build whose staged runtime can't compile its own
    payload (it is missing). iOS, Android and a Linux ``aarch64`` target never
    search: they compile with the host CPython the lock pins
    (:mod:`kivyforge.bundle.hostpython`).

    The search, in order: this interpreter; the ``py`` launcher (Windows);
    ``python3.x``, ``python3`` and ``python`` on ``PATH``; and, only when uv is
    installed, whatever ``uv python find`` reports. uv is never required — an
    interpreter it manages is often not on ``PATH``, which is the one case the
    earlier rungs miss. Each candidate looked at is appended to *searched*.

    Returns ``()`` for "this interpreter", an argv prefix for another one, or
    ``None`` when there is no match to be found.
    """
    seen = searched if searched is not None else []
    target = target_minor(python_version)
    this = _describe(
        *sys.version_info[:3], sys.version_info.releaselevel, sys.version_info.serial
    )
    if sys.version_info[:2] == target and is_final_release():
        return ()
    seen.append(Candidate(f"this interpreter ({sys.executable})", this))
    tag = f"{target[0]}.{target[1]}"
    candidates: list[tuple[str, ...]] = []
    if os.name == "nt":
        # The PEP 397 launcher is the reliable way to reach a specific version
        # on Windows; versioned executables are usually not on PATH there.
        candidates.append(("py", f"-{tag}"))
    candidates += [(f"python{tag}",), (f"python{target[0]}",), ("python",)]
    for candidate in candidates:
        if _accept(candidate, tag, " ".join(candidate), seen):
            return candidate
    uv = _uv_executable()
    if uv is None:
        return None
    uv_found = _uv_find(uv, tag)
    if uv_found is None:
        seen.append(Candidate("uv python find", None))
        return None
    if _accept(uv_found, tag, f"uv python find ({uv_found[0]})", seen):
        return uv_found
    return None


def _accept(argv: tuple[str, ...], tag: str, label: str, seen: list[Candidate]) -> bool:
    """Probe *argv*, record it in *seen*, and say whether it can compile for *tag*.

    The releaselevel half is load-bearing, not belt-and-braces: an alpha of the
    right minor passes a bare version check and then writes ``.pyc`` the
    shipped runtime cannot import (see :func:`find_interpreter`).
    """
    probed = _probe_version(argv)
    if probed is None:
        seen.append(Candidate(label, None))
        return False
    major, minor, micro, level, serial = probed
    seen.append(Candidate(label, _describe(major, minor, micro, level, serial)))
    return f"{major}.{minor}" == tag and level == "final"


def _probe_version(argv: tuple[str, ...]) -> tuple[int, int, int, str, int] | None:
    """*argv*'s ``sys.version_info``, or ``None`` if it is absent or will not run."""
    try:
        proc = subprocess.run(
            [
                *argv,
                "-c",
                "import sys;print('%d %d %d %s %d' % tuple(sys.version_info))",
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    parts = proc.stdout.split()
    if len(parts) != 5:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2]), parts[3], int(parts[4])
    except ValueError:
        return None


def _uv_executable() -> str | None:
    """uv, if it is installed. Optional: nothing here requires it."""
    return shutil.which("uv")


def _uv_find(uv: str, tag: str) -> tuple[str, ...] | None:
    """The interpreter ``uv python find`` reports for *tag*.

    ``--no-project`` keeps the cwd's ``.python-version`` and ``requires-python``
    out of the answer; ``--no-python-downloads`` keeps the search off the
    network, which byte-compiling must never need.
    """
    try:
        proc = subprocess.run(
            [uv, "python", "find", "--no-project", "--no-python-downloads", tag],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = proc.stdout.strip()
    if proc.returncode != 0 or not path:
        return None
    return (path,)


_LEVELS = {"alpha": "a", "beta": "b", "candidate": "rc"}


def _describe(major: int, minor: int, micro: int, level: str, serial: int) -> str:
    """``3.15.2`` for a final release, ``3.15.0rc1`` for a pre-release."""
    version = f"{major}.{minor}.{micro}"
    if level == "final":
        return version
    return f"{version}{_LEVELS.get(level, level)}{serial}"


@dataclass(frozen=True)
class NoInterpreter:
    """What every backend says when byte-compiling has no interpreter to use.

    One wording for all six call sites (iOS app and pip-deps, macOS, Linux,
    Windows, Android) and doctor, which had drifted into copies of each other.
    """

    headline: str
    #: The search, an optional pre-release note, and the ``Fix:`` line.
    lines: tuple[str, ...]
    #: For ``ClassifiedError(**...)`` when ``byte_compile = true`` insists.
    #: Exit 3: what is missing is on the machine, not in the config.
    classification: Classification

    def detail(self, indent: str = "  ") -> str:
        return "\n".join(indent + line for line in self.lines)

    def required(self, table: str) -> str:
        """The message for ``byte_compile = true``, which fails the build."""
        return f"[{table}].byte_compile = true, but {self.headline}.\n{self.detail()}"


def no_interpreter(
    python_version: str, *, table: str, searched: Sequence[Candidate]
) -> NoInterpreter:
    """Describe a failed :func:`find_interpreter` search for the user."""
    target = target_minor(python_version)
    minor = f"{target[0]}.{target[1]}"
    headline = f"no final CPython {minor} found (this project ships {python_version})"
    lines: list[str] = []
    if searched:
        lines.append(
            f"The .pyc files must be written by a final CPython {minor} on this "
            "machine. Looked at:"
        )
        lines += [
            f"  {c.label}: {c.version if c.version else 'not found'}" for c in searched
        ]
    prereleases = [
        c.version
        for c in searched
        if c.version is not None
        and c.version.startswith(f"{minor}.")
        and not c.version[len(minor) + 1 :].isdigit()
    ]
    if prereleases:
        lines.append(
            f"{', '.join(prereleases)} is a pre-release, which does not count: "
            "CPython only freezes the .pyc format at the first release "
            f"candidate, so an alpha writes bytecode {python_version} refuses "
            "to import."
        )
    lines.append(
        f"Fix: install any final CPython {minor}.x (for example "
        f"`uv python install {minor}`, or python.org) so python{minor} is on "
        f"PATH, or set byte_compile = false in [{table}]."
    )
    return NoInterpreter(
        headline=headline,
        lines=tuple(lines),
        classification={
            "code": diagnostics.BYTECOMPILE_NO_INTERP,
            "exit_code": exit_codes.ENVIRONMENT_ERROR,
            "context": {"tool": f"python{minor}"},
        },
    )


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


def stdlib_dir(python_home: Path) -> Path | None:
    """The staged runtime's stdlib directory, or ``None`` if it is not there.

    Two layouts, both shipped by python-build-standalone: ``Lib/`` on Windows and
    ``lib/python3.x/`` elsewhere. Located by looking for ``os.py`` rather than by
    building a path from a version string, so a runtime bump cannot silently make
    this a no-op.
    """
    windows = python_home / "Lib"
    if (windows / "os.py").is_file():
        return windows
    for candidate in sorted((python_home / "lib").glob("python3.*")):
        if (candidate / "os.py").is_file():
            return candidate
    return None


def byte_compile(
    trees: Sequence[Path],
    *,
    compiler: Sequence[str] = (),
    strip_source: bool = False,
    stripdir: Path,
    exclude: str | None = None,
) -> None:
    """Compile every tree in *trees* in place; strip ``.py`` when asked.

    Missing trees are skipped (a backend may stage some payload areas only
    conditionally). Raises :class:`PycompileError` naming the tree that failed.
    *exclude* is a regex of paths to leave alone, for a subtree a different call
    has already handled.
    """
    for tree in trees:
        if not tree.is_dir():
            continue
        if not compile_tree(
            tree,
            compiler=compiler,
            legacy=strip_source,
            stripdir=stripdir,
            exclude=exclude,
        ):
            raise PycompileError(
                f"byte-compiling {tree.name}/ failed; the output above names the "
                "file.\n"
                "  A syntax error in app code fails here rather than at runtime."
            )
        if strip_source:
            strip_sources(tree)


def compile_stdlib(
    python_home: Path,
    *,
    compiler: Sequence[str] = (),
    stripdir: Path,
    echo: Callable[[str], None] = lambda msg: None,
) -> None:
    """Byte-compile the staged runtime's stdlib in place.

    Desktop bundles ship the stdlib as source, so every launch re-parses it --
    measured at ~170 ms on `import kivy` alone, and permanent since both
    launchers stopped letting the app write ``__pycache__`` back into itself.

    Sources are **never** stripped here, unlike the app payload: the stdlib's
    ``.py`` files are what make tracebacks, ``inspect`` and ``linecache`` work,
    and they cost disk rather than launch time. ``site-packages`` is excluded
    because the caller compiles it as payload, under its own strip setting.
    """
    tree = stdlib_dir(python_home)
    if tree is None:
        return
    echo("[stage] byte-compiling the embedded stdlib")
    byte_compile(
        [tree],
        compiler=compiler,
        strip_source=False,
        stripdir=stripdir,
        exclude="site-packages",
    )


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
    exclude: str | None = None,
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
                    rx=re.compile(exclude) if exclude else None,
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
    if exclude:
        argv += ["-x", exclude]
    argv.append(str(target))
    # The compiler's *own* imports would otherwise deposit timestamp-invalidated
    # .pyc into whatever stdlib it is running from -- including the staged one it
    # is compiling, making that subtree depend on which interpreter ran the
    # build. compileall writes through py_compile and ignores this variable, so
    # only the incidental caching is suppressed (verified 2026-09-15).
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        with stderr_for_child() as err:
            return (
                subprocess.run(
                    argv,
                    check=False,
                    stdout=err,
                    stderr=err,
                    stdin=subprocess.DEVNULL,
                    env=env,
                ).returncode
                == 0
            )
    except OSError as exc:
        raise PycompileError(
            f"could not run {' '.join(compiler)} to byte-compile {target.name}: {exc}",
            **spawn_failure(compiler[0], exc),
        ) from exc
