"""Hermetic ELF header reader (is_elf / elf_machine, endianness-aware)."""

from __future__ import annotations

import struct

import pytest

from kivyforge.platforms.linux import elftools


def _elf_bytes(*, elf_class=2, ei_data=1, e_machine=62, size=64) -> bytes:
    header = bytearray(size)
    header[0:4] = b"\x7fELF"
    header[4] = elf_class
    header[5] = ei_data
    endian = "<" if ei_data == 1 else ">"
    struct.pack_into(f"{endian}H", header, 18, e_machine)
    return bytes(header)


class TestIsElf:
    def test_true_for_elf(self, tmp_path):
        p = tmp_path / "lib.so"
        p.write_bytes(_elf_bytes())
        assert elftools.is_elf(p)

    def test_false_for_script(self, tmp_path):
        p = tmp_path / "helper"
        p.write_bytes(b"#!/bin/sh\n")
        assert not elftools.is_elf(p)

    def test_false_for_missing(self, tmp_path):
        assert not elftools.is_elf(tmp_path / "absent")

    def test_false_for_symlink(self, tmp_path):
        target = tmp_path / "lib.so"
        target.write_bytes(_elf_bytes())
        link = tmp_path / "link.so"
        link.symlink_to(target)
        assert not elftools.is_elf(link)


class TestElfMachine:
    def test_x86_64_little_endian(self, tmp_path):
        p = tmp_path / "lib.so"
        p.write_bytes(_elf_bytes(elf_class=2, ei_data=1, e_machine=62))
        assert elftools.elf_machine(p) == (elftools.ELFCLASS64, elftools.EM_X86_64)

    def test_big_endian_machine_decoded_correctly(self, tmp_path):
        # A big-endian ELF's e_machine must be read with big-endian byte order;
        # hard-coding little-endian would misread 62 as 0x3E00.
        p = tmp_path / "be.so"
        p.write_bytes(_elf_bytes(elf_class=2, ei_data=2, e_machine=62))
        assert elftools.elf_machine(p) == (elftools.ELFCLASS64, elftools.EM_X86_64)

    def test_aarch64(self, tmp_path):
        p = tmp_path / "lib.so"
        p.write_bytes(_elf_bytes(e_machine=elftools.EM_AARCH64))
        assert elftools.elf_machine(p) == (elftools.ELFCLASS64, elftools.EM_AARCH64)

    def test_32bit_class(self, tmp_path):
        p = tmp_path / "lib.so"
        p.write_bytes(_elf_bytes(elf_class=1, e_machine=elftools.EM_386))
        assert elftools.elf_machine(p) == (elftools.ELFCLASS32, elftools.EM_386)

    def test_non_elf_raises(self, tmp_path):
        p = tmp_path / "helper"
        p.write_bytes(b"#!/bin/sh\n")
        with pytest.raises(elftools.ElfError, match="not an ELF"):
            elftools.elf_machine(p)

    def test_truncated_raises(self, tmp_path):
        p = tmp_path / "short"
        p.write_bytes(b"\x7fELF")
        with pytest.raises(elftools.ElfError):
            elftools.elf_machine(p)

    def test_invalid_ei_data_raises(self, tmp_path):
        p = tmp_path / "bad"
        data = bytearray(_elf_bytes())
        data[5] = 9  # invalid EI_DATA
        p.write_bytes(bytes(data))
        with pytest.raises(elftools.ElfError, match="EI_DATA"):
            elftools.elf_machine(p)


class TestDescribe:
    def test_known(self):
        assert elftools.describe(elftools.ELFCLASS64, elftools.EM_X86_64) == (
            "x86_64 (ELF64)"
        )

    def test_unknown(self):
        assert "class9" in elftools.describe(9, 999)
        assert "machine999" in elftools.describe(9, 999)
