"""A tiny, hermetic ELF header reader (the ELF analog of ``machotools``).

``doctor`` uses this to confirm a staged native binary matches the AppImage's
target arch: a 32-bit or aarch64 ``.so`` in an x86_64 AppImage only fails at
``dlopen`` time with a cryptic message, so it is caught here from the header.

Pure-Python, no ``readelf`` dependency, so the check works on any host and in
unit tests. The endianness matters: ``e_machine`` is a 16-bit field whose byte
order is given by ``EI_DATA`` (``e_ident[5]``), so hard-coding little-endian
would misread a big-endian (mis-supplied) artifact — exactly the case this
check exists to catch.
"""

from __future__ import annotations

import struct
from pathlib import Path

ELF_MAGIC = b"\x7fELF"

# EI_CLASS (e_ident[4]).
ELFCLASS32 = 1
ELFCLASS64 = 2

# EI_DATA (e_ident[5]).
ELFDATA2LSB = 1
ELFDATA2MSB = 2

# e_machine values kivyforge maps its arches to.
EM_386 = 3
EM_X86_64 = 62
EM_AARCH64 = 183

# kivyforge arch -> (EI_CLASS, e_machine). aarch64 is deferred at the backend
# level but listed so the arch check is purely additive when it lands.
ARCH_ELF: dict[str, tuple[int, int]] = {
    "x86_64": (ELFCLASS64, EM_X86_64),
    "aarch64": (ELFCLASS64, EM_AARCH64),
}

_CLASS_NAMES = {ELFCLASS32: "ELF32", ELFCLASS64: "ELF64"}
_MACHINE_NAMES = {EM_386: "i386", EM_X86_64: "x86_64", EM_AARCH64: "aarch64"}


class ElfError(Exception):
    """The file is not a readable ELF header."""


def is_elf(path: Path) -> bool:
    """True if *path* is a regular (non-symlink) file starting with ``\\x7fELF``.

    Mirrors ``is_macho``: a non-ELF helper (e.g. a ``#!/bin/sh`` script) is
    skipped by the arch check rather than failed for "not being x86_64".
    """
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    return head == ELF_MAGIC


def elf_machine(path: Path) -> tuple[int, int]:
    """Return ``(EI_CLASS, e_machine)`` for the ELF at *path*.

    Decodes the 16-bit ``e_machine`` (offset 18) using the endianness named by
    ``EI_DATA`` (offset 5). Raises :class:`ElfError` if *path* is not a readable
    ELF header.
    """
    try:
        with path.open("rb") as fh:
            header = fh.read(20)
    except OSError as exc:
        raise ElfError(f"cannot read {path}: {exc}") from exc
    if len(header) < 20 or header[:4] != ELF_MAGIC:
        raise ElfError(f"{path} is not an ELF file")
    ei_class = header[4]
    ei_data = header[5]
    if ei_data == ELFDATA2LSB:
        endian = "<"
    elif ei_data == ELFDATA2MSB:
        endian = ">"
    else:
        raise ElfError(f"{path} has an invalid EI_DATA byte {ei_data!r}")
    (e_machine,) = struct.unpack(f"{endian}H", header[18:20])
    return ei_class, e_machine


def describe(elf_class: int, e_machine: int) -> str:
    """A short human label for an ``(EI_CLASS, e_machine)`` pair."""
    cls = _CLASS_NAMES.get(elf_class, f"class{elf_class}")
    mach = _MACHINE_NAMES.get(e_machine, f"machine{e_machine}")
    return f"{mach} ({cls})"
