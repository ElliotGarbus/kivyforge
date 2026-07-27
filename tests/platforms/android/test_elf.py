"""Hermetic ELF reader: LOAD alignment + DT_NEEDED parsing (android/04 §16 KB).

Builds minimal, synthetic ELF32/ELF64 binaries by hand (no real toolchain
needed) to exercise ``read_elf``'s header/program-header/.dynamic parsing.
"""

from __future__ import annotations

import struct

import pytest

from kivyforge.platforms.android.elf import ElfError, read_elf, scan_alignment

_DT_NEEDED = 1
_DT_STRTAB = 5
_DT_NULL = 0
_PT_LOAD = 1
_PT_DYNAMIC = 2


def _make_elf(
    *,
    is_64: bool = True,
    little: bool = True,
    align: int = 0x4000,
    needed: tuple[str, ...] = (),
    include_dynamic: bool = True,
    include_strtab: bool = True,
    strtab_vaddr_override: int | None = None,
) -> bytes:
    """Hand-assemble a minimal ELF: one PT_LOAD (whole file, identity
    vaddr==offset) plus, optionally, a PT_DYNAMIC segment with DT_NEEDED/
    DT_STRTAB entries pointing at a real string table appended at the end.
    """
    end = "<" if little else ">"
    ehsize = 64 if is_64 else 52
    phentsize = 0x38 if is_64 else 0x20
    phnum = 2 if include_dynamic else 1
    phoff = ehsize

    ei_class = 2 if is_64 else 1
    ei_data = 1 if little else 2
    e_ident = bytes([0x7F, 0x45, 0x4C, 0x46, ei_class, ei_data, 1, 0]) + b"\x00" * 8

    if is_64:
        header = (
            e_ident
            + struct.pack(end + "H", 3)  # e_type: ET_DYN
            + struct.pack(end + "H", 0xB7)  # e_machine: AArch64
            + struct.pack(end + "I", 1)  # e_version
            + struct.pack(end + "Q", 0)  # e_entry
            + struct.pack(end + "Q", phoff)  # e_phoff
            + struct.pack(end + "Q", 0)  # e_shoff
            + struct.pack(end + "I", 0)  # e_flags
            + struct.pack(end + "H", ehsize)
            + struct.pack(end + "H", phentsize)
            + struct.pack(end + "H", phnum)
            + struct.pack(end + "H", 0)  # e_shentsize
            + struct.pack(end + "H", 0)  # e_shnum
            + struct.pack(end + "H", 0)  # e_shstrndx
        )
    else:
        header = (
            e_ident
            + struct.pack(end + "H", 3)
            + struct.pack(end + "H", 0x28)  # ARM
            + struct.pack(end + "I", 1)
            + struct.pack(end + "I", 0)  # e_entry
            + struct.pack(end + "I", phoff)  # e_phoff
            + struct.pack(end + "I", 0)  # e_shoff
            + struct.pack(end + "I", 0)
            + struct.pack(end + "H", ehsize)
            + struct.pack(end + "H", phentsize)
            + struct.pack(end + "H", phnum)
            + struct.pack(end + "H", 0)
            + struct.pack(end + "H", 0)
            + struct.pack(end + "H", 0)
        )
    assert len(header) == ehsize

    # Build the trailing payload (dynamic table + strtab) first so we know
    # the total file size before writing the identity-mapped PT_LOAD.
    dyn_fmt = end + ("qQ" if is_64 else "iI")
    payload_start = ehsize + phentsize * phnum

    strtab = b"\x00"
    name_offsets = []
    for name in needed:
        name_offsets.append(len(strtab))
        strtab += name.encode("ascii") + b"\x00"
    strtab_off = payload_start

    dyn_entries = []
    if include_strtab:
        strtab_vaddr = (
            strtab_off if strtab_vaddr_override is None else strtab_vaddr_override
        )
        dyn_entries.append((_DT_STRTAB, strtab_vaddr))
    for off in name_offsets:
        dyn_entries.append((_DT_NEEDED, off))
    dyn_entries.append((_DT_NULL, 0))
    dyn_bytes = b"".join(struct.pack(dyn_fmt, tag, val) for tag, val in dyn_entries)
    dyn_off = strtab_off + len(strtab)

    total_size = dyn_off + len(dyn_bytes)

    phdrs = b""
    if is_64:
        phdrs += struct.pack(
            end + "IIQQQQQQ",
            _PT_LOAD,
            5,
            0,
            0,
            0,
            total_size,
            total_size,
            align,
        )
        if include_dynamic:
            phdrs += struct.pack(
                end + "IIQQQQQQ",
                _PT_DYNAMIC,
                6,
                dyn_off,
                dyn_off,
                dyn_off,
                len(dyn_bytes),
                len(dyn_bytes),
                8,
            )
    else:
        phdrs += struct.pack(
            end + "IIIIIIII",
            _PT_LOAD,
            0,
            0,
            0,
            total_size,
            total_size,
            5,
            align,
        )
        if include_dynamic:
            phdrs += struct.pack(
                end + "IIIIIIII",
                _PT_DYNAMIC,
                dyn_off,
                dyn_off,
                dyn_off,
                len(dyn_bytes),
                len(dyn_bytes),
                6,
                4,
            )

    body = header + phdrs
    body += b"\x00" * (strtab_off - len(body))
    body += strtab
    body += dyn_bytes
    assert len(body) == total_size
    return body


class TestReadElfHeaderParsing:
    def test_too_short_raises(self, tmp_path):
        path = tmp_path / "tiny.so"
        path.write_bytes(b"\x7fELF" + b"\x00" * 10)
        with pytest.raises(ElfError, match="not an ELF file"):
            read_elf(path)

    def test_bad_magic_raises(self, tmp_path):
        path = tmp_path / "notelf.so"
        path.write_bytes(b"NOTELF\x00" + b"\x00" * 60)
        with pytest.raises(ElfError, match="not an ELF file"):
            read_elf(path)

    def test_64bit_little_endian_parsed(self, tmp_path):
        path = tmp_path / "lib.so"
        path.write_bytes(_make_elf(is_64=True, little=True, align=0x4000))
        info = read_elf(path)
        assert info.is_64 is True
        assert info.max_load_align == 0x4000
        assert info.is_16k_aligned is True

    def test_32bit_little_endian_parsed(self, tmp_path):
        path = tmp_path / "lib32.so"
        path.write_bytes(_make_elf(is_64=False, little=True, align=0x1000))
        info = read_elf(path)
        assert info.is_64 is False
        assert info.max_load_align == 0x1000
        assert info.is_16k_aligned is False

    def test_64bit_big_endian_parsed(self, tmp_path):
        path = tmp_path / "libbe.so"
        path.write_bytes(_make_elf(is_64=True, little=False, align=0x4000))
        info = read_elf(path)
        assert info.is_64 is True
        assert info.max_load_align == 0x4000

    def test_4k_alignment_flagged_not_16k(self, tmp_path):
        path = tmp_path / "lib4k.so"
        path.write_bytes(_make_elf(align=0x1000))
        info = read_elf(path)
        assert info.is_16k_aligned is False

    def test_16k_alignment_ok(self, tmp_path):
        path = tmp_path / "lib16k.so"
        path.write_bytes(_make_elf(align=0x4000))
        info = read_elf(path)
        assert info.is_16k_aligned is True


class TestDtNeeded:
    def test_needed_names_extracted(self, tmp_path):
        path = tmp_path / "lib.so"
        path.write_bytes(_make_elf(needed=("libSDL2.so", "liblog.so")))
        info = read_elf(path)
        assert info.needed == ("libSDL2.so", "liblog.so")

    def test_no_dynamic_segment_yields_empty(self, tmp_path):
        path = tmp_path / "static.so"
        path.write_bytes(_make_elf(include_dynamic=False))
        info = read_elf(path)
        assert info.needed == ()

    def test_no_strtab_tag_yields_empty(self, tmp_path):
        path = tmp_path / "nostrtab.so"
        path.write_bytes(_make_elf(needed=("libfoo.so",), include_strtab=False))
        info = read_elf(path)
        assert info.needed == ()

    def test_32bit_needed_names_extracted(self, tmp_path):
        path = tmp_path / "lib32.so"
        path.write_bytes(_make_elf(is_64=False, needed=("libc.so",)))
        info = read_elf(path)
        assert info.needed == ("libc.so",)

    def test_strtab_vaddr_outside_any_load_segment_yields_empty(self, tmp_path):
        # DT_STRTAB pointing at a vaddr no PT_LOAD covers: _vaddr_to_offset
        # returns None, so the (unmappable) needed names are silently dropped
        # rather than crashing the doctor scan.
        path = tmp_path / "badstrtab.so"
        path.write_bytes(
            _make_elf(needed=("libfoo.so",), strtab_vaddr_override=0x7FFFFFFF)
        )
        info = read_elf(path)
        assert info.needed == ()


class TestScanAlignment:
    def test_flags_only_sub_16k_libraries(self, tmp_path):
        good = tmp_path / "good.so"
        good.write_bytes(_make_elf(align=0x4000))
        bad = tmp_path / "bad.so"
        bad.write_bytes(_make_elf(align=0x1000))
        garbage = tmp_path / "garbage.so"
        garbage.write_bytes(b"not an elf at all, just junk bytes here")

        results = scan_alignment(tmp_path)
        assert results == [(bad, 0x1000)]

    def test_no_so_files_returns_empty(self, tmp_path):
        assert scan_alignment(tmp_path) == []

    def test_scans_nested_directories(self, tmp_path):
        nested = tmp_path / "arm64-v8a"
        nested.mkdir()
        bad = nested / "libbad.so"
        bad.write_bytes(_make_elf(align=0x1000))
        assert scan_alignment(tmp_path) == [(bad, 0x1000)]
