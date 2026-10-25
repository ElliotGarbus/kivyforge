"""Synthetic Mach-O files for hermetic tests of the header reader and resolver.

Each builder writes the bytes dyld would read: a ``mach_header(_64)``, the load
commands the test asks for, and (for a universal file) a fat header in front.
Nothing here is executable; it only has to parse.
"""

from __future__ import annotations

import struct
from pathlib import Path

from kivyforge.platforms.macos import machotools

_COMMANDS = {
    "load": 0xC,
    "weak": 0x18 | 0x80000000,
    "reexport": 0x1F | 0x80000000,
    "lazy": 0x20,
    "upward": 0x23 | 0x80000000,
}
_LC_ID_DYLIB = 0xD
_LC_RPATH = 0x1C | 0x80000000


def _padded(text: str) -> bytes:
    raw = text.encode() + b"\x00"
    return raw + b"\x00" * (-len(raw) % 8)


def thin(
    filetype: int,
    *,
    cpu_type: int = machotools.CPU_TYPE_ARM64,
    deps: tuple[str | tuple[str, str], ...] = (),
    rpaths: tuple[str, ...] = (),
    install_name: str | None = None,
    little_endian: bool = True,
    wide: bool = True,
) -> bytes:
    """A thin Mach-O. A dep is a name, or ``(name, kind)`` with a ``_COMMANDS`` kind."""
    order = "<" if little_endian else ">"
    cmds = b""
    ncmds = 0
    if install_name is not None:
        name = _padded(install_name)
        cmds += struct.pack(order + "6I", _LC_ID_DYLIB, 24 + len(name), 24, 0, 0, 0)
        cmds += name
        ncmds += 1
    for dep in deps:
        dep_name, kind = (dep, "load") if isinstance(dep, str) else dep
        name = _padded(dep_name)
        cmd = _COMMANDS[kind]
        cmds += struct.pack(order + "6I", cmd, 24 + len(name), 24, 0, 0, 0) + name
        ncmds += 1
    for rpath in rpaths:
        path = _padded(rpath)
        cmds += struct.pack(order + "3I", _LC_RPATH, 12 + len(path), 12) + path
        ncmds += 1
    magic = 0xFEEDFACF if wide else 0xFEEDFACE
    header = struct.pack(
        order + "7I", magic, cpu_type, 0, filetype, ncmds, len(cmds), 0
    )
    if wide:
        header += b"\x00\x00\x00\x00"
    return header + cmds


def fat(*slices: bytes, wide: bool = False, little_endian: bool = False) -> bytes:
    """A universal file holding *slices*, each a :func:`thin` result."""
    order = "<" if little_endian else ">"
    magic = 0xCAFEBABF if wide else 0xCAFEBABE
    entry = 32 if wide else 20
    offset = 8 + entry * len(slices)
    offset += -offset % 16
    header = struct.pack(order + "II", magic, len(slices))
    body = b""
    for data in slices:
        cpu_type = machotools.parse_macho(data).slices[0].cpu_type
        start = offset + len(body)
        if wide:
            header += struct.pack(order + "IIQQII", cpu_type, 0, start, len(data), 4, 0)
        else:
            header += struct.pack(order + "5I", cpu_type, 0, start, len(data), 4)
        body += data + b"\x00" * (-len(data) % 16)
    return header + b"\x00" * (offset - len(header)) + body


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def helper(**kwargs) -> bytes:
    return thin(machotools.MH_EXECUTE, **kwargs)


def dylib(name: str, **kwargs) -> bytes:
    kwargs.setdefault("install_name", f"@rpath/{name}")
    return thin(machotools.MH_DYLIB, **kwargs)
