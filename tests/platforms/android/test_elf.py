"""Hermetic ELF reader: LOAD alignment + DT_NEEDED parsing (android/04 §16 KB).

Builds minimal, synthetic ELF32/ELF64 binaries by hand (no real toolchain
needed) to exercise ``read_elf``'s header/program-header/.dynamic parsing.
"""

from __future__ import annotations

import struct
import zipfile

import pytest

from kivyforge.platforms.android.elf import (
    EM_AARCH64,
    EM_X86_64,
    ElfError,
    parse_elf,
    read_elf,
    scan_alignment,
    scan_packaged_libs,
)

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
    machine: int = EM_AARCH64,
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
            + struct.pack(end + "H", machine)
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


#: A minimal library for each ABI the runtime ships.
ARM64_LIB = _make_elf()
X86_64_LIB = _make_elf(machine=EM_X86_64)


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


_SHF_ALLOC = 0x2


def make_sectioned_elf(
    *,
    loads: list[tuple[int, int, int, int]],
    sections: list[tuple[int, int, int, int]],
    phoff: int = 64,
) -> bytes:
    """ELF64 LE with the given program and section headers, no real content.

    ``loads`` are ``(offset, vaddr, filesz, align)``; ``sections`` are
    ``(type, flags, offset, size)``. Only headers are parsed, so the bytes they
    describe are zeros.
    """
    shoff = max(
        [phoff + 0x38 * len(loads)]
        + [off + size for off, _, size, _ in loads]
        + [off + size for _, _, off, size in sections]
    )
    shoff = (shoff + 7) & ~7
    shnum = len(sections) + 1
    header = (
        bytes([0x7F, 0x45, 0x4C, 0x46, 2, 1, 1, 0])
        + b"\x00" * 8
        + struct.pack(
            "<HHIQQQIHHHHHH",
            3, 0xB7, 1, 0, phoff, shoff, 0, 64, 0x38, len(loads), 0x40, shnum, 0,
        )
    )  # fmt: skip
    phdrs = b"".join(
        struct.pack("<IIQQQQQQ", _PT_LOAD, 4, off, va, va, size, size, align)
        for off, va, size, align in loads
    )
    shdrs = b"\x00" * 0x40 + b"".join(
        struct.pack("<IIQQQQIIQQ", 0, typ, flags, 0, off, size, 0, 0, 1, 0)
        for typ, flags, off, size in sections
    )
    body = bytearray(shoff + len(shdrs))
    body[:64] = header
    body[phoff : phoff + len(phdrs)] = phdrs
    body[shoff:] = shdrs
    return bytes(body)


# A linker's layout: loadable sections first, then .comment/.symtab/.strtab.
LINKED = make_sectioned_elf(
    loads=[(0, 0, 0x1000, 0x4000), (0x1000, 0x5000, 0x800, 0x4000)],
    sections=[(1, _SHF_ALLOC, 0x200, 0xE00), (1, _SHF_ALLOC, 0x1000, 0x800),
              (1, 0, 0x1800, 0x100), (2, 0, 0x1900, 0x300)],
)  # fmt: skip
# patchelf's: a new loadable segment appended after the symbol table.
PATCHED = make_sectioned_elf(
    loads=[(0, 0, 0x1000, 0x4000), (0x10000, 0x10000, 0x400, 0x10000)],
    sections=[(1, _SHF_ALLOC, 0x200, 0xE00), (2, 0, 0x1000, 0x300),
              (11, _SHF_ALLOC, 0x10000, 0x400)],
)  # fmt: skip
# What NDK r27's llvm-strip makes of PATCHED: the segment moved, its address not.
STRIPPED = make_sectioned_elf(
    loads=[(0, 0, 0x1000, 0x4000), (0x1078, 0x10000, 0x400, 0x10000)],
    sections=[(1, _SHF_ALLOC, 0x200, 0xE00), (11, _SHF_ALLOC, 0x1078, 0x400)],
)  # fmt: skip


class TestStripSafety:
    def test_a_linkers_layout_is_safe_to_strip(self):
        assert parse_elf(LINKED, name="lib.so").strip_unsafe is False

    def test_a_segment_after_the_symbol_table_is_not(self):
        assert parse_elf(PATCHED, name="lib.so").strip_unsafe is True

    def test_no_section_headers_is_safe(self, tmp_path):
        path = tmp_path / "lib.so"
        path.write_bytes(_make_elf())
        assert read_elf(path).strip_unsafe is False

    def test_a_truncated_file_is_an_elf_error(self):
        with pytest.raises(ElfError, match="truncated"):
            parse_elf(PATCHED[:200], name="lib.so")

    def test_congruent_segments_are_not_misaligned(self):
        assert parse_elf(PATCHED, name="lib.so").misaligned_loads == ()

    def test_a_moved_segment_is_misaligned(self):
        (seg,) = parse_elf(STRIPPED, name="lib.so").misaligned_loads
        assert (seg.offset, seg.vaddr, seg.align) == (0x1078, 0x10000, 0x10000)


class TestScanPackagedLibs:
    def _archive(self, tmp_path, members: dict[str, bytes]):
        path = tmp_path / "app.apk"
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return path

    def test_reports_misaligned_libraries_only(self, tmp_path):
        apk = self._archive(
            tmp_path,
            {
                "lib/arm64-v8a/libgood.so": PATCHED,
                "lib/arm64-v8a/libbad.so": STRIPPED,
                "lib/arm64-v8a/libjunk.so": b"not an elf",
                "assets/_python_bundle/stray.so": STRIPPED,
            },
        )
        bad = scan_packaged_libs(apk)
        assert [member for member, _ in bad] == ["lib/arm64-v8a/libbad.so"]

    def test_reads_an_aab_module(self, tmp_path):
        aab = self._archive(tmp_path, {"base/lib/x86_64/libbad.so": STRIPPED})
        assert [m for m, _ in scan_packaged_libs(aab)] == ["base/lib/x86_64/libbad.so"]

    def test_program_headers_past_the_first_page_are_read(self, tmp_path):
        far = make_sectioned_elf(
            loads=[(0, 0, 0x100, 0x4000), (0x3078, 0x10000, 0x10, 0x10000)],
            sections=[],
            phoff=0x2000,
        )
        apk = self._archive(tmp_path, {"lib/arm64-v8a/libfar.so": far})
        assert [m for m, _ in scan_packaged_libs(apk)] == ["lib/arm64-v8a/libfar.so"]


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
