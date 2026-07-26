"""Android doctor: fake-probe matrix + ELF alignment (android/06)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from kivyforge.doctor.result import Status
from kivyforge.platforms.android.doctor import android_doctor
from kivyforge.platforms.android.elf import PAGE_16K, ElfError, read_elf, scan_alignment


class FakeProbe:
    def __init__(self, **kw):
        self._which = kw.get("which", {})
        self._java_home = kw.get("java_home")
        self._sdk = kw.get("sdk")
        self._ndk = kw.get("ndk", [])
        self._build_tools = kw.get("build_tools", [])
        self._platforms = kw.get("platforms", set())
        self._avds = kw.get("avds", [])
        self._accel = kw.get("accel", True)
        self._reachable = kw.get("reachable", True)

    def which(self, name):
        return self._which.get(name)

    def java_home(self):
        return self._java_home

    def sdk_root(self):
        return self._sdk

    def ndk_versions(self, sdk):
        return list(self._ndk)

    def build_tools_versions(self, sdk):
        return list(self._build_tools)

    def platform_installed(self, sdk, api):
        return api in self._platforms

    def avds(self):
        return list(self._avds)

    def has_kvm_or_haxm(self):
        return self._accel

    def tcp_reachable(self, host, port):
        return self._reachable


def _healthy_probe(sdk: Path):
    return FakeProbe(
        which={"java": "/jdk/bin/java", "adb": "/sdk/platform-tools/adb"},
        java_home="/jdk",
        sdk=sdk,
        ndk=["27.3.13750724"],
        build_tools=["35.0.0"],
        platforms={35},
        avds=["kivyforge_x86_64"],
        accel=True,
    )


def _by_name(results):
    return {r.name: r for r in results}


class TestEnvironmentChecks:
    def test_all_healthy(self, tmp_path):
        results = android_doctor(
            tmp_path,
            kivyforge_version="0",
            offline=True,
            probe=_healthy_probe(tmp_path),
        )
        by = _by_name(results)
        assert by["JDK"].status is Status.PASS
        assert by["NDK"].status is Status.PASS
        assert by["Emulator / virtualization"].status is Status.PASS

    def test_no_jdk_fails(self, tmp_path):
        probe = FakeProbe(sdk=tmp_path, ndk=["27"], build_tools=["35.0.0"])
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["JDK"].status is Status.FAIL

    def test_no_ndk_fails(self, tmp_path):
        probe = FakeProbe(
            which={"java": "/j"}, sdk=tmp_path, ndk=[], build_tools=["35.0.0"]
        )
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["NDK"].status is Status.FAIL
        assert "every" in by["NDK"].detail.lower()

    def test_no_sdk_fails(self, tmp_path):
        probe = FakeProbe(which={"java": "/j"}, sdk=None)
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["Android SDK"].status is Status.FAIL
        assert by["NDK"].status is Status.SKIP

    def test_no_avd_warns(self, tmp_path):
        probe = _healthy_probe(tmp_path)
        probe._avds = []
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["Emulator / virtualization"].status is Status.WARN


class TestProjectChecks:
    def _project(self, tmp_path, *, compile_sdk=35):
        (tmp_path / "src").mkdir(exist_ok=True)
        # target_sdk tracks compile_sdk so the config itself stays valid
        # (compile_sdk >= target_sdk); the check under test is the *platform*
        # install, not config validity.
        (tmp_path / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "app"',
                    'version = "1.0.0"',
                    'dependencies = ["kivy==2.3.1", "pyjnius"]',
                    "[tool.kivy]",
                    'app_dir = "src"',
                    "[tool.kivy.android]",
                    "schema_version = 1",
                    'package = "org.real.app"',
                    f"target_sdk = {compile_sdk}",
                    f"compile_sdk = {compile_sdk}",
                    "[tool.kivy.android.python]",
                    'version = "3.14.6"',
                ]
            ),
            encoding="utf-8",
        )

    def test_config_and_app_source(self, tmp_path):
        self._project(tmp_path)
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["Android config"].status is Status.PASS
        assert by["App source directory"].status is Status.PASS
        assert by["Lock"].status is Status.WARN  # no lock yet

    def test_compile_sdk_platform_missing_fails(self, tmp_path):
        self._project(tmp_path, compile_sdk=34)
        probe = _healthy_probe(tmp_path)  # only android-35 installed
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["Build-tools / platform"].status is Status.FAIL

    def test_invalid_config_fails_fast(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "app"',
                    'version = "1.0.0"',
                    "[tool.kivy]",
                    'app_dir = "src"',
                    "[tool.kivy.android]",
                    "schema_version = 1",
                    'package = "nodots"',
                ]
            ),
            encoding="utf-8",
        )
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["Android config"].status is Status.FAIL


def _make_elf(align: int, *, is64=True) -> bytes:
    """A minimal ELF with one PT_LOAD segment at the given p_align."""
    e_phoff = 64 if is64 else 52
    phentsize = 56 if is64 else 32
    buf = bytearray(e_phoff + phentsize)
    buf[:4] = b"\x7fELF"
    buf[4] = 2 if is64 else 1  # class
    buf[5] = 1  # little-endian
    if is64:
        struct.pack_into("<Q", buf, 0x20, e_phoff)  # e_phoff
        struct.pack_into("<H", buf, 0x36, phentsize)
        struct.pack_into("<H", buf, 0x38, 1)  # e_phnum
        off = e_phoff
        struct.pack_into("<I", buf, off, 1)  # PT_LOAD
        struct.pack_into("<Q", buf, off + 0x30, align)  # p_align
    return bytes(buf)


class TestElf:
    def test_16k_aligned(self, tmp_path):
        so = tmp_path / "good.so"
        so.write_bytes(_make_elf(PAGE_16K))
        info = read_elf(so)
        assert info.is_16k_aligned

    def test_4k_flagged(self, tmp_path):
        so = tmp_path / "bad.so"
        so.write_bytes(_make_elf(0x1000))
        info = read_elf(so)
        assert not info.is_16k_aligned
        assert info.max_load_align == 0x1000

    def test_not_elf_raises(self, tmp_path):
        f = tmp_path / "x.so"
        f.write_bytes(b"not an elf at all, just text padding here to be long enough..")
        with pytest.raises(ElfError):
            read_elf(f)

    def test_scan_finds_bad(self, tmp_path):
        (tmp_path / "arm64-v8a").mkdir()
        (tmp_path / "arm64-v8a" / "good.so").write_bytes(_make_elf(PAGE_16K))
        (tmp_path / "arm64-v8a" / "bad.so").write_bytes(_make_elf(0x1000))
        bad = scan_alignment(tmp_path)
        assert [p.name for p, _ in bad] == ["bad.so"]
