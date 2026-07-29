"""Hermetic ELF reader: LOAD-segment alignment + DT_NEEDED (android/04 §16 KB).

Pure-Python parsing of the parts kivyforge's doctor needs — no NDK/readelf
dependency, so the 16 KB alignment check runs on any host. Android 15/16 devices
with 16 KB memory pages refuse to load 4 KB-aligned ``.so``s; the check scans
every staged library's LOAD-segment ``p_align`` and flags anything below 16 KB.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

PAGE_16K = 0x4000

_PT_LOAD = 1
_DT_NEEDED = 1
_DT_STRTAB = 5
_DT_NULL = 0


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
class ElfInfo:
    is_64: bool
    max_load_align: int
    needed: tuple[str, ...]
    machine: int = 0

    @property
    def is_16k_aligned(self) -> bool:
        return self.max_load_align >= PAGE_16K


def read_elf(path: Path) -> ElfInfo:
    """Parse an ELF's LOAD alignments + DT_NEEDED; raise ``ElfError`` if not ELF."""
    data = path.read_bytes()
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ElfError(f"{path} is not an ELF file")
    ei_class = data[4]
    little = data[5] == 1
    is_64 = ei_class == 2
    end = "<" if little else ">"
    e_machine = struct.unpack_from(end + "H", data, 0x12)[0]

    if is_64:
        e_phoff = struct.unpack_from(end + "Q", data, 0x20)[0]
        e_phentsize = struct.unpack_from(end + "H", data, 0x36)[0]
        e_phnum = struct.unpack_from(end + "H", data, 0x38)[0]
    else:
        e_phoff = struct.unpack_from(end + "I", data, 0x1C)[0]
        e_phentsize = struct.unpack_from(end + "H", data, 0x2A)[0]
        e_phnum = struct.unpack_from(end + "H", data, 0x2C)[0]

    max_align = 0
    dynamic_off = dynamic_size = 0
    load_segments = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from(end + "I", data, off)[0]
        if is_64:
            p_offset = struct.unpack_from(end + "Q", data, off + 8)[0]
            p_filesz = struct.unpack_from(end + "Q", data, off + 0x20)[0]
            p_align = struct.unpack_from(end + "Q", data, off + 0x30)[0]
            p_vaddr = struct.unpack_from(end + "Q", data, off + 0x10)[0]
        else:
            p_offset = struct.unpack_from(end + "I", data, off + 4)[0]
            p_filesz = struct.unpack_from(end + "I", data, off + 0x10)[0]
            p_align = struct.unpack_from(end + "I", data, off + 0x1C)[0]
            p_vaddr = struct.unpack_from(end + "I", data, off + 8)[0]
        if p_type == _PT_LOAD:
            max_align = max(max_align, p_align)
            load_segments.append((p_offset, p_vaddr, p_filesz))
        elif p_type == 2:  # PT_DYNAMIC
            dynamic_off, dynamic_size = p_offset, p_filesz

    needed = _read_needed(data, end, is_64, dynamic_off, dynamic_size, load_segments)
    return ElfInfo(
        is_64=is_64, max_load_align=max_align, needed=needed, machine=e_machine
    )


def _read_needed(data, end, is_64, dyn_off, dyn_size, load_segments) -> tuple[str, ...]:
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
    strtab_file = _vaddr_to_offset(strtab_vaddr, load_segments)
    if strtab_file is None:
        return ()
    names: list[str] = []
    for str_off in needed_offsets:
        start = strtab_file + str_off
        end_idx = data.find(b"\x00", start)
        if end_idx > start:
            names.append(data[start:end_idx].decode("utf-8", "replace"))
    return tuple(names)


def _vaddr_to_offset(vaddr, load_segments) -> int | None:
    for p_offset, p_vaddr, p_filesz in load_segments:
        if p_vaddr <= vaddr < p_vaddr + p_filesz:
            return p_offset + (vaddr - p_vaddr)
    return None


def scan_alignment(jnilibs_dir: Path) -> list[tuple[Path, int]]:
    """Return ``(path, align)`` for every ``.so`` below 16 KB LOAD alignment."""
    bad: list[tuple[Path, int]] = []
    for so in sorted(jnilibs_dir.rglob("*.so")):
        try:
            info = read_elf(so)
        except (ElfError, OSError, struct.error):
            continue
        if not info.is_16k_aligned:
            bad.append((so, info.max_load_align))
    return bad
