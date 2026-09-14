"""The T3 artifact checks, against synthetic APKs.

Hermetic on purpose: a checker that only runs when a real build exists cannot be
trusted to fail correctly, and the whole point of it is to fail when something
is wrong. Each test builds the smallest zip that expresses one fault.

Magic 3627 is CPython 3.14's, and 3621 is 3.14.0a7's — the actual pair from
roadmap item 1, where the alpha's bytecode looked fine and was unimportable.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

from kivyforge.platforms.android.elf import EM_AARCH64, EM_X86_64
from tests.artifact_checks import (
    BUNDLE_ROOT,
    ELFCLASS64,
    android_apk_problems,
    shipped_python_tags,
)

MAGIC_314 = struct.pack("<H", 3627) + b"\r\n"
MAGIC_314_ALPHA = struct.pack("<H", 3621) + b"\r\n"


def _elf(machine: int, *, ei_class: int = ELFCLASS64) -> bytes:
    """A 64-byte ELF header — enough for the six bytes the checks look at."""
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = ei_class
    header[5] = 1  # ELFDATA2LSB
    struct.pack_into("<H", header, 18, machine)
    return bytes(header)


def _apk(tmp_path: Path, entries: dict[str, bytes], name: str = "app.apk") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for entry, payload in entries.items():
            zf.writestr(entry, payload)
    return path


def _stripped_entries(abi: str = "arm64-v8a") -> dict[str, bytes]:
    """A well-formed stripped APK: bytecode only, libs hoisted, right arch."""
    machine = EM_AARCH64 if abi == "arm64-v8a" else EM_X86_64
    return {
        f"lib/{abi}/libmain.so": _elf(machine),
        f"lib/{abi}/libpython3.14.so": _elf(machine),
        f"lib/{abi}/libpy._socket.so": _elf(machine),
        f"{BUNDLE_ROOT}app/main.pyc": MAGIC_314 + b"body",
        f"{BUNDLE_ROOT}stdlib/os.pyc": MAGIC_314 + b"body",
        f"{BUNDLE_ROOT}site-packages/kivy/__init__.pyc": MAGIC_314 + b"body",
        f"{BUNDLE_ROOT}VERSION": b"bf2eaad4cf839f30",
    }


def _check(tmp_path, entries, *, abi="arm64-v8a", stripped=True, magic=MAGIC_314):
    return android_apk_problems(
        _apk(tmp_path, entries),
        abi=abi,
        stripped=stripped,
        expected_magic=magic,
    )


class TestCleanArtifacts:
    def test_a_well_formed_stripped_apk_has_no_problems(self, tmp_path):
        assert _check(tmp_path, _stripped_entries()) == []

    def test_x86_64_is_checked_against_its_own_machine(self, tmp_path):
        entries = _stripped_entries("x86_64")
        assert _check(tmp_path, entries, abi="x86_64") == []

    def test_an_unstripped_apk_wants_source(self, tmp_path):
        entries = _stripped_entries()
        for name in [n for n in entries if n.endswith(".pyc")]:
            entries[name.removesuffix(".pyc") + ".py"] = b"x = 1\n"
            del entries[name]
        assert _check(tmp_path, entries, stripped=False) == []


class TestPayloadStripping:
    def test_a_leftover_source_file_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}site-packages/kivy/leftover.py"] = b"x = 1\n"
        problems = _check(tmp_path, entries)
        assert any("1 .py file(s) remain" in p for p in problems)

    def test_a_payload_with_no_bytecode_is_reported_as_degraded(self, tmp_path):
        entries = {
            k: v for k, v in _stripped_entries().items() if not k.endswith(".pyc")
        }
        entries[f"{BUNDLE_ROOT}app/main.py"] = b"x = 1\n"
        problems = _check(tmp_path, entries)
        assert any("degraded to shipping source" in p for p in problems)

    def test_pycache_defeats_sourceless_import(self, tmp_path):
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}site-packages/x/__pycache__/m.cpython-314.pyc"] = (
            MAGIC_314 + b"body"
        )
        problems = _check(tmp_path, entries)
        assert any("__pycache__" in p for p in problems)

    def test_a_missing_compiled_entry_point_is_reported(self, tmp_path):
        entries = _stripped_entries()
        del entries[f"{BUNDLE_ROOT}app/main.pyc"]
        problems = _check(tmp_path, entries)
        assert any("app/main.pyc is missing" in p for p in problems)

    def test_an_unstripped_build_missing_its_entry_point_is_reported(self, tmp_path):
        entries = {
            k: v for k, v in _stripped_entries().items() if not k.endswith(".pyc")
        }
        problems = _check(tmp_path, entries, stripped=False)
        assert any("app/main.py is missing" in p for p in problems)

    def test_a_shared_object_left_in_the_payload_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}site-packages/x/_speedup.so"] = _elf(EM_AARCH64)
        problems = _check(tmp_path, entries)
        assert any("left inside the payload" in p for p in problems)


class TestPycMagic:
    def test_bytecode_from_the_wrong_interpreter_is_reported(self, tmp_path):
        """Roadmap item 1's bug: a pre-release wrote unimportable bytecode."""
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}stdlib/os.pyc"] = MAGIC_314_ALPHA + b"body"
        problems = _check(tmp_path, entries)
        assert any("3621" in p and "3627" in p for p in problems)

    def test_the_magic_check_is_skipped_when_source_ships_alongside(self, tmp_path):
        """Unstripped, a stale .pyc is ignored by the import system, not fatal."""
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}stdlib/os.pyc"] = MAGIC_314_ALPHA + b"body"
        entries[f"{BUNDLE_ROOT}app/main.py"] = b"x = 1\n"
        problems = _check(tmp_path, entries, stripped=False)
        assert not any("3621" in p for p in problems)


class TestNativeLibraries:
    def test_a_host_binary_in_a_cross_build_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/arm64-v8a/libpy._socket.so"] = _elf(EM_X86_64)
        problems = _check(tmp_path, entries)
        assert any("x86_64" in p and "leaked into a" in p for p in problems)

    def test_a_second_abi_directory_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/x86_64/libmain.so"] = _elf(EM_X86_64)
        problems = _check(tmp_path, entries)
        assert any("unrequested ABI" in p for p in problems)

    def test_a_32_bit_library_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/arm64-v8a/libpy._socket.so"] = _elf(EM_AARCH64, ei_class=1)
        problems = _check(tmp_path, entries)
        assert any("32-bit" in p for p in problems)

    def test_a_non_elf_library_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/arm64-v8a/libpy._socket.so"] = b"not an elf at all"
        problems = _check(tmp_path, entries)
        assert any("is not an ELF file" in p for p in problems)


class TestShippedRuntime:
    def test_the_runtime_version_is_read_out_of_the_artifact(self, tmp_path):
        """The expected .pyc magic is anchored to what the APK actually ships."""
        assert shipped_python_tags(_apk(tmp_path, _stripped_entries())) == ["3.14"]

    def test_two_runtimes_are_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/arm64-v8a/libpython3.13.so"] = _elf(EM_AARCH64)
        assert shipped_python_tags(_apk(tmp_path, entries)) == ["3.13", "3.14"]
        assert any("ships 2 CPython runtimes" in p for p in _check(tmp_path, entries))

    def test_no_runtime_is_reported(self, tmp_path):
        entries = _stripped_entries()
        del entries["lib/arm64-v8a/libpython3.14.so"]
        problems = _check(tmp_path, entries)
        assert any("ships no runtime" in p for p in problems)


class TestRequiredEntries:
    def test_a_missing_launcher_is_reported(self, tmp_path):
        entries = _stripped_entries()
        del entries["lib/arm64-v8a/libmain.so"]
        problems = _check(tmp_path, entries)
        assert any("libmain.so is missing" in p for p in problems)

    def test_a_missing_bundle_is_reported(self, tmp_path):
        entries = {
            k: v
            for k, v in _stripped_entries().items()
            if not k.startswith(BUNDLE_ROOT)
        }
        problems = _check(tmp_path, entries)
        assert any(BUNDLE_ROOT in p and "missing" in p for p in problems)

    def test_an_unknown_abi_fails_fast(self, tmp_path):
        problems = _check(tmp_path, _stripped_entries(), abi="armeabi-v7a")
        assert problems == [
            "unknown ABI 'armeabi-v7a'; expected one of ['arm64-v8a', 'x86_64']"
        ]
