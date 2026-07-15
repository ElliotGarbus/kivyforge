"""Windows native-binary staging guards + PE arch check (hermetic)."""

from __future__ import annotations

import io
import struct
import tarfile
import zipfile

import pytest

from kivyforge.artifacts import native_stage_util as util
from kivyforge.lock.wheelruntime.model import LockedNativeBinary, WheelRuntimeLock
from kivyforge.platforms.windows import WindowsBundleError, native_stage, petools


def _pe_bytes(machine: int) -> bytes:
    buf = bytearray(0x88)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, 0x80)
    buf[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", buf, 0x84, machine)
    return bytes(buf)


def _nb(name, source, sha="s"):
    return LockedNativeBinary(name=name, version="1.0", url=source, sha256=sha)


def _lock(binaries):
    return WheelRuntimeLock(
        platform="windows",
        requires_python=">=3.13",
        packages=(),
        python_runtime=None,  # unused by staging
        archs=("amd64",),
        kivyforge_version="0",
        generated_at="t",
        pyproject_sha256="0" * 64,
        tool_kivyforge_schema_version=1,
        native_binaries=tuple(binaries),
    )


@pytest.fixture
def fetch_files(monkeypatch, tmp_path):
    """Map each entry's basename to a prepared file the fake _fetch returns."""
    files: dict[str, object] = {}

    def _fake_fetch(entry, filename, project_root, cache, no_cache):
        return files[entry.url]

    monkeypatch.setattr(util, "_fetch", _fake_fetch)
    return files, tmp_path


class TestWrapperArchCheck:
    def test_good_pe_stages(self, fetch_files, tmp_path):
        files, work = fetch_files
        dll = work / "sdk.dll"
        dll.write_bytes(_pe_bytes(petools.IMAGE_FILE_MACHINE_AMD64))
        files["https://e/sdk.dll"] = dll
        bundle = work / "bundle"
        bundle.mkdir()
        native_stage.stage_native_binaries(
            _lock([_nb("sdk", "https://e/sdk.dll")]),
            bundle,
            "amd64",
            project_root=work,
        )
        assert (bundle / "bin" / "sdk.dll").is_file()

    def test_wrong_arch_pe_rejected(self, fetch_files):
        files, work = fetch_files
        dll = work / "x86.dll"
        dll.write_bytes(_pe_bytes(petools.IMAGE_FILE_MACHINE_I386))
        files["https://e/x86.dll"] = dll
        bundle = work / "bundle"
        bundle.mkdir()
        with pytest.raises(WindowsBundleError, match="x86.*amd64"):
            native_stage.stage_native_binaries(
                _lock([_nb("x86", "https://e/x86.dll")]),
                bundle,
                "amd64",
                project_root=work,
            )


class TestSharedWindowsGuards:
    """Exercise the extended shared helper directly with the Windows flags."""

    def _stage(self, binaries, parent, files, project_root, **kw):
        return util.stage_binaries(
            tuple(binaries),
            parent,
            project_root=project_root,
            bin_label="bin",
            casefold=True,
            reject_windows_names=True,
            **kw,
        )

    def test_casefold_collision(self, fetch_files):
        files, work = fetch_files
        a = work / "SDK.dll"
        b = work / "sdk.dll"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        files["https://e/SDK.dll"] = a
        files["https://e/sdk.dll"] = b
        parent = work / "p"
        parent.mkdir()
        with pytest.raises(util.NativeStageError, match="colliding path"):
            self._stage(
                [_nb("one", "https://e/SDK.dll"), _nb("two", "https://e/sdk.dll")],
                parent,
                files,
                work,
            )

    def test_reserved_name_rejected(self, fetch_files):
        files, work = fetch_files
        src = work / "payload"
        src.write_bytes(b"x")
        files["https://e/NUL.dll"] = src
        parent = work / "p"
        parent.mkdir()
        with pytest.raises(util.NativeStageError, match="reserved Windows device"):
            self._stage([_nb("bad", "https://e/NUL.dll")], parent, files, work)

    def test_ads_member_rejected(self, fetch_files):
        files, work = fetch_files
        archive = work / "pack.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("good.dll", "x")
            zf.writestr("evil:stream.dll", "y")
        files["https://e/pack.zip"] = archive
        parent = work / "p"
        parent.mkdir()
        with pytest.raises(util.NativeStageError, match="alternate data stream"):
            self._stage([_nb("pack", "https://e/pack.zip")], parent, files, work)

    def test_trailing_dot_rejected(self, fetch_files):
        files, work = fetch_files
        archive = work / "pack.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("tool.", "x")
        files["https://e/pack.zip"] = archive
        parent = work / "p"
        parent.mkdir()
        with pytest.raises(util.NativeStageError, match="dot or space"):
            self._stage([_nb("pack", "https://e/pack.zip")], parent, files, work)

    def test_zip_extracts_normally(self, fetch_files):
        files, work = fetch_files
        archive = work / "pack.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("a.dll", "x")
            zf.writestr("sub/b.dll", "y")
        files["https://e/pack.zip"] = archive
        parent = work / "p"
        parent.mkdir()
        self._stage([_nb("pack", "https://e/pack.zip")], parent, files, work)
        assert (parent / "bin" / "a.dll").read_text() == "x"
        assert (parent / "bin" / "sub" / "b.dll").read_text() == "y"

    def _write_targz(self, path, members):
        with tarfile.open(path, "w:gz") as tf:
            for name, data in members.items():
                raw = data.encode()
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                tf.addfile(info, io.BytesIO(raw))

    def test_targz_extracts_normally(self, fetch_files):
        files, work = fetch_files
        archive = work / "pack.tar.gz"
        self._write_targz(archive, {"a.dll": "x", "sub/b.dll": "y"})
        files["https://e/pack.tar.gz"] = archive
        parent = work / "p"
        parent.mkdir()
        self._stage([_nb("pack", "https://e/pack.tar.gz")], parent, files, work)
        assert (parent / "bin" / "a.dll").read_text() == "x"
        assert (parent / "bin" / "sub" / "b.dll").read_text() == "y"

    def test_targz_reserved_name_rejected(self, fetch_files):
        files, work = fetch_files
        archive = work / "pack.tar.gz"
        self._write_targz(archive, {"COM1.dll": "x"})
        files["https://e/pack.tar.gz"] = archive
        parent = work / "p"
        parent.mkdir()
        with pytest.raises(util.NativeStageError, match="reserved Windows device"):
            self._stage([_nb("pack", "https://e/pack.tar.gz")], parent, files, work)


class TestExecBitNoop:
    def test_make_executable_is_noop_on_windows(self, tmp_path, monkeypatch):
        f = tmp_path / "x.dll"
        f.write_bytes(b"x")
        monkeypatch.setattr(util.sys, "platform", "win32")
        util._make_executable(f)  # must not raise


class TestDefaultsUnchanged:
    """macOS/Linux consumers pass no Windows flags: behavior is unchanged."""

    def test_case_sensitive_by_default(self, fetch_files):
        files, work = fetch_files
        a = work / "SDK.so"
        b = work / "sdk.so"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        files["https://e/SDK.so"] = a
        files["https://e/sdk.so"] = b
        parent = work / "p"
        parent.mkdir()
        # No casefold: SDK.so and sdk.so are distinct (POSIX filesystem).
        util.stage_binaries(
            (_nb("one", "https://e/SDK.so"), _nb("two", "https://e/sdk.so")),
            parent,
            project_root=work,
            bin_label="usr/bin",
        )
        assert (parent / "bin" / "SDK.so").exists()
        assert (parent / "bin" / "sdk.so").exists()
