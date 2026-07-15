"""PE machine-type reader + arch verification (hermetic, host-agnostic)."""

from __future__ import annotations

import struct

import pytest

from kivyforge.platforms.windows import petools


def _pe(machine: int) -> bytes:
    """A minimal valid PE header stub with COFF Machine = *machine*."""
    pe_offset = 0x80
    buf = bytearray(pe_offset + 8)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, pe_offset)
    buf[pe_offset : pe_offset + 4] = b"PE\x00\x00"
    struct.pack_into("<H", buf, pe_offset + 4, machine)
    return bytes(buf)


class TestReadMachine:
    def test_amd64(self, tmp_path):
        p = tmp_path / "a.dll"
        p.write_bytes(_pe(petools.IMAGE_FILE_MACHINE_AMD64))
        assert petools.read_pe_machine(p) == 0x8664

    def test_i386(self, tmp_path):
        p = tmp_path / "a.dll"
        p.write_bytes(_pe(petools.IMAGE_FILE_MACHINE_I386))
        assert petools.read_pe_machine(p) == 0x014C

    def test_not_pe_returns_none(self, tmp_path):
        p = tmp_path / "notpe.txt"
        p.write_bytes(b"hello world, not a PE")
        assert petools.read_pe_machine(p) is None

    def test_mz_but_no_pe_sig(self, tmp_path):
        p = tmp_path / "dos.exe"
        buf = bytearray(0x100)
        buf[0:2] = b"MZ"
        struct.pack_into("<I", buf, 0x3C, 0x80)  # points at zeros, no PE sig
        p.write_bytes(bytes(buf))
        assert petools.read_pe_machine(p) is None

    def test_truncated(self, tmp_path):
        p = tmp_path / "t"
        p.write_bytes(b"MZ")
        assert petools.read_pe_machine(p) is None

    def test_is_pe(self, tmp_path):
        p = tmp_path / "a.dll"
        p.write_bytes(_pe(petools.IMAGE_FILE_MACHINE_AMD64))
        assert petools.is_pe(p)
        q = tmp_path / "b.txt"
        q.write_bytes(b"x")
        assert not petools.is_pe(q)


class TestArch:
    def test_machine_for_arch(self):
        assert petools.machine_for_arch("amd64") == 0x8664
        assert petools.machine_for_arch("arm64") == 0xAA64
        assert petools.machine_for_arch("mystery") is None

    def test_verify_matches(self, tmp_path):
        p = tmp_path / "a.dll"
        p.write_bytes(_pe(petools.IMAGE_FILE_MACHINE_AMD64))
        petools.verify_pe_arch(p, "amd64")  # no raise

    def test_verify_mismatch_raises(self, tmp_path):
        p = tmp_path / "x86.dll"
        p.write_bytes(_pe(petools.IMAGE_FILE_MACHINE_I386))
        with pytest.raises(petools.PeArchError, match="x86.*amd64"):
            petools.verify_pe_arch(p, "amd64")

    def test_verify_ignores_non_pe(self, tmp_path):
        p = tmp_path / "data.txt"
        p.write_bytes(b"just data")
        petools.verify_pe_arch(p, "amd64")  # no raise

    def test_verify_unknown_arch_noop(self, tmp_path):
        p = tmp_path / "x86.dll"
        p.write_bytes(_pe(petools.IMAGE_FILE_MACHINE_I386))
        petools.verify_pe_arch(p, "sparc")  # unknown target -> not enforced
