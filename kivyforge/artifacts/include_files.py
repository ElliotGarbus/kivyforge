"""``include_files``: the user's own files, copied verbatim into the app (#170).

Android, iOS and macOS share one model (include-files-proposal.md §4.3):

* an entry's ``dest`` is a path under the platform's root (Android: the
  generated Gradle project; iOS: the ``.app``; macOS: ``Contents/``);
* a file source lands in ``dest`` under its own name, and a directory source's
  *contents* land in ``dest``, subfolders kept;
* ``lock`` records one SHA-256 pin per staged file, keyed by ``(dest,
  source)``, and ``build`` refuses an edited file, a file with no pin and a pin
  with no file, all as lock drift.

What differs per platform is passed in: the paths the generated build owns, the
override callback (Android only), and whether the file must arrive byte for
byte (iOS and macOS, where the built product is then checked against the pins,
§4.8). Each backend re-raises :class:`IncludeFilesError` in its own error
family with ``reclassify``, so the codes here survive to the CLI.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import posixpath
import shutil
import struct
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from kivyforge.artifacts.verify import sha256_file
from kivyforge.config.model import Config, IncludeFile
from kivyforge.lock.model import LockedIncludeFile
from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.failures import ClassifiedError

if TYPE_CHECKING:
    from kivyforge.doctor.result import CheckResult


class IncludeFilesError(ClassifiedError):
    """An include could not be pinned, staged or verified."""


class IncludeDrift(IncludeFilesError):
    """A file differs from, lacks or outlives its pin."""

    code = diagnostics.LOCK_DRIFT
    exit_code = exit_codes.LOCK_DRIFT


class IncludeReserved(IncludeFilesError):
    code = diagnostics.INCLUDE_RESERVED


class IncludeNativeCode(IncludeFilesError):
    code = diagnostics.INCLUDE_NATIVE_CODE


class IncludeSourceFormat(IncludeFilesError):
    code = diagnostics.INCLUDE_SOURCE_FORMAT


class ArtifactContentMismatch(IncludeFilesError):
    """The built product lacks an include or holds a different copy."""

    code = diagnostics.ARTIFACT_CONTENT
    exit_code = exit_codes.BUILD_FAILURE


@dataclass(frozen=True)
class IncludeItem:
    """One file an include stages."""

    file: Path
    #: Project-relative, posix: the pin's ``source``.
    source: str
    #: The entry's ``dest`` as written: the pin's ``dest``.
    dest: str
    #: Where the file lands, posix, relative to the platform's root.
    path: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.dest, self.source)

    @property
    def context(self) -> dict[str, str | None]:
        return {"path": self.path, "source": self.source}


def expand(entries: Iterable[IncludeFile], root: Path) -> list[IncludeItem]:
    """Every file *entries* stage, in table order, sources sorted within."""
    items: list[IncludeItem] = []
    for entry in entries:
        dest = entry.dest.replace("\\", "/")
        for source in entry.sources:
            local = (root / source).resolve()
            if local.is_dir():
                for child in sorted(local.rglob("*")):
                    if child.is_file():
                        rel = child.relative_to(local)
                        items.append(
                            IncludeItem(
                                file=child,
                                source=(Path(source) / rel).as_posix(),
                                dest=entry.dest,
                                path=posixpath.normpath(
                                    posixpath.join(dest, rel.as_posix())
                                ),
                            )
                        )
            elif local.is_file():
                items.append(
                    IncludeItem(
                        file=local,
                        source=Path(source).as_posix(),
                        dest=entry.dest,
                        path=posixpath.normpath(posixpath.join(dest, local.name)),
                    )
                )
            else:
                raise IncludeFilesError(
                    f"include_files source does not exist: {source} "
                    f"(resolved to {local})"
                )
    return items


def hash_pins(entries: Iterable[IncludeFile], root: Path) -> list[LockedIncludeFile]:
    """One pin per staged file, sorted the way the lock writes them."""
    pins = [
        LockedIncludeFile(source=i.source, dest=i.dest, sha256=sha256_file(i.file))
        for i in expand(entries, root)
    ]
    pins.sort(key=lambda p: p.key)
    return pins


def pins_current(
    pins: Iterable[LockedIncludeFile], entries: Iterable[IncludeFile], root: Path
) -> bool:
    """Whether *pins* are exactly what :func:`hash_pins` would record now.

    A missing source is not current: ``lock`` then rebuilds, and its error
    names the file.
    """
    try:
        fresh = hash_pins(entries, root)
    except IncludeFilesError:
        return False
    return fresh == sorted(pins, key=lambda p: p.key)


def entries_for(config: Config, platform: str) -> tuple[IncludeFile, ...]:
    """The ``include_files`` entries of *platform*'s overlay, or none."""
    overlay = getattr(config, platform, None)
    return tuple(getattr(overlay, "include_files", ()))


def lock_current(lock, config: Config, platform: str, root: Path) -> bool:
    """``is_in_sync()`` and pins that match the files on disk (§4.3)."""
    from kivyforge.lock.inputs import is_in_sync

    return is_in_sync(lock, config, platform) and pins_current(
        getattr(lock, "include_files", ()), entries_for(config, platform), root
    )


def refresh(
    lock,
    config: Config,
    *,
    project_root: Path,
    platform: str,
    now: datetime | None = None,
):
    """*lock* with its ``include_files`` pins re-hashed from disk.

    Returns *lock* itself when no pin changed. ``lock_inputs_sha256`` records
    an include's paths, not the contents or a directory's files, so an edited
    include leaves the lock in sync while the build refuses to stage it. The
    pins depend on nothing that was resolved, so rewriting them alone is a
    complete re-lock for that change (#176).
    """
    pins = hash_pins(entries_for(config, platform), project_root.resolve())
    if pins == sorted(lock.include_files, key=lambda p: p.key):
        return lock
    return dataclasses.replace(
        lock,
        include_files=tuple(pins),
        generated_at=(now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def pin_changes(
    old: Iterable[LockedIncludeFile], new: Iterable[LockedIncludeFile]
) -> list[str]:
    """``lock`` and ``lock --check`` lines for the pins that differ."""
    before = {p.key: p.sha256 for p in old}
    after = {p.key: p.sha256 for p in new}
    out: list[str] = []
    for key in sorted(before.keys() | after.keys()):
        dest, source = key
        if key not in before:
            change = "added"
        elif key not in after:
            change = "removed"
        elif before[key] != after[key]:
            change = "changed"
        else:
            continue
        out.append(f"  ~ include_files: {source} -> {dest} ({change})")
    return out


# --- placement -------------------------------------------------------------


def refuse_reserved(
    items: Iterable[IncludeItem], reserved: Callable[[IncludeItem], str | None]
) -> None:
    """Raise ``KF-INCLUDE-RESERVED`` with the message *reserved* gives an item."""
    for item in items:
        message = reserved(item)
        if message is not None:
            raise IncludeReserved(message, context=item.context)


#: What a format Xcode compiles has to be included as instead.
_COMPILED_FORMS = {
    ".xcstrings": (
        "a String Catalog, which Xcode compiles to `.strings` tables; include "
        "the compiled `<lang>.lproj/InfoPlist.strings` (or "
        "`<lang>.lproj/Localizable.strings`) files instead"
    ),
    ".storyboard": (
        "a storyboard, which Xcode compiles to `.storyboardc`; include the "
        "compiled form, or use the `splash` key for the launch screen"
    ),
    ".xib": "an interface file, which Xcode compiles to `.nib`; include the `.nib`",
    ".xcassets": (
        "an asset catalog, which Xcode compiles into `Assets.car`; include the "
        "image files themselves, or use the `icons` key"
    ),
}

#: Mach-O magics, as in ``macos/machotools.py``. Fat headers are told apart
#: from a Java class file (also ``0xCAFEBABE``) by their small arch count.
_MACHO_THIN = frozenset({0xFEEDFACE, 0xCEFAEDFE, 0xFEEDFACF, 0xCFFAEDFE})
_MACHO_FAT = {0xCAFEBABE: ">I", 0xBEBAFECA: "<I"}
_AR_MAGIC = b"!<arch>\n"


def native_kind(path: Path) -> str | None:
    """``"a Mach-O file"``, ``"a static archive"``, or ``None`` for data."""
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
    except OSError:
        return None
    if head.startswith(_AR_MAGIC):
        return "a static archive"
    if len(head) < 8:
        return None
    magic = struct.unpack(">I", head[:4])[0]
    if magic in _MACHO_THIN:
        return "a Mach-O file"
    fat = _MACHO_FAT.get(magic)
    if fat is not None and 0 < struct.unpack(fat, head[4:])[0] < 32:
        return "a Mach-O file"
    return None


def refuse_unprocessed(items: Iterable[IncludeItem], *, native_key: str) -> None:
    """iOS and macOS copy an include byte for byte, so refuse what needs more.

    A format Xcode compiles would ship verbatim and do nothing; native code
    belongs in *native_key*, the platform's own channel, which signs it.
    """
    for item in items:
        parts = (*item.source.split("/"), *item.path.split("/"))
        for part in parts:
            suffix = posixpath.splitext(part)[1].casefold()
            if suffix in _COMPILED_FORMS:
                raise IncludeSourceFormat(
                    f"include_files: {item.source} is {_COMPILED_FORMS[suffix]}. "
                    f"Copied as it is, {part} would ship and do nothing.",
                    context=item.context,
                )
        kind = native_kind(item.file)
        if kind is not None:
            raise IncludeNativeCode(
                f"include_files: {item.source} is {kind}, native code, which "
                "include_files copies as data and would leave unsigned.\n"
                f"  Fix: list it under {native_key} instead.",
                context=item.context,
            )


# --- verification and staging ----------------------------------------------


def verify_pins(
    items: Sequence[IncludeItem], pins: Iterable[LockedIncludeFile], *, platform: str
) -> None:
    """Refuse an edited file, a file with no pin, and a pin with no file."""
    recorded = {p.key: p.sha256 for p in pins}
    relock = f"kivyforge lock -p {platform}"
    for item in items:
        sha256 = recorded.get(item.key)
        if sha256 is None:
            raise IncludeDrift(
                f"include_files drift: {item.source} would be staged into "
                f"{item.dest} but the lock records no hash for it.\n"
                f"  Re-run `{relock}` to record it.",
                context=item.context,
            )
        actual = sha256_file(item.file)
        if actual != sha256:
            raise IncludeDrift(
                f"include_files drift: {item.source} has changed since the lock "
                "was written.\n"
                f"  locked:  {sha256}\n"
                f"  on disk: {actual}\n"
                f"  Re-run `{relock}` to accept the new content.",
                context=item.context,
            )
    missing = sorted(recorded.keys() - {item.key for item in items})
    if missing:
        names = ", ".join(source for _dest, source in missing)
        raise IncludeDrift(
            f"include_files drift: the lock records {names}, which no longer "
            "exists.\n"
            f"  Re-run `{relock}` to re-record what the project actually ships.",
            context={"source": missing[0][1]},
        )


def copy_fresh(src: Path, dst: Path) -> None:
    """Copy contents, mode and times, and no extended attributes.

    ``shutil.copy2`` and ``copyfile`` keep ``com.apple.quarantine`` on macOS,
    and ``copystat`` copies extended attributes on Linux. App Store Connect
    refuses a macOS upload with the quarantine attribute on any file.
    """
    dst.unlink(missing_ok=True)
    with src.open("rb") as fin, dst.open("wb") as fout:
        shutil.copyfileobj(fin, fout)
    shutil.copymode(src, dst)
    st = src.stat()
    os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))


def copy_items(
    items: Sequence[IncludeItem],
    root: Path,
    *,
    on_existing: Callable[[str], None] | None = None,
    record: str | None = None,
    copy: Callable[[Path, Path], object] = shutil.copy2,
) -> list[str]:
    """Copy each item to ``root/item.path``; return the paths, once each.

    *on_existing* hears about a file already at the target that this call did
    not write (Android's override note). *record* names a file under *root*
    that lists what was copied, so :func:`remove_recorded` can take it out
    again next build; it is written even when a copy fails part way.
    """
    copied: list[str] = []
    try:
        for item in items:
            target = root / item.path
            if on_existing is not None and target.is_file() and item.path not in copied:
                on_existing(item.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            copy(item.file, target)
            copied.append(item.path)
    finally:
        if record is not None and copied:
            (root / record).write_text(
                "".join(f"{rel}\n" for rel in dict.fromkeys(copied)),
                encoding="utf-8",
                newline="\n",
            )
    return list(dict.fromkeys(copied))


def remove_recorded(root: Path, record: str) -> None:
    """Delete what the last :func:`copy_items` with *record* copied."""
    path = root / record
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        rel = Path(line)
        if not line or rel.is_absolute() or ".." in rel.parts:
            continue
        (root / rel).unlink(missing_ok=True)
    path.unlink()


# --- the built product (§4.8) ----------------------------------------------


@dataclass(frozen=True)
class Mismatch:
    path: str
    source: str
    expected: str
    #: ``None`` when the product has no file at ``path``.
    actual: str | None


def expected_contents(items: Iterable[IncludeItem]) -> dict[str, tuple[str, str]]:
    """``path -> (source, sha256)`` of what staging put there; last copy wins."""
    return {item.path: (item.source, sha256_file(item.file)) for item in items}


def tree_mismatches(expected: dict[str, tuple[str, str]], root: Path) -> list[Mismatch]:
    """Each expected file missing from, or different in, the tree at *root*."""

    def digest(path: str) -> str | None:
        target = root / path
        return sha256_file(target) if target.is_file() else None

    return _mismatches(expected, digest)


def zip_mismatches(
    expected: dict[str, tuple[str, str]], archive: Path, prefix: str
) -> list[Mismatch]:
    """As :func:`tree_mismatches`, over the members under *prefix* of a zip."""
    with zipfile.ZipFile(archive) as zf:
        members = {info.filename: info for info in zf.infolist() if not info.is_dir()}

        def digest(path: str) -> str | None:
            info = members.get(prefix + path)
            if info is None:
                return None
            h = hashlib.sha256()
            with zf.open(info) as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()

        return _mismatches(expected, digest)


def _mismatches(
    expected: dict[str, tuple[str, str]], digest: Callable[[str], str | None]
) -> list[Mismatch]:
    out: list[Mismatch] = []
    for path, (source, sha256) in sorted(expected.items()):
        actual = digest(path)
        if actual != sha256:
            out.append(Mismatch(path, source, sha256, actual))
    return out


def raise_for_mismatches(mismatches: Sequence[Mismatch], *, artifact: str) -> None:
    """``KF-ARTIFACT-CONTENT`` naming every mismatch; context names the first."""
    if not mismatches:
        return
    lines = [
        f"  {m.path} (from {m.source}): "
        + ("missing" if m.actual is None else f"expected {m.expected}, got {m.actual}")
        for m in mismatches
    ]
    first = mismatches[0]
    raise ArtifactContentMismatch(
        f"{artifact} does not hold include_files as staged:\n"
        + "\n".join(lines)
        + "\n  A build tool converted, stripped or dropped the file. kivyforge "
        "copies includes byte for byte; please report this with the build log.",
        context={
            "path": first.path,
            "source": first.source,
            "artifact": artifact,
            "expected": first.expected,
            "actual": first.actual,
        },
    )


# --- doctor ----------------------------------------------------------------


def doctor_check(
    entries: Sequence[IncludeFile],
    pins: Iterable[LockedIncludeFile],
    root: Path,
    *,
    platform: str,
) -> CheckResult:
    """``include_files`` drift as a warning, before ``build`` refuses it."""
    from kivyforge.doctor.result import CheckResult, Status

    if not entries:
        return CheckResult(
            "include_files", Status.SKIP, f"no [[tool.kivy.{platform}.include_files]]"
        )
    recorded = {p.key: p.sha256 for p in pins}
    seen: set[tuple[str, str]] = set()
    drifted: list[str] = []
    for entry in entries:
        for source in entry.sources:
            try:
                items = expand([IncludeFile(dest=entry.dest, sources=(source,))], root)
            except IncludeFilesError:
                seen.add((entry.dest, source))
                drifted.append(f"{source} (missing)")
                continue
            for item in items:
                seen.add(item.key)
                sha256 = recorded.get(item.key)
                if sha256 is None:
                    drifted.append(f"{item.source} (not in the lock)")
                elif sha256 != sha256_file(item.file):
                    drifted.append(f"{item.source} (changed)")
    drifted += [
        f"{source} (deleted)" for _dest, source in sorted(recorded.keys() - seen)
    ]
    if drifted:
        return CheckResult(
            "include_files",
            Status.WARN,
            "drift vs. the lock: " + ", ".join(drifted),
            hint=f"run `kivyforge lock -p {platform}`; the build refuses to stage drift.",
        )
    return CheckResult(
        "include_files", Status.PASS, f"{len(seen)} file(s) match the lock"
    )
