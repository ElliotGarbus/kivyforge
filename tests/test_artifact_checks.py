"""The T3 artifact checks, against synthetic APKs and ``.app`` bundles.

Hermetic on purpose: a checker that only runs when a real build exists cannot be
trusted to fail correctly, and the whole point of it is to fail when something
is wrong. Each Android test builds the smallest zip that expresses one fault;
each macOS and Linux test builds the smallest directory tree that does the
same.

Magic 3627 is CPython 3.14's, and 3621 is 3.14.0a7's — the actual pair from
roadmap item 1, where the alpha's bytecode looked fine and was unimportable.
3571 is 3.13's, which is what the desktop examples ship: the Linux tests use
the 3571/3627 pair because that is the real mismatch a Linux build hits, the
AppDir compiling its payload with its own staged 3.13 while pytest runs under
3.14.
"""

from __future__ import annotations

import os
import plistlib
import struct
import zipfile
from pathlib import Path

import pytest

from kivyforge.platforms.android.elf import EM_AARCH64, EM_X86_64
from kivyforge.platforms.linux.elftools import ELFCLASS32
from kivyforge.platforms.macos.machotools import CPU_TYPE_ARM64, CPU_TYPE_X86_64
from tests.artifact_checks import (
    BUNDLE_ROOT,
    ELFCLASS64,
    android_apk_problems,
    linux_appdir_problems,
    linux_appimage_file_problems,
    macos_app_problems,
    shipped_python_tags,
    shipped_python_tags_appdir,
)

MAGIC_314 = struct.pack("<H", 3627) + b"\r\n"
MAGIC_314_ALPHA = struct.pack("<H", 3621) + b"\r\n"
MAGIC_313 = struct.pack("<H", 3571) + b"\r\n"


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


# --- macOS -------------------------------------------------------------------
#
# 0xFEEDFACF is MH_MAGIC_64, hardcoded rather than imported so these fixtures
# stay independent of machotools' internals — same reasoning as the Android
# fixtures above building raw ELF bytes instead of importing a header helper.

MAGIC_MACOS_314 = struct.pack("<H", 3627) + b"\r\n"
MAGIC_MACOS_314_ALPHA = struct.pack("<H", 3621) + b"\r\n"


def _macho(cpu_type: int) -> bytes:
    """Minimal thin 64-bit Mach-O header: real macOS binaries are little-endian."""
    return struct.pack("<II", 0xFEEDFACF, cpu_type) + b"\x00" * 24


def _macos_app(
    tmp_path: Path,
    *,
    name: str = "Test.app",
    arch: int = CPU_TYPE_ARM64,
    executable: str = "test-app",
    bundle_id: str = "org.example.test",
    version: str = "1.0",
    build: str = "1",
    stripped: bool = True,
) -> Path:
    app = tmp_path / name
    resources = app / "Contents" / "Resources"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (resources / "app").mkdir(parents=True)
    (resources / "lib").mkdir(parents=True)
    (resources / "python" / "bin").mkdir(parents=True)

    (app / "Contents" / "MacOS" / executable).write_bytes(_macho(arch))
    (resources / "python" / "bin" / "python3").write_bytes(_macho(arch))

    plist = {
        "CFBundleIdentifier": bundle_id,
        "CFBundleExecutable": executable,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build,
    }
    with (app / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(plist, fh)

    if stripped:
        (resources / "app" / "main.pyc").write_bytes(MAGIC_MACOS_314 + b"body")
        (resources / "lib" / "somepkg.pyc").write_bytes(MAGIC_MACOS_314 + b"body")
    else:
        (resources / "app" / "main.py").write_text("x = 1\n")
        (resources / "lib" / "somepkg.py").write_text("x = 1\n")
    # The embedded stdlib always ships source, stripped or not — verifying
    # that this is *not* flagged is the point of TestMacosStdlibExcluded.
    (resources / "python" / "os.py").write_text("x = 1\n")

    return app


def _check_macos(
    app: Path,
    *,
    arch: str = "arm64",
    stripped: bool = True,
    magic: bytes = MAGIC_MACOS_314,
    bundle_id=None,
    executable=None,
):
    return macos_app_problems(
        app,
        arch=arch,
        stripped=stripped,
        expected_magic=magic,
        bundle_id=bundle_id,
        executable=executable,
    )


class TestMacosCleanArtifacts:
    def test_a_well_formed_stripped_app_has_no_problems(self, tmp_path):
        app = _macos_app(tmp_path)
        assert _check_macos(app) == []

    def test_x86_64_is_checked_against_its_own_arch(self, tmp_path):
        app = _macos_app(tmp_path, arch=CPU_TYPE_X86_64)
        assert _check_macos(app, arch="x86_64") == []

    def test_an_unstripped_app_wants_source(self, tmp_path):
        app = _macos_app(tmp_path, stripped=False)
        assert _check_macos(app, stripped=False) == []

    def test_plist_matching_expected_values_passes(self, tmp_path):
        app = _macos_app(tmp_path, bundle_id="org.kivy.demo", executable="demo")
        assert _check_macos(app, bundle_id="org.kivy.demo", executable="demo") == []


class TestMacosStdlibExcluded:
    """The embedded CPython framework's stdlib is never stripped — by design."""

    def test_stdlib_py_files_are_not_flagged_when_stripped(self, tmp_path):
        app = _macos_app(tmp_path, stripped=True)
        assert (app / "Contents/Resources/python/os.py").is_file()
        assert _check_macos(app, stripped=True) == []


class TestMacosPayloadStripping:
    def test_a_leftover_source_file_under_app_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/app/leftover.py").write_text("x = 1\n")
        problems = _check_macos(app)
        assert any("1 .py file(s) remain" in p for p in problems)

    def test_a_leftover_source_file_under_lib_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/lib/leftover.py").write_text("x = 1\n")
        problems = _check_macos(app)
        assert any(
            "1 .py file(s) remain under Contents/Resources/lib" in p for p in problems
        )

    def test_a_payload_with_no_bytecode_is_reported_as_degraded(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/app/main.pyc").unlink()
        problems = _check_macos(app)
        assert any("degraded to shipping source" in p for p in problems)

    def test_pycache_defeats_sourceless_import(self, tmp_path):
        app = _macos_app(tmp_path)
        cache = app / "Contents/Resources/lib/__pycache__"
        cache.mkdir()
        (cache / "somepkg.cpython-314.pyc").write_bytes(MAGIC_MACOS_314 + b"body")
        problems = _check_macos(app)
        assert any("__pycache__" in p for p in problems)


class TestMacosArch:
    def test_a_host_binary_leaking_into_a_cross_build_is_reported(self, tmp_path):
        app = _macos_app(tmp_path, arch=CPU_TYPE_ARM64)
        (app / "Contents/Resources/lib/native.so").write_bytes(_macho(CPU_TYPE_X86_64))
        problems = _check_macos(app, arch="arm64")
        assert any("native.so is x86_64 but this build is arm64" in p for p in problems)

    def test_a_non_macho_file_is_not_flagged(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/lib/readme.txt").write_text("not a binary")
        assert _check_macos(app) == []

    def test_an_unknown_arch_fails_fast(self, tmp_path):
        app = _macos_app(tmp_path)
        assert _check_macos(app, arch="armv7") == [
            "unknown arch 'armv7'; expected one of ['arm64', 'x86_64']"
        ]


class TestMacosPlist:
    def test_a_mismatched_bundle_id_is_reported(self, tmp_path):
        app = _macos_app(tmp_path, bundle_id="org.example.test")
        problems = _check_macos(app, bundle_id="org.other.app")
        assert any("CFBundleIdentifier" in p and "org.other.app" in p for p in problems)

    def test_a_mismatched_executable_is_reported(self, tmp_path):
        app = _macos_app(tmp_path, executable="test-app")
        problems = _check_macos(app, executable="something-else")
        assert any("CFBundleExecutable" in p for p in problems)

    def test_an_executable_not_matching_any_file_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        plist_path = app / "Contents/Info.plist"
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
        plist["CFBundleExecutable"] = "does-not-exist"
        with plist_path.open("wb") as fh:
            plistlib.dump(plist, fh)
        problems = _check_macos(app)
        assert any("does not name a file" in p for p in problems)

    def test_an_unparseable_plist_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Info.plist").write_bytes(b"not a plist")
        problems = _check_macos(app)
        assert any("does not parse" in p for p in problems)

    def test_a_missing_required_key_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        plist_path = app / "Contents/Info.plist"
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
        del plist["CFBundleVersion"]
        with plist_path.open("wb") as fh:
            plistlib.dump(plist, fh)
        problems = _check_macos(app)
        assert any("CFBundleVersion" in p for p in problems)


class TestMacosPycMagic:
    def test_bytecode_from_the_wrong_interpreter_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/lib/somepkg.pyc").write_bytes(
            MAGIC_MACOS_314_ALPHA + b"body"
        )
        problems = _check_macos(app)
        assert any("3621" in p and "3627" in p for p in problems)

    def test_the_magic_check_is_skipped_when_unstripped(self, tmp_path):
        app = _macos_app(tmp_path, stripped=False)
        # An unstripped build has no .pyc to mismatch in the first place, but
        # confirm the check path is simply not taken.
        problems = _check_macos(app, stripped=False)
        assert not any("3621" in p for p in problems)


class TestMacosRequiredEntries:
    def test_a_missing_info_plist_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Info.plist").unlink()
        problems = _check_macos(app)
        assert any("Info.plist is missing" in p for p in problems)

    def test_a_missing_executable_is_reported(self, tmp_path):
        app = _macos_app(tmp_path, executable="test-app")
        (app / "Contents/MacOS/test-app").unlink()
        problems = _check_macos(app)
        assert any("no executable" in p for p in problems)

    def test_a_missing_runtime_is_reported(self, tmp_path):
        import shutil

        app = _macos_app(tmp_path)
        shutil.rmtree(app / "Contents/Resources/python")
        problems = _check_macos(app)
        assert any("embedded runtime" in p for p in problems)

    def test_a_missing_app_payload_is_reported(self, tmp_path):
        import shutil

        app = _macos_app(tmp_path)
        shutil.rmtree(app / "Contents/Resources/app")
        problems = _check_macos(app)
        assert any("app payload" in p for p in problems)


# ---------------------------------------------------------------------------
# Linux: AppDir / AppImage
# ---------------------------------------------------------------------------

_SCRIPT_APPRUN = 'exec "$HERE/usr/python/bin/python3" "$HERE/usr/app/{entry}.py" "$@"\n'
_MODULE_APPRUN = 'exec "$HERE/usr/python/bin/python3" -m {entry} "$@"\n'


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _appdir(
    tmp_path: Path,
    *,
    stripped: bool = True,
    machine: int = EM_X86_64,
    minor: str = "3.13",
    apprun: str | None = None,
    magic: bytes = MAGIC_313,
) -> Path:
    """A well-formed AppDir: right arch, one runtime, payload in one state.

    Mirrors the real tree — runtime under ``usr/python``, site-packages under
    ``usr/lib``, app sources under ``usr/app`` — including a stdlib that keeps
    its ``.py`` and ``__pycache__`` even when the payload is stripped, because
    the build byte-compiles only the payload and a check that swept the whole
    tree would call the stdlib a fault.

    ``apprun`` defaults to a launcher that can actually start this payload: the
    ``-m`` form when stripped, the script form otherwise. Pairing the script
    form *with* a stripped payload is precisely the shipped bug, so the tests
    that assert on it ask for that combination explicitly rather than getting it
    by default.
    """
    if apprun is None:
        apprun = _MODULE_APPRUN if stripped else _SCRIPT_APPRUN
    root = tmp_path / "Test.AppDir"
    (root / "usr").mkdir(parents=True, exist_ok=True)

    run = root / "AppRun"
    _write(run, ("#!/bin/sh\nHERE=x\n" + apprun.format(entry="main")).encode())
    run.chmod(0o755)
    _write(root / "org.example.test.desktop", b"[Desktop Entry]\nName=Test\n")

    _write(root / f"usr/python/lib/libpython{minor}.so", _elf(machine))
    _write(root / f"usr/python/bin/python{minor}", _elf(machine))
    _write(root / f"usr/python/lib/python{minor}/os.py", b"x = 1\n")
    _write(
        root / f"usr/python/lib/python{minor}/__pycache__/os.cpython-313.pyc",
        magic + b"body",
    )
    _write(root / "usr/lib/kivy/_speedup.so", _elf(machine))

    suffix, body = (".pyc", magic + b"body") if stripped else (".py", b"x = 1\n")
    _write(root / f"usr/app/main{suffix}", body)
    _write(root / f"usr/lib/kivy/__init__{suffix}", body)
    return root


def _lcheck(root: Path, *, arch="x86_64", stripped=True, magic=MAGIC_313):
    return linux_appdir_problems(
        root, arch=arch, stripped=stripped, expected_magic=magic
    )


class TestLinuxCleanArtifacts:
    def test_a_well_formed_stripped_appdir_has_no_problems(self, tmp_path):
        assert _lcheck(_appdir(tmp_path)) == []

    def test_an_unstripped_appdir_wants_source(self, tmp_path):
        assert _lcheck(_appdir(tmp_path, stripped=False), stripped=False) == []

    def test_the_stdlib_keeping_its_source_is_not_a_fault(self, tmp_path):
        """The payload is usr/app + usr/lib; usr/python is the runtime.

        A real stripped dice-roller AppImage ships 1037 stdlib ``.py`` and six
        ``__pycache__`` directories, because ``build_appdir`` byte-compiles only
        the payload. Sweeping the whole tree would report every one of them.
        """
        root = _appdir(tmp_path)
        for i in range(5):
            _write(root / f"usr/python/lib/python3.13/mod{i}.py", b"x = 1\n")
            _write(
                root / f"usr/python/lib/python3.13/__pycache__/m{i}.cpython-313.pyc",
                MAGIC_313 + b"body",
            )
        assert _lcheck(root) == []

    def test_an_aarch64_appdir_is_checked_against_its_own_machine(self, tmp_path):
        root = _appdir(tmp_path, machine=EM_AARCH64)
        assert _lcheck(root, arch="aarch64") == []

    def test_an_unknown_arch_fails_fast(self, tmp_path):
        assert _lcheck(_appdir(tmp_path), arch="riscv64") == [
            "unknown arch 'riscv64'; expected one of ['aarch64', 'x86_64']"
        ]


class TestAppRunEntryPoint:
    """The Linux shape of roadmap item 1, and a bug that actually shipped."""

    def test_apprun_pointing_at_a_stripped_away_source_file_is_reported(self, tmp_path):
        """`kivyforge package` produced exactly this: AppRun execs a deleted file."""
        root = _appdir(
            tmp_path, apprun=_SCRIPT_APPRUN
        )  # main.pyc exists, main.py does not
        problems = _lcheck(root)
        assert any(
            "AppRun execs usr/app/main.py" in p and "cannot start" in p
            for p in problems
        )

    def test_the_diagnosis_names_the_bytecode_sitting_beside_it(self, tmp_path):
        problems = _lcheck(_appdir(tmp_path, apprun=_SCRIPT_APPRUN))
        assert any("usr/app/main.pyc is there" in p for p in problems)

    def test_the_module_form_accepts_a_sourceless_payload(self, tmp_path):
        """The proposed fix: `-m main` resolves main.pyc through the importer."""
        root = _appdir(tmp_path, apprun=_MODULE_APPRUN)
        assert _lcheck(root) == []

    def test_the_module_form_still_catches_a_missing_entry_point(self, tmp_path):
        root = _appdir(tmp_path, apprun=_MODULE_APPRUN)
        (root / "usr/app/main.pyc").unlink()
        problems = _lcheck(root)
        assert any(
            "neither usr/app/main.py nor usr/app/main.pyc" in p for p in problems
        )

    def test_a_dotted_entry_point_maps_to_a_nested_file(self, tmp_path):
        root = _appdir(tmp_path, apprun='exec "$HERE/x" -m pkg.start "$@"\n')
        _write(root / "usr/app/pkg/start.pyc", MAGIC_313 + b"body")
        assert not any("pkg" in p for p in _lcheck(root))

    def test_an_apprun_with_no_exec_line_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "AppRun").write_text("#!/bin/sh\necho nothing\n")
        assert any("no exec line" in p for p in _lcheck(root))

    @pytest.mark.skipif(
        os.name != "posix",
        reason=(
            "NTFS stores no execute bit, so chmod(0o644) is indistinguishable "
            "from chmod(0o755) here and the check deliberately does not ask"
        ),
    )
    def test_a_non_executable_apprun_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "AppRun").chmod(0o644)
        assert any("not executable" in p for p in _lcheck(root))

    def test_a_missing_apprun_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "AppRun").unlink()
        assert any("AppRun is missing" in p for p in _lcheck(root))


class TestLinuxPayloadStripping:
    def test_a_leftover_source_file_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/leftover.py", b"x = 1\n")
        assert any("1 .py file(s) remain" in p for p in _lcheck(root))

    def test_a_payload_with_no_bytecode_is_reported_as_degraded(self, tmp_path):
        root = _appdir(tmp_path)
        for pyc in [root / "usr/app/main.pyc", root / "usr/lib/kivy/__init__.pyc"]:
            pyc.unlink()
        assert any("degraded to shipping source" in p for p in _lcheck(root))

    def test_pycache_in_the_payload_defeats_sourceless_import(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/__pycache__/m.cpython-313.pyc", MAGIC_313 + b"body")
        assert any("__pycache__" in p for p in _lcheck(root))

    def test_pycache_in_an_unstripped_payload_accuses_the_launch(self, tmp_path):
        """A build never writes payload ``__pycache__``; running the AppDir does.

        Measured on dice-roller: ``kivyforge build -p linux`` staged 336 ``.py``
        and zero ``.pyc``, then launching that same AppDir left 100 ``.pyc`` in
        ``usr/app``/``usr/lib``. So this is normal in a working tree and never
        in a freshly staged artifact, which is what makes it worth reporting
        even though the payload is *meant* to be source here.
        """
        root = _appdir(tmp_path, stripped=False)
        _write(root / "usr/lib/kivy/__pycache__/m.cpython-313.pyc", MAGIC_313 + b"body")
        problems = _lcheck(root, stripped=False)
        assert any("written to after the build" in p for p in problems)
        assert not any("strip_source" in p for p in problems)

    def test_an_unstripped_payload_without_pycache_is_clean(self, tmp_path):
        assert _lcheck(_appdir(tmp_path, stripped=False), stripped=False) == []

    def test_an_empty_payload_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        for path in [root / "usr/app", root / "usr/lib"]:
            for f in path.rglob("*"):
                if f.is_file():
                    f.unlink()
        assert any("no payload" in p for p in _lcheck(root))


class TestLinuxPycMagic:
    def test_bytecode_from_the_wrong_interpreter_is_reported(self, tmp_path):
        """The real Linux mismatch: a 3.14 host compiling for a 3.13 runtime."""
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/__init__.pyc", MAGIC_314 + b"body")
        problems = _lcheck(root)
        assert any("3627" in p and "3571" in p for p in problems)

    def test_the_magic_check_is_skipped_when_source_ships_alongside(self, tmp_path):
        root = _appdir(tmp_path, stripped=False)
        _write(root / "usr/lib/kivy/stale.pyc", MAGIC_314 + b"body")
        assert not any("3627" in p for p in _lcheck(root, stripped=False))

    def test_the_stdlib_is_not_judged_for_magic(self, tmp_path):
        """usr/python is the shipped runtime's own business, not the payload's."""
        root = _appdir(tmp_path)
        _write(
            root / "usr/python/lib/python3.13/__pycache__/x.cpython-313.pyc",
            MAGIC_314 + b"body",
        )
        assert not any("3627" in p for p in _lcheck(root))


class TestLinuxElfArch:
    def test_a_foreign_arch_extension_module_is_reported(self, tmp_path):
        """Coverage doctor does not have: site-packages, not usr/bin."""
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/_speedup.so", _elf(EM_AARCH64))
        problems = _lcheck(root)
        assert any("_speedup.so" in p and "aarch64" in p for p in problems)

    def test_a_foreign_arch_runtime_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/python/lib/libpython3.13.so", _elf(EM_AARCH64))
        assert any("libpython3.13.so" in p for p in _lcheck(root))

    def test_a_32_bit_object_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/_speedup.so", _elf(EM_X86_64, ei_class=ELFCLASS32))
        assert any("ELF32" in p for p in _lcheck(root))

    def test_a_declared_native_binary_is_checked_too(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/bin/helper", _elf(EM_AARCH64))
        assert any("usr/bin/helper" in p for p in _lcheck(root))

    def test_a_non_elf_file_is_not_mistaken_for_one(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/bin/helper.sh", b"#!/bin/sh\necho hi\n")
        assert _lcheck(root) == []


class TestLinuxShippedRuntime:
    def test_the_runtime_version_is_read_out_of_the_artifact(self, tmp_path):
        assert shipped_python_tags_appdir(_appdir(tmp_path)) == ["3.13"]

    def test_a_versioned_soname_is_recognised(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "usr/python/lib/libpython3.13.so").rename(
            root / "usr/python/lib/libpython3.13.so.1.0"
        )
        assert shipped_python_tags_appdir(root) == ["3.13"]

    def test_the_abi_stub_is_not_mistaken_for_a_runtime(self, tmp_path):
        """libpython3.so carries no minor and must not count as a second one."""
        root = _appdir(tmp_path)
        _write(root / "usr/python/lib/libpython3.so", _elf(EM_X86_64))
        assert shipped_python_tags_appdir(root) == ["3.13"]
        assert _lcheck(root) == []

    def test_two_runtimes_are_reported(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/python/lib/libpython3.14.so", _elf(EM_X86_64))
        assert shipped_python_tags_appdir(root) == ["3.13", "3.14"]
        assert any("ships 2 CPython runtimes" in p for p in _lcheck(root))

    def test_no_runtime_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "usr/python/lib/libpython3.13.so").unlink()
        assert any("ships no runtime" in p for p in _lcheck(root))

    def test_a_missing_desktop_entry_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "org.example.test.desktop").unlink()
        assert any(".desktop" in p for p in _lcheck(root))


class TestAppImageContainer:
    """appimagetool's own output, which inspecting the extracted tree cannot see."""

    def _appimage(self, tmp_path, *, machine=EM_X86_64, marker=b"AI\x02") -> Path:
        header = bytearray(_elf(machine))
        header[8:11] = marker
        return _write(tmp_path / "app.AppImage", bytes(header))

    def test_a_well_formed_type2_appimage_has_no_problems(self, tmp_path):
        assert (
            linux_appimage_file_problems(self._appimage(tmp_path), arch="x86_64") == []
        )

    def test_a_type1_appimage_is_reported(self, tmp_path):
        image = self._appimage(tmp_path, marker=b"AI\x01")
        assert any(
            "type-2" in p for p in linux_appimage_file_problems(image, arch="x86_64")
        )

    def test_a_plain_elf_with_no_marker_is_reported(self, tmp_path):
        image = self._appimage(tmp_path, marker=b"\x00\x00\x00")
        assert any(
            "appimagetool" in p
            for p in linux_appimage_file_problems(image, arch="x86_64")
        )

    def test_a_wrong_arch_runtime_is_reported(self, tmp_path):
        image = self._appimage(tmp_path, machine=EM_AARCH64)
        problems = linux_appimage_file_problems(image, arch="x86_64")
        assert any("type2-runtime" in p for p in problems)

    def test_a_non_elf_is_reported(self, tmp_path):
        image = _write(tmp_path / "app.AppImage", b"not an elf")
        assert any(
            "not an ELF" in p
            for p in linux_appimage_file_problems(image, arch="x86_64")
        )
