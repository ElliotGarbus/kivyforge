"""Stage locked native binaries into the ``.app``'s code locations (macos-spec).

The ``[tool.kivy.macos.native.binaries]`` channel places native code where
Apple's bundle layout says it goes
(macos-native-binaries-placement-proposal.md): executables (``MH_EXECUTE``) in
``Contents/Helpers/``, dynamic libraries (``MH_DYLIB``) in
``Contents/Frameworks/``. Each code location is flat, so a file from an
archive keeps only its name.

Each entry is fetched, SHA-256-verified and extracted by the shared
:mod:`kivyforge.artifacts.native_stage_util` into a temporary directory, which
keeps the path-traversal guards in one audited place. Then every file is
classified and given a destination, the links between them are checked
(:mod:`.native_links`), and only then is anything copied into the bundle.

Only native code is placed. A single-file source that is not a Mach-O is
refused; archive members that are not (headers, licences) are skipped with a
warning. Other Mach-O types, and binaries inside a bundle in an archive, are
refused: neither has a place in this channel.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click

from kivyforge.artifacts.cache import ArtifactCache
from kivyforge.artifacts.native_stage_util import NativeStageError, stage_binaries
from kivyforge.build_outcome import discard_note
from kivyforge.report import diagnostics

from . import AppBundleError
from .lock import MacosLockfile
from .machotools import (
    MH_DYLIB,
    MH_EXECUTE,
    MachoError,
    MachoFile,
    MachoSlice,
    NotMachoError,
    filetype_name,
    is_macho,
    read_macho,
)
from .native_links import Image, Interpreter, check_links, describe

NATIVE_KEY = "[tool.kivy.macos.native.binaries]"
HELPERS = "Helpers"
FRAMEWORKS = "Frameworks"

_ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz")

#: Directory suffixes Apple uses for bundles. A Mach-O below one is part of the
#: bundle, and moving it out on its own would break it.
_BUNDLE_SUFFIXES = (
    ".app",
    ".appex",
    ".bundle",
    ".dext",
    ".framework",
    ".kext",
    ".mdimporter",
    ".plugin",
    ".prefpane",
    ".qlgenerator",
    ".saver",
    ".service",
    ".systemextension",
    ".xpc",
)
#: Where a bundle keeps its Info.plist: a flat (iOS-style) bundle, a macOS
#: bundle, and a versioned framework's ``Versions/A``.
_BUNDLE_MARKERS = ("Info.plist", "Contents/Info.plist", "Resources/Info.plist")

#: How many skipped archive members a warning names.
_SHOWN = 10


@dataclass(frozen=True)
class _Planned:
    entry: str
    member: str
    staged: Path
    dest: Path
    macho: MachoSlice


def stage_native_binaries(
    lock: MacosLockfile,
    contents: Path,
    *,
    target_arch: str,
    project_root: Path,
    cache: ArtifactCache | None = None,
    no_cache: bool = False,
    echo: Callable[[str], None] = click.echo,
    note=discard_note,
) -> list[Path]:
    """Place every pinned native binary under *contents*; return what was placed.

    *contents* is the bundle's ``Contents/``, with the runtime already staged
    (the link check reads the interpreter's run paths).
    """
    if not lock.native_binaries:
        return []
    cache = cache or ArtifactCache()
    with tempfile.TemporaryDirectory(prefix="kivy-nb-") as tmp:
        plan, skipped = _plan(
            lock,
            Path(tmp),
            contents,
            target_arch=target_arch,
            project_root=project_root,
            cache=cache,
            no_cache=no_cache,
        )
        if skipped:
            _report_skipped(skipped, echo, note)
        _check_links(plan, contents, target_arch, echo, note)
        for item in plan:
            item.dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.staged, item.dest)
    return [item.dest for item in plan]


def _plan(
    lock: MacosLockfile,
    work: Path,
    contents: Path,
    *,
    target_arch: str,
    project_root: Path,
    cache: ArtifactCache,
    no_cache: bool,
) -> tuple[list[_Planned], list[tuple[str, str]]]:
    plan: list[_Planned] = []
    skipped: list[tuple[str, str]] = []
    claimed: dict[str, dict[str, _Planned]] = {HELPERS: {}, FRAMEWORKS: {}}
    for index, entry in enumerate(lock.native_binaries):
        root = work / str(index)
        try:
            # One entry at a time: two archives may both carry a LICENSE,
            # which is skipped and must not collide. Code collisions are
            # checked below, per code location.
            stage_binaries(
                (entry,),
                root,
                project_root=project_root,
                cache=cache,
                no_cache=no_cache,
                bin_label=NATIVE_KEY,
                casefold=True,
            )
        except NativeStageError as exc:
            raise AppBundleError(str(exc)) from exc
        staged_dir = root / "bin"
        source = entry.url or entry.path or ""
        archive = source.lower().endswith(_ARCHIVE_SUFFIXES)
        for staged in sorted(staged_dir.rglob("*")):
            if staged.is_symlink() or not staged.is_file():
                continue
            member = staged.relative_to(staged_dir).as_posix() if archive else source
            macho = _read(staged, entry.name, member)
            if macho is None:
                if not archive:
                    raise _not_code(entry.name, source)
                skipped.append((entry.name, member))
                continue
            if archive:
                bundle = _enclosing_bundle(staged, staged_dir)
                if bundle is not None:
                    raise _unsupported(
                        entry.name,
                        member,
                        f"{member} is inside {bundle}/, a bundle. This channel "
                        "places standalone executables and dynamic libraries; "
                        "taking the binary out of its bundle would break it",
                    )
            location = _location(macho.filetypes, entry.name, member)
            chosen = macho.slice_for(target_arch)
            if chosen is None:
                have = ", ".join(s.arch for s in macho.slices)
                raise AppBundleError(
                    f"native binary {entry.name!r}: {member} has no {target_arch} "
                    f"code (it has {have}), so the app could not load it.\n"
                    f"  Rebuild it for {target_arch}, then re-lock."
                )
            item = _Planned(
                entry.name, member, staged, contents / location / staged.name, chosen
            )
            prev = claimed[location].get(staged.name.casefold())
            if prev is not None:
                raise AppBundleError(
                    f"native binaries {prev.entry!r} ({prev.member}) and "
                    f"{entry.name!r} ({member}) would both be "
                    f"Contents/{location}/{staged.name}.\n"
                    f"  Contents/{location}/ is flat, and names that differ only "
                    "in case are the same file on macOS. Rename one, or drop "
                    "the duplicate."
                )
            claimed[location][staged.name.casefold()] = item
            plan.append(item)
    return plan, skipped


def _read(staged: Path, entry: str, shown: str) -> MachoFile | None:
    """The parsed Mach-O, or ``None`` when *staged* is not one."""
    if not is_macho(staged):
        return None
    try:
        return read_macho(staged)
    except NotMachoError:
        return None
    except MachoError as exc:
        raise _unsupported(
            entry, shown, f"{shown} has a Mach-O header that cannot be read ({exc})"
        ) from exc


def _location(filetypes: frozenset[int], entry: str, member: str) -> str:
    if len(filetypes) > 1:
        kinds = " and ".join(sorted(filetype_name(t) for t in filetypes))
        raise _unsupported(
            entry,
            member,
            f"{member} is a universal file whose slices disagree on what it is "
            f"({kinds})",
        )
    (filetype,) = filetypes
    if filetype == MH_EXECUTE:
        return HELPERS
    if filetype == MH_DYLIB:
        return FRAMEWORKS
    raise _unsupported(
        entry,
        member,
        f"{member} is a {filetype_name(filetype)}, not an executable or a "
        "dynamic library",
    )


def _enclosing_bundle(staged: Path, top: Path) -> str | None:
    """The bundle directory *staged* sits in, relative to *top*, if any."""
    for parent in staged.relative_to(top).parents:
        if parent == Path("."):
            continue
        directory = top / parent
        if parent.name.casefold().endswith(_BUNDLE_SUFFIXES) or any(
            (directory / marker).is_file() for marker in _BUNDLE_MARKERS
        ):
            return parent.as_posix()
    return None


def _not_code(entry: str, source: str) -> AppBundleError:
    return AppBundleError(
        f"native binary {entry!r} ({source}) is not a Mach-O file. "
        f"{NATIVE_KEY} places native code only.\n"
        "  Fix: list data under [[tool.kivy.macos.include_files]], and put "
        "scripts in app_dir.",
        code=diagnostics.MACOS_NATIVE_NOT_CODE,
        context={"binary": entry, "path": source},
    )


def _unsupported(entry: str, path: str, why: str) -> AppBundleError:
    return AppBundleError(
        f"native binary {entry!r}: {why}.\n"
        f"  {NATIVE_KEY} places executables in Contents/Helpers/ and dynamic "
        "libraries in Contents/Frameworks/; plug-ins and bundles are not "
        "supported.",
        code=diagnostics.MACOS_NATIVE_UNSUPPORTED,
        context={"binary": entry, "path": path},
    )


def _report_skipped(skipped: list[tuple[str, str]], echo, note) -> None:
    shown = [f"{entry}: {member}" for entry, member in skipped[:_SHOWN]]
    more = len(skipped) - len(shown)
    listing = "; ".join(shown) + (f"; and {more} more" if more else "")
    count = f"{len(skipped)} archive member" + ("s" if len(skipped) != 1 else "")
    message = (
        f"skipped {count} that are not Mach-O files ({listing}). "
        f"{NATIVE_KEY} places native code only; list any the app needs under "
        "[[tool.kivy.macos.include_files]]."
    )
    echo(f"[stage] {message}")
    entries = sorted({entry for entry, _ in skipped})
    note(
        diagnostics.MACOS_NATIVE_NOT_CODE,
        message,
        {"binary": ", ".join(entries), "path": listing},
    )


def _check_links(
    plan: list[_Planned], contents: Path, target_arch: str, echo, note
) -> None:
    images = [
        Image(item.dest, item.macho, is_helper=item.dest.parent.name == HELPERS)
        for item in plan
    ]
    problems = check_links(images, _interpreter(contents, target_arch))
    errors = [p for p in problems if not p.warning]
    for problem in problems:
        if problem.warning:
            message = describe(problem, contents)
            echo(f"[stage] warning: {message}")
            note(
                diagnostics.MACOS_NATIVE_LOAD_PATH,
                message.splitlines()[0],
                {k: v or "" for k, v in problem.context().items()},
            )
    if errors:
        shown = [describe(p, contents) for p in errors[:_SHOWN]]
        more = len(errors) - len(shown)
        tail = f"\n... and {more} more." if more else ""
        raise AppBundleError(
            "\n".join(shown) + tail,
            code=diagnostics.MACOS_NATIVE_LOAD_PATH,
            context=errors[0].context(),
        )


def _interpreter(contents: Path, target_arch: str) -> Interpreter:
    """The staged CPython, the process a ``ctypes`` load happens in."""
    link = contents / "Resources" / "python" / "bin" / "python3"
    path = link.resolve() if link.exists() else link
    rpaths: tuple[str, ...] = ()
    try:
        chosen = read_macho(path).slice_for(target_arch)
    except MachoError:
        chosen = None
    if chosen is not None:
        rpaths = chosen.rpaths
    return Interpreter(path, rpaths)
