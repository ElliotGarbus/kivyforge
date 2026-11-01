"""Will each declared native binary find the declared libraries it links?

macos-native-binaries-placement-proposal §3.5. kivyforge does not rewrite load
commands, but a helper in ``Contents/Helpers/`` that expects its library beside
it fails at launch once the library is in ``Contents/Frameworks/``. This module
works out, per process, where dyld would look for each link to a library the
channel staged, so the build can refuse a binary that will not load.

dyld's rules, as the spikes measured them (proposal §2):

- ``@executable_path`` is the directory of the process's main executable: a
  helper's own directory, or ``Contents/MacOS/`` for a library the app loads
  with ``ctypes`` (the launcher runs CPython in its own process).
- ``@loader_path`` is the directory of the image holding the link.
- ``@rpath`` tries the run paths of that image, then of each image that
  loaded it, back to the main executable. Run paths are never shared between
  processes.
- A library the process has already loaded satisfies a later link whose text
  is exactly that library's install name. Python code can arrange that by
  loading libraries in dependency order; a helper cannot.
- A weak link that does not resolve does not stop the image loading.

Pure: images are described by where they will be in the bundle and by their
parsed headers, so the whole walk runs on synthetic data in the hermetic suite.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass
from pathlib import Path

from .machotools import Dependency, MachoSlice

#: Absolute links into these are served by the dyld shared cache, even when the
#: app also ships a library with the same file name.
_SYSTEM_PREFIXES = ("/usr/lib/", "/System/")

_APPLE_RECIPE = (
    "https://developer.apple.com/documentation/xcode/"
    "embedding-nonstandard-code-structures-in-a-bundle"
)


@dataclass(frozen=True)
class Image:
    """A staged Mach-O: where it will live in the bundle, and its headers."""

    path: Path
    macho: MachoSlice
    #: An executable in ``Contents/Helpers/``; otherwise a dynamic library.
    is_helper: bool


@dataclass(frozen=True)
class Interpreter:
    """The process ``ctypes`` loads libraries into: the launcher's, running CPython.

    *exe_dir* is its main executable's directory and *rpaths* that
    executable's run paths.
    """

    exe_dir: Path
    rpaths: tuple[str, ...]


@dataclass(frozen=True)
class LinkProblem:
    binary: Image
    library: Image
    dependency: Dependency
    process: str
    tried: tuple[Path, ...]
    #: ``""`` for an error, else why it is only a warning: ``"weak"`` or
    #: ``"preload"``.
    warning: str

    def context(self) -> dict[str, str | None]:
        return {
            "binary": self.binary.path.name,
            "library": self.library.path.name,
            "process": self.process,
            "dependency": self.dependency.name,
        }


@dataclass(frozen=True)
class _Process:
    label: str
    exe_dir: Path
    python: bool


# One step of a loading chain: an image's directory and its run paths.
_Step = tuple[Path, tuple[str, ...]]


def check_links(images: list[Image], interpreter: Interpreter) -> list[LinkProblem]:
    """Every link to a declared library that would not resolve, per process.

    Helpers are roots of their own processes. A library no staged binary links
    is taken to be loaded from Python, and walked in the interpreter's process;
    a library that is linked is judged through whatever links it. A library
    only other libraries link, and that no walk reached (a cycle, or a link
    already reported as broken), is walked from Python too, so its own links
    are still checked.
    """
    libraries = [i for i in images if not i.is_helper]
    helpers = [i for i in images if i.is_helper]
    targets = _Targets(libraries)
    problems: dict[tuple[str, Path, str], LinkProblem] = {}
    reached: set[Path] = set()

    for helper in helpers:
        process = _Process(f"the helper {helper.path.name}", helper.path.parent, False)
        _walk(helper, [], process, targets, {helper.path}, problems, reached)

    linked_by_helper = _linked(helpers, targets)
    linked = linked_by_helper | _linked(libraries, targets)
    exe_dir = interpreter.exe_dir
    root: list[_Step] = [(exe_dir, interpreter.rpaths)]
    process = _Process("Python (ctypes)", exe_dir, True)
    for lib in libraries:
        if lib.path not in linked:
            reached.add(lib.path)
            _walk(lib, root, process, targets, {lib.path}, problems, reached)
    while unreached := [
        lib
        for lib in libraries
        if lib.path not in reached and lib.path not in linked_by_helper
    ]:
        lib = unreached[0]
        reached.add(lib.path)
        _walk(lib, root, process, targets, {lib.path}, problems, reached)
    return list(problems.values())


def _linked(images: list[Image], targets: _Targets) -> set[Path]:
    """The declared libraries *images* link, resolvable or not."""
    return {
        lib.path
        for image in images
        for dep in image.macho.dependencies
        if (lib := targets.find(dep.name)) is not None and lib.path != image.path
    }


class _Targets:
    """Which declared library a dependency names, if any."""

    def __init__(self, libraries: list[Image]) -> None:
        self._by_install = {
            lib.macho.install_name: lib for lib in libraries if lib.macho.install_name
        }
        self._by_leaf = {lib.path.name.casefold(): lib for lib in libraries}

    def find(self, dependency: str) -> Image | None:
        if dependency.startswith(_SYSTEM_PREFIXES):
            return None
        hit = self._by_install.get(dependency)
        if hit is not None:
            return hit
        return self._by_leaf.get(posixpath.basename(dependency).casefold())


def _walk(
    image: Image,
    loaders: list[_Step],
    process: _Process,
    targets: _Targets,
    in_chain: set[Path],
    problems: dict[tuple[str, Path, str], LinkProblem],
    reached: set[Path],
) -> None:
    own: _Step = (image.path.parent, image.macho.rpaths)
    search = [own, *reversed(loaders)]
    for dep in image.macho.dependencies:
        lib = targets.find(dep.name)
        if lib is None or lib.path == image.path:
            continue
        tried = [
            Path(os.path.normpath(path))
            for path in _candidates(
                dep.name, image.path.parent, search, process.exe_dir
            )
        ]
        if Path(os.path.normpath(lib.path)) in tried:
            reached.add(lib.path)
            if lib.path not in in_chain:
                _walk(
                    lib,
                    [*loaders, own],
                    process,
                    targets,
                    in_chain | {lib.path},
                    problems,
                    reached,
                )
            continue
        if dep.weak:
            warning = "weak"
        elif process.python and dep.name == lib.macho.install_name:
            warning = "preload"
        else:
            warning = ""
        key = (process.label, image.path, dep.name)
        problems.setdefault(
            key, LinkProblem(image, lib, dep, process.label, tuple(tried), warning)
        )


def _candidates(
    dependency: str, loader_dir: Path, search: list[_Step], exe_dir: Path
) -> list[Path]:
    """The paths dyld tries for *dependency*, in order (bare names: none)."""
    for token, base in (("@executable_path", exe_dir), ("@loader_path", loader_dir)):
        if dependency.startswith(token + "/"):
            return [Path(str(base) + dependency[len(token) :])]
    if dependency.startswith("@rpath/"):
        rest = dependency[len("@rpath") :]
        found = []
        for step_dir, rpaths in search:
            for rpath in rpaths:
                base = _expand(rpath, step_dir, exe_dir)
                if base is not None:
                    found.append(Path(str(base) + rest))
        return found
    if dependency.startswith("/"):
        return [Path(dependency)]
    return []


def _expand(rpath: str, loader_dir: Path, exe_dir: Path) -> Path | None:
    for token, base in (("@executable_path", exe_dir), ("@loader_path", loader_dir)):
        if rpath == token or rpath.startswith(token + "/"):
            return Path(str(base) + rpath[len(token) :])
    if rpath.startswith("/"):
        return Path(rpath)
    return None


def describe(problem: LinkProblem, contents: Path) -> str:
    """The message for *problem*: what fails, where dyld looks, and the fix."""
    binary = problem.binary.path.name
    library = problem.library.path.name
    dep = problem.dependency
    tried = ", ".join(_shown(p, contents) for p in problem.tried) or (
        "nowhere in the bundle"
    )
    head = (
        f"{_shown(problem.binary.path, contents)} links {library} as {dep.name!r} "
        f"({dep.command}); in {problem.process} dyld tries {tried}, not "
        f"{_shown(problem.library.path, contents)}."
    )
    if problem.warning == "weak":
        return head + f"\n  It is a weak link, so {binary} loads without {library}."
    fix = _fix(problem)
    if problem.warning == "preload":
        return (
            head + f"\n  It loads only if the app loads {library} first. "
            f"To not depend on that: {fix}"
        )
    return head + f"\n  Fix: {fix}"


def _fix(problem: LinkProblem) -> str:
    binary = problem.binary.path.name
    library = problem.library.path.name
    dep = problem.dependency.name
    rpath = (
        "@loader_path"
        if not problem.binary.is_helper
        else ("@executable_path/../Frameworks")
    )
    steps = []
    if not dep.startswith("@rpath/"):
        steps.append(f"install_name_tool -change '{dep}' '@rpath/{library}' {binary}")
    if rpath not in problem.binary.macho.rpaths:
        steps.append(f"install_name_tool -add_rpath {rpath} {binary}")
    commands = "; ".join(steps) or f"check the run paths of {binary}"
    return f"{commands}, then re-lock. See {_APPLE_RECIPE}"


def _shown(path: Path, contents: Path) -> str:
    try:
        return "Contents/" + path.relative_to(contents).as_posix()
    except ValueError:
        return path.as_posix()
