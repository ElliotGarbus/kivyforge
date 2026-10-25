"""Mach-O detection + tool wrappers (hermetic; Apple tools are faked)."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

from kivyforge.platforms.macos import AppBundleError, machotools
from tests.platforms.macos import macho_fixtures as mf


def _write_magic(path, magic: int) -> None:
    path.write_bytes(struct.pack(">I", magic) + b"\x00\x00\x00\x00")


class TestIsMacho:
    def test_detects_macho_magics(self, tmp_path):
        for magic in (0xFEEDFACE, 0xFEEDFACF, 0xCAFEBABE, 0xCFFAEDFE):
            f = tmp_path / f"bin_{magic:x}"
            _write_magic(f, magic)
            assert machotools.is_macho(f)

    def test_rejects_text_short_and_dirs(self, tmp_path):
        text = tmp_path / "a.txt"
        text.write_text("hello world")
        assert not machotools.is_macho(text)

        short = tmp_path / "short"
        short.write_bytes(b"\x01\x02")
        assert not machotools.is_macho(short)

        assert not machotools.is_macho(tmp_path)

    @pytest.mark.requires_symlinks
    def test_rejects_symlink(self, tmp_path):
        real = tmp_path / "real"
        _write_magic(real, 0xFEEDFACF)
        link = tmp_path / "link"
        link.symlink_to(real)
        assert not machotools.is_macho(link)


def _thin_macho_64(cpu_type: int, *, little_endian: bool = True) -> bytes:
    """The first 8 bytes of a thin 64-bit Mach-O: magic + cpu_type.

    Both fields of a real mach_header_64 are written in the *same* byte
    order, so this packs ``MH_MAGIC_64`` (0xfeedfacf) and *cpu_type* with the
    same ``order`` — for a little-endian file (every real arm64/x86_64 Mach-O)
    that magic serializes to the bytes ``read_macho_cpu_type`` recognizes as
    ``MH_CIGAM_64``, exactly like a real binary on disk.
    """
    order = "<" if little_endian else ">"
    return struct.pack(order + "II", machotools._MH_MAGIC_64, cpu_type)


class TestReadMachoCpuType:
    def test_reads_arm64_little_endian(self):
        # A real macOS binary: little-endian on disk, which reads as
        # MH_CIGAM_64 under the big-endian magic check.
        data = _thin_macho_64(machotools.CPU_TYPE_ARM64, little_endian=True)
        assert machotools.read_macho_cpu_type(data) == machotools.CPU_TYPE_ARM64

    def test_reads_x86_64_little_endian(self):
        data = _thin_macho_64(machotools.CPU_TYPE_X86_64, little_endian=True)
        assert machotools.read_macho_cpu_type(data) == machotools.CPU_TYPE_X86_64

    def test_reads_big_endian_too(self):
        data = _thin_macho_64(machotools.CPU_TYPE_ARM64, little_endian=False)
        assert machotools.read_macho_cpu_type(data) == machotools.CPU_TYPE_ARM64

    def test_rejects_non_macho(self):
        with pytest.raises(machotools.MachoError, match="not a thin 64-bit"):
            machotools.read_macho_cpu_type(b"not a macho at all!!")

    def test_rejects_too_short(self):
        with pytest.raises(machotools.MachoError, match="too short"):
            machotools.read_macho_cpu_type(b"\x00\x00\x00")

    def test_rejects_32_bit_magic(self):
        # MH_MAGIC (32-bit) is deliberately unsupported.
        data = struct.pack(">II", 0xFEEDFACE, machotools.CPU_TYPE_ARM64)
        with pytest.raises(machotools.MachoError, match="not a thin 64-bit"):
            machotools.read_macho_cpu_type(data)


class TestCpuTypeName:
    def test_known_types(self):
        assert machotools.cpu_type_name(machotools.CPU_TYPE_ARM64) == "arm64"
        assert machotools.cpu_type_name(machotools.CPU_TYPE_X86_64) == "x86_64"

    def test_unknown_type_is_labelled(self):
        assert machotools.cpu_type_name(0x99) == "cpu_type 0x99"


class TestParseMacho:
    def test_thin_helper_reads_type_deps_and_rpaths(self):
        data = mf.helper(
            deps=("@rpath/libx.dylib", ("/usr/lib/libSystem.B.dylib", "load")),
            rpaths=("@executable_path/../Frameworks",),
        )
        (s,) = machotools.parse_macho(data).slices
        assert s.arch == "arm64"
        assert s.filetype == machotools.MH_EXECUTE
        assert s.install_name is None
        assert [d.name for d in s.dependencies] == [
            "@rpath/libx.dylib",
            "/usr/lib/libSystem.B.dylib",
        ]
        assert s.rpaths == ("@executable_path/../Frameworks",)

    def test_dylib_install_name(self):
        (s,) = machotools.parse_macho(mf.dylib("libx.dylib")).slices
        assert s.filetype == machotools.MH_DYLIB
        assert s.install_name == "@rpath/libx.dylib"

    @pytest.mark.parametrize(
        ("kind", "command", "weak"),
        [
            ("load", "LC_LOAD_DYLIB", False),
            ("weak", "LC_LOAD_WEAK_DYLIB", True),
            ("reexport", "LC_REEXPORT_DYLIB", False),
            ("lazy", "LC_LAZY_LOAD_DYLIB", False),
            ("upward", "LC_LOAD_UPWARD_DYLIB", False),
        ],
    )
    def test_every_dependency_command(self, kind, command, weak):
        (s,) = machotools.parse_macho(mf.helper(deps=(("libx.dylib", kind),))).slices
        (dep,) = s.dependencies
        assert (dep.name, dep.command, dep.weak) == ("libx.dylib", command, weak)

    @pytest.mark.parametrize("little_endian", [True, False])
    @pytest.mark.parametrize("wide", [True, False])
    def test_thin_byte_orders_and_widths(self, little_endian, wide):
        data = mf.thin(
            machotools.MH_DYLIB,
            deps=("@loader_path/liby.dylib",),
            little_endian=little_endian,
            wide=wide,
        )
        (s,) = machotools.parse_macho(data).slices
        assert s.filetype == machotools.MH_DYLIB
        assert s.dependencies[0].name == "@loader_path/liby.dylib"

    @pytest.mark.parametrize("little_endian", [True, False])
    @pytest.mark.parametrize("wide", [True, False])
    def test_universal_both_widths_and_orders(self, little_endian, wide):
        data = mf.fat(
            mf.helper(cpu_type=machotools.CPU_TYPE_X86_64),
            mf.helper(deps=("@rpath/libx.dylib",)),
            wide=wide,
            little_endian=little_endian,
        )
        parsed = machotools.parse_macho(data)
        assert [s.arch for s in parsed.slices] == ["x86_64", "arm64"]
        assert parsed.filetypes == {machotools.MH_EXECUTE}
        arm = parsed.slice_for("arm64")
        assert arm is not None
        assert arm.dependencies[0].name == "@rpath/libx.dylib"
        assert parsed.slice_for("ppc") is None

    def test_universal_slices_can_disagree(self):
        data = mf.fat(
            mf.helper(cpu_type=machotools.CPU_TYPE_X86_64), mf.dylib("libx.dylib")
        )
        assert machotools.parse_macho(data).filetypes == {
            machotools.MH_EXECUTE,
            machotools.MH_DYLIB,
        }

    def test_slice_past_end_is_refused(self):
        data = mf.fat(mf.helper())
        with pytest.raises(machotools.MachoError, match="past the end"):
            machotools.parse_macho(data[:-8])

    def test_fat_header_past_end_is_refused(self):
        data = struct.pack(">II", 0xCAFEBABE, 3) + b"\x00" * 20
        with pytest.raises(machotools.MachoError, match="past the end"):
            machotools.parse_macho(data)

    def test_java_class_file_is_not_universal(self):
        # 0xCAFEBABE then a class-file version (major 52), not a slice count.
        data = struct.pack(">IHH", 0xCAFEBABE, 0, 52) + b"\x00" * 32
        with pytest.raises(machotools.MachoError, match="universal slices"):
            machotools.parse_macho(data)

    def test_truncated_load_commands_are_refused(self):
        data = mf.helper(deps=("@rpath/libx.dylib",))
        with pytest.raises(machotools.MachoError, match="past the end"):
            machotools.parse_macho(data[:-4])

    def test_bad_command_size_is_refused(self):
        data = bytearray(mf.helper(deps=("@rpath/libx.dylib",)))
        struct.pack_into("<I", data, 32 + 4, 4)  # cmdsize < 8
        with pytest.raises(machotools.MachoError, match="bad size"):
            machotools.parse_macho(bytes(data))

    def test_string_offset_out_of_range_is_refused(self):
        data = bytearray(mf.helper(deps=("@rpath/libx.dylib",)))
        struct.pack_into("<I", data, 32 + 8, 999)
        with pytest.raises(machotools.MachoError, match="out of range"):
            machotools.parse_macho(bytes(data))

    def test_not_macho(self):
        with pytest.raises(machotools.MachoError, match="not a Mach-O"):
            machotools.parse_macho(b"#!/bin/sh\necho hi\n")
        with pytest.raises(machotools.MachoError, match="too short"):
            machotools.parse_macho(b"\xcf\xfa")

    def test_read_macho_from_disk(self, tmp_path):
        path = mf.write(tmp_path / "libx.dylib", mf.dylib("libx.dylib"))
        assert machotools.read_macho(path).filetypes == {machotools.MH_DYLIB}
        with pytest.raises(machotools.MachoError, match="could not read"):
            machotools.read_macho(tmp_path / "absent")

    def test_filetype_names(self):
        assert machotools.filetype_name(machotools.MH_BUNDLE) == "MH_BUNDLE"
        assert machotools.filetype_name(0x77) == "file type 0x77"

    def test_fat64_magic_is_macho(self, tmp_path):
        f = tmp_path / "u64"
        _write_magic(f, 0xCAFEBABF)
        assert machotools.is_macho(f)


class TestToolWrappers:
    def test_run_missing_tool_is_actionable(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("nope")

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(AppBundleError, match="not found"):
            machotools.codesign_adhoc(Path("/tmp/x"))

    def test_run_nonzero_raises(self, monkeypatch):
        def fail(*a, **k):
            return subprocess.CompletedProcess(a[0], 1, "", "boom")

        monkeypatch.setattr(subprocess, "run", fail)
        with pytest.raises(AppBundleError, match="boom"):
            machotools.codesign_adhoc(Path("/bin/x"))

    def test_macho_arches_parses_lipo(self, monkeypatch):
        def ok(*a, **k):
            return subprocess.CompletedProcess(a[0], 0, "x86_64 arm64\n", "")

        monkeypatch.setattr(subprocess, "run", ok)
        assert machotools.macho_arches(Path("/bin/x")) == ("x86_64", "arm64")

    def test_macho_arches_empty_on_error(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "e"),
        )
        assert machotools.macho_arches(Path("/bin/x")) == ()

    def test_codesign_verify_bool(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""),
        )
        assert machotools.codesign_verify(Path("/app")) is True


class TestCodesignIdentityRetry:
    """errSecInternalComponent is transient keychain flakiness -> retry."""

    def test_retries_transient_error_then_succeeds(self, monkeypatch):
        calls = []

        def flaky(*a, **k):
            calls.append(a[0])
            if len(calls) < 3:
                return subprocess.CompletedProcess(
                    a[0], 1, "", "...: errSecInternalComponent"
                )
            return subprocess.CompletedProcess(a[0], 0, "", "")

        monkeypatch.setattr(subprocess, "run", flaky)
        monkeypatch.setattr(machotools.time, "sleep", lambda s: None)

        machotools.codesign_identity(Path("/bin/x"), "Developer ID Application: Me")

        assert len(calls) == 3

    def test_gives_up_after_max_attempts(self, monkeypatch):
        calls = []

        def always_flaky(*a, **k):
            calls.append(a[0])
            return subprocess.CompletedProcess(a[0], 1, "", "errSecInternalComponent")

        monkeypatch.setattr(subprocess, "run", always_flaky)
        monkeypatch.setattr(machotools.time, "sleep", lambda s: None)

        with pytest.raises(AppBundleError, match="errSecInternalComponent"):
            machotools.codesign_identity(Path("/bin/x"), "Developer ID Application: Me")

        assert len(calls) == machotools._CODESIGN_MAX_ATTEMPTS

    def test_non_transient_error_raises_immediately(self, monkeypatch):
        calls = []

        def fail(*a, **k):
            calls.append(a[0])
            return subprocess.CompletedProcess(a[0], 1, "", "no identity found")

        monkeypatch.setattr(subprocess, "run", fail)
        monkeypatch.setattr(machotools.time, "sleep", lambda s: None)

        with pytest.raises(AppBundleError, match="no identity found"):
            machotools.codesign_identity(Path("/bin/x"), "Developer ID Application: Me")

        assert len(calls) == 1
