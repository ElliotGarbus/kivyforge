"""Launcher build determinism guards (hermetic — no MSVC, no Windows host).

The cross-machine half of launcher reproducibility rests on the linker omitting
the PE "rich header" (``/EMITTOOLVERSIONINFO:NO``): it stamps the *serviced*
``cl``/``link`` build, which differs between runner images that share one
``VCTOOLSVERSION``. These cover the detector that asserts the flag took effect;
the byte-compare against the vendored binary is the CI ``verify`` gate.
"""

from __future__ import annotations

import struct

import pytest

from kivyforge.platforms.windows.launcher import build_launcher


def _pe(*, rich: bool) -> bytes:
    """A minimal PE stub, with or without a rich header before ``e_lfanew``."""
    stub = b"\x0e\x1fThis program cannot be run in DOS mode.\r\r\n$" + b"\x00" * 7
    tail = b"DanS" + b"\x00" * 12 + b"Rich" + b"\x00" * 4 if rich else b""
    pe_offset = 0x40 + len(stub) + len(tail)
    buf = bytearray(pe_offset + 8)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, pe_offset)
    buf[0x40 : 0x40 + len(stub)] = stub
    buf[0x40 + len(stub) : pe_offset] = tail
    buf[pe_offset : pe_offset + 4] = b"PE\x00\x00"
    return bytes(buf)


class TestHasToolVersionStamp:
    def test_detects_rich_header(self):
        assert build_launcher.has_tool_version_stamp(_pe(rich=True))

    def test_clean_image(self):
        assert not build_launcher.has_tool_version_stamp(_pe(rich=False))

    def test_ignores_rich_after_the_pe_signature(self):
        """Only the DOS-stub gap counts — 'Rich' in section data is not a stamp."""
        image = _pe(rich=False) + b"....Rich...."
        assert not build_launcher.has_tool_version_stamp(image)

    @pytest.mark.parametrize("image", [b"", b"MZ", b"not a pe at all"])
    def test_truncated_or_non_pe(self, image):
        assert not build_launcher.has_tool_version_stamp(image)

    def test_out_of_range_e_lfanew(self):
        buf = bytearray(0x80)
        buf[0:2] = b"MZ"
        struct.pack_into("<I", buf, 0x3C, 0xDEADBEEF)
        assert not build_launcher.has_tool_version_stamp(bytes(buf))


class TestRejectToolVersionStamp:
    def test_raises_on_stamped_image(self):
        with pytest.raises(build_launcher.LauncherBuildError, match="rich"):
            build_launcher._reject_tool_version_stamp(_pe(rich=True), "test binary")

    def test_passes_clean_image(self):
        build_launcher._reject_tool_version_stamp(_pe(rich=False), "test binary")


class TestDeterministicFlags:
    def test_link_flags_drop_the_tool_version_stamp(self):
        """The flag that makes the binary reproducible across runner images."""
        assert "/EMITTOOLVERSIONINFO:NO" in build_launcher._LINK_FLAGS

    def test_link_flags_keep_brepro_and_release(self):
        assert "/Brepro" in build_launcher._LINK_FLAGS
        assert "/RELEASE" in build_launcher._LINK_FLAGS

    def test_compile_flags_keep_brepro(self):
        assert "/Brepro" in build_launcher._CL_FLAGS
