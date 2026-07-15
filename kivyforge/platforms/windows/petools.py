"""Minimal PE (Portable Executable) machine-type reader (windows-spec).

The PE analog of Linux ``elftools`` / macOS ``machotools``: a tiny, pure-Python
reader of the COFF header ``Machine`` field so a wrong-architecture DLL/EXE
staged into an amd64 app is caught with a clear message instead of a cryptic
load failure at runtime. Pure-Python (no ``ctypes``/OS APIs), so it runs on any
host and in hermetic unit tests.

Layout walked: ``MZ`` DOS signature at offset 0, the 4-byte PE-header offset at
``0x3C``, the ``PE\\0\\0`` signature there, then the COFF header whose first
field is the 2-byte little-endian ``Machine``.
"""

from __future__ import annotations

import struct
from pathlib import Path

# IMAGE_FILE_MACHINE_* values (winnt.h).
IMAGE_FILE_MACHINE_I386 = 0x014C
IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_FILE_MACHINE_ARM64 = 0xAA64
IMAGE_FILE_MACHINE_ARMNT = 0x01C4

# kivyforge arch name -> expected PE machine.
_ARCH_MACHINE = {
    "amd64": IMAGE_FILE_MACHINE_AMD64,
    "arm64": IMAGE_FILE_MACHINE_ARM64,
}

_MACHINE_NAME = {
    IMAGE_FILE_MACHINE_I386: "x86 (i386)",
    IMAGE_FILE_MACHINE_AMD64: "x64 (amd64)",
    IMAGE_FILE_MACHINE_ARM64: "arm64",
    IMAGE_FILE_MACHINE_ARMNT: "arm (32-bit)",
}


def machine_name(machine: int) -> str:
    """A human label for a PE ``Machine`` value (hex fallback if unknown)."""
    return _MACHINE_NAME.get(machine, f"0x{machine:04x}")


def machine_for_arch(arch: str) -> int | None:
    """The expected PE ``Machine`` for a kivyforge *arch* (``None`` if unknown)."""
    return _ARCH_MACHINE.get(arch)


def read_pe_machine(path: Path) -> int | None:
    """Return the PE ``Machine`` value of *path*, or ``None`` if it is not a PE.

    Reads only the headers; never loads the file. Non-PE files (a ``.txt`` in a
    zip, a truncated stub) return ``None`` so callers can skip them.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(0x40)
            if len(head) < 0x40 or head[:2] != b"MZ":
                return None
            pe_offset = struct.unpack_from("<I", head, 0x3C)[0]
            fh.seek(pe_offset)
            sig = fh.read(6)  # "PE\0\0" + first 2 bytes of Machine
            if len(sig) < 6 or sig[:4] != b"PE\x00\x00":
                return None
            return struct.unpack_from("<H", sig, 4)[0]
    except OSError:
        return None


def is_pe(path: Path) -> bool:
    """Whether *path* is a PE image (has a valid MZ + PE signature)."""
    return read_pe_machine(path) is not None


class PeArchError(Exception):
    """A staged PE image does not match the target architecture."""


def verify_pe_arch(path: Path, arch: str) -> None:
    """Raise :class:`PeArchError` if *path* is a PE for a different *arch*.

    Non-PE files are ignored (a native-binary channel may carry data files or
    scripts). Unknown target archs are not enforced (forward-compat).
    """
    expected = machine_for_arch(arch)
    if expected is None:
        return
    machine = read_pe_machine(path)
    if machine is None or machine == expected:
        return
    raise PeArchError(
        f"{path.name} is a {machine_name(machine)} PE image, but the app targets "
        f"{arch} ({machine_name(expected)}).\n"
        "  Ship the matching-architecture binary in "
        "[tool.kivy.windows.native.binaries]."
    )
