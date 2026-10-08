"""Hermetic ELF reader: LOAD-segment alignment + DT_NEEDED (android/04 §16 KB).

Pure-Python parsing of the parts kivyforge's doctor needs — no NDK/readelf
dependency, so the 16 KB alignment check runs on any host. Android 15/16 devices
with 16 KB memory pages refuse to load 4 KB-aligned ``.so``s; the check scans
every staged library's LOAD-segment ``p_align`` and flags anything below 16 KB.

It also answers two questions about stripping (android/04 §"Stripping"):
whether AGP's strip would corrupt a staged library, and whether a packaged one
already is corrupt.
"""

from __future__ import annotations

import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

PAGE_16K = 0x4000

_PT_LOAD = 1
_DT_NEEDED = 1
_DT_STRTAB = 5
_DT_NULL = 0
_SHF_ALLOC = 0x2
_SHT_NOBITS = 8

# Enough for the ELF header and the program headers of any linker's output.
_HEADER_BYTES = 0x1000

# Native libraries in an APK (lib/<abi>/) or an AAB module (base/lib/<abi>/).
_PACKAGED_LIB = re.compile(r"^(?:[^/]+/)?lib/[^/]+/[^/]+\.so$")


class ElfError(Exception):
    pass


# e_machine values for the two ABIs the python.org runtime ships.
EM_X86_64 = 0x3E
EM_AARCH64 = 0xB7
_MACHINE_NAMES = {
    EM_X86_64: "x86_64",
    EM_AARCH64: "aarch64",
    0x28: "armv7 (32-bit)",
    0x03: "i386 (32-bit)",
}


def machine_name(e_machine: int) -> str:
    return _MACHINE_NAMES.get(e_machine, f"e_machine 0x{e_machine:x}")


@dataclass(frozen=True)
class LoadSegment:
    offset: int
    vaddr: int
    filesz: int
    align: int

    @property
    def misaligned(self) -> bool:
        """Offset and address disagree modulo the alignment.

        The loader maps whole pages, so such a segment is read from the wrong
        file offset: the library fails to load, or loads with garbage in it.
        """
        return self.align > 1 and self.offset % self.align != self.vaddr % self.align


@dataclass(frozen=True)
class ElfInfo:
    is_64: bool
    max_load_align: int
    needed: tuple[str, ...]
    machine: int = 0
    loads: tuple[LoadSegment, ...] = ()
    #: A loadable segment lies after a section stripping removes. NDK r27's
    #: llvm-strip then moves the segment's bytes without keeping its offset
    #: congruent to its address. patchelf, which auditwheel's repair runs,
    #: writes this layout; linkers never do. The layout test is independent of
    #: the NDK: under one whose strip handles it, keeping such a library whole
    #: only costs its symbols' size.
    strip_unsafe: bool = False

    @property
    def is_16k_aligned(self) -> bool:
        return self.max_load_align >= PAGE_16K

    @property
    def misaligned_loads(self) -> tuple[LoadSegment, ...]:
        return tuple(seg for seg in self.loads if seg.misaligned)


def read_elf(path: Path) -> ElfInfo:
    """Parse an ELF's LOAD alignments + DT_NEEDED; raise ``ElfError`` if not ELF."""
    return parse_elf(path.read_bytes(), name=str(path))


def parse_elf(data: bytes, *, name: str) -> ElfInfo:
    try:
        return _parse(data, name)
    except struct.error as exc:
        raise ElfError(f"{name} is a truncated ELF file") from exc


def _parse(data: bytes, name: str) -> ElfInfo:
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ElfError(f"{name} is not an ELF file")
    is_64 = data[4] == 2
    end = "<" if data[5] == 1 else ">"
    e_machine = struct.unpack_from(end + "H", data, 0x12)[0]
    loads, dynamic = _program_headers(data, end, is_64)
    needed = _read_needed(data, end, is_64, *dynamic, loads)
    return ElfInfo(
        is_64=is_64,
        max_load_align=max((seg.align for seg in loads), default=0),
        needed=needed,
        machine=e_machine,
        loads=loads,
        strip_unsafe=_strip_unsafe(data, end, is_64, loads),
    )


def _program_headers(
    data: bytes, end: str, is_64: bool
) -> tuple[tuple[LoadSegment, ...], tuple[int, int]]:
    """The LOAD segments, and the PT_DYNAMIC ``(offset, size)``."""
    if is_64:
        e_phoff = struct.unpack_from(end + "Q", data, 0x20)[0]
        e_phentsize = struct.unpack_from(end + "H", data, 0x36)[0]
        e_phnum = struct.unpack_from(end + "H", data, 0x38)[0]
    else:
        e_phoff = struct.unpack_from(end + "I", data, 0x1C)[0]
        e_phentsize = struct.unpack_from(end + "H", data, 0x2A)[0]
        e_phnum = struct.unpack_from(end + "H", data, 0x2C)[0]

    loads: list[LoadSegment] = []
    dynamic = (0, 0)
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from(end + "I", data, off)[0]
        if is_64:
            p_offset = struct.unpack_from(end + "Q", data, off + 8)[0]
            p_vaddr = struct.unpack_from(end + "Q", data, off + 0x10)[0]
            p_filesz = struct.unpack_from(end + "Q", data, off + 0x20)[0]
            p_align = struct.unpack_from(end + "Q", data, off + 0x30)[0]
        else:
            p_offset = struct.unpack_from(end + "I", data, off + 4)[0]
            p_vaddr = struct.unpack_from(end + "I", data, off + 8)[0]
            p_filesz = struct.unpack_from(end + "I", data, off + 0x10)[0]
            p_align = struct.unpack_from(end + "I", data, off + 0x1C)[0]
        if p_type == _PT_LOAD:
            loads.append(LoadSegment(p_offset, p_vaddr, p_filesz, p_align))
        elif p_type == 2:  # PT_DYNAMIC
            dynamic = (p_offset, p_filesz)
    return tuple(loads), dynamic


def _strip_unsafe(
    data: bytes, end: str, is_64: bool, loads: tuple[LoadSegment, ...]
) -> bool:
    if is_64:
        e_shoff = struct.unpack_from(end + "Q", data, 0x28)[0]
        e_shentsize = struct.unpack_from(end + "H", data, 0x3A)[0]
        e_shnum = struct.unpack_from(end + "H", data, 0x3C)[0]
        fields = end + "IIQQQQ"
    else:
        e_shoff = struct.unpack_from(end + "I", data, 0x20)[0]
        e_shentsize = struct.unpack_from(end + "H", data, 0x2E)[0]
        e_shnum = struct.unpack_from(end + "H", data, 0x30)[0]
        fields = end + "IIIIII"
    if not e_shoff:
        return False
    first_unallocated: int | None = None
    for i in range(1, e_shnum):
        _, sh_type, sh_flags, _, sh_offset, sh_size = struct.unpack_from(
            fields, data, e_shoff + i * e_shentsize
        )
        if sh_flags & _SHF_ALLOC or sh_type == _SHT_NOBITS or not sh_size:
            continue
        if first_unallocated is None or sh_offset < first_unallocated:
            first_unallocated = sh_offset
    if first_unallocated is None:
        return False
    return any(seg.filesz and seg.offset > first_unallocated for seg in loads)


def _read_needed(
    data, end, is_64, dyn_off, dyn_size, loads: tuple[LoadSegment, ...]
) -> tuple[str, ...]:
    if not dyn_off:
        return ()
    entry = 16 if is_64 else 8
    fmt = end + ("qQ" if is_64 else "iI")
    strtab_vaddr = 0
    needed_offsets: list[int] = []
    for i in range(dyn_size // entry):
        tag, val = struct.unpack_from(fmt, data, dyn_off + i * entry)
        if tag == _DT_NULL:
            break
        if tag == _DT_STRTAB:
            strtab_vaddr = val
        elif tag == _DT_NEEDED:
            needed_offsets.append(val)
    if not strtab_vaddr:
        return ()
    strtab_file = _vaddr_to_offset(strtab_vaddr, loads)
    if strtab_file is None:
        return ()
    names: list[str] = []
    for str_off in needed_offsets:
        start = strtab_file + str_off
        end_idx = data.find(b"\x00", start)
        if end_idx > start:
            names.append(data[start:end_idx].decode("utf-8", "replace"))
    return tuple(names)


def _vaddr_to_offset(vaddr, loads: tuple[LoadSegment, ...]) -> int | None:
    for seg in loads:
        if seg.vaddr <= vaddr < seg.vaddr + seg.filesz:
            return seg.offset + (vaddr - seg.vaddr)
    return None


def scan_alignment(jnilibs_dir: Path) -> list[tuple[Path, int]]:
    """Return ``(path, align)`` for every ``.so`` below 16 KB LOAD alignment."""
    bad: list[tuple[Path, int]] = []
    for so in sorted(jnilibs_dir.rglob("*.so")):
        try:
            info = read_elf(so)
        except (ElfError, OSError):
            continue
        if not info.is_16k_aligned:
            bad.append((so, info.max_load_align))
    return bad


def scan_packaged_libs(archive: Path) -> list[tuple[str, LoadSegment]]:
    """Return ``(member, segment)`` for each misaligned LOAD in an APK or AAB."""
    bad: list[tuple[str, LoadSegment]] = []
    with zipfile.ZipFile(archive) as zf:
        for member in sorted(zf.namelist()):
            if not _PACKAGED_LIB.match(member):
                continue
            with zf.open(member) as fh:
                data = fh.read(_HEADER_BYTES)
            if len(data) < 64 or data[:4] != b"\x7fELF":
                continue
            end, is_64 = ("<" if data[5] == 1 else ">"), data[4] == 2
            try:
                loads, _ = _program_headers(data, end, is_64)
            except struct.error:
                # patchelf can move the program headers to the end of the file.
                try:
                    loads, _ = _program_headers(zf.read(member), end, is_64)
                except struct.error as exc:
                    raise ElfError(
                        f"{member} in {archive.name} is a truncated ELF file"
                    ) from exc
            bad.extend((member, seg) for seg in loads if seg.misaligned)
    return bad
