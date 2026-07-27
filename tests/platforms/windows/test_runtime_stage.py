"""Windows runtime staging + conditional VC-runtime placement (hermetic)."""

from __future__ import annotations

import struct
import tarfile

import pytest

from kivyforge.artifacts.download import DownloadError
from kivyforge.lock.wheelruntime.model import PythonRuntime, RuntimeArtifact
from kivyforge.platforms.windows import WindowsBundleError, runtime_stage
from kivyforge.platforms.windows.petools import (
    IMAGE_FILE_MACHINE_AMD64,
    IMAGE_FILE_MACHINE_I386,
)


def _pe_bytes(machine: int) -> bytes:
    """Minimal but valid PE header carrying *machine* (petools reads this)."""
    buf = bytearray(0x48)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, 0x40)  # PE header offset
    buf[0x40:0x44] = b"PE\x00\x00"
    struct.pack_into("<H", buf, 0x44, machine)
    return bytes(buf)


def _make_pbs_archive(path, *, with_core_vc: bool = True) -> None:
    """A minimal PBS-shaped Windows install_only archive (python/ root)."""
    root = path.parent / f"stage_{path.stem}"
    py = root / "python"
    (py / "Lib" / "site-packages").mkdir(parents=True)
    (py / "DLLs").mkdir(parents=True)
    (py / "python.exe").write_bytes(b"MZ")
    (py / "python313.dll").write_bytes(b"MZ")
    if with_core_vc:
        (py / "vcruntime140.dll").write_bytes(b"MZ")
        (py / "vcruntime140_1.dll").write_bytes(b"MZ")
    with tarfile.open(path, "w:gz") as tf:
        tf.add(py, arcname="python")


def _runtime(archs=("amd64",)):
    return PythonRuntime(
        provider="python-build-standalone",
        version="3.13.14",
        artifacts=tuple(
            RuntimeArtifact(arch=a, url=f"https://e/{a}.tar.gz", sha256="x")
            for a in archs
        ),
        floor=None,
    )


def _fake_system_dir(tmp_path, *dlls):
    d = tmp_path / "system32"
    d.mkdir()
    for name in dlls:
        (d / name).write_bytes(b"MZ-sys")
    return d


class TestStageRuntime:
    def test_stages_whole_prefix(self, tmp_path, monkeypatch):
        archive = tmp_path / "amd64.tar.gz"
        _make_pbs_archive(archive)
        monkeypatch.setattr(runtime_stage, "_fetch", lambda *a, **k: archive)
        home = tmp_path / "bundle" / "python"
        result = runtime_stage.stage_runtime(
            _runtime(),
            "amd64",
            home,
            project_root=tmp_path,
            system_dir=_fake_system_dir(tmp_path),
        )
        assert result == home
        assert (home / "python.exe").exists()
        assert (home / "Lib" / "site-packages").is_dir()
        assert (home / "vcruntime140.dll").exists()

    def test_missing_arch_artifact_fails(self, tmp_path, monkeypatch):
        archive = tmp_path / "amd64.tar.gz"
        _make_pbs_archive(archive)
        monkeypatch.setattr(runtime_stage, "_fetch", lambda *a, **k: archive)
        with pytest.raises(WindowsBundleError, match="no arm64 runtime artifact"):
            runtime_stage.stage_runtime(
                _runtime(("amd64",)), "arm64", tmp_path / "home", project_root=tmp_path
            )

    def test_existing_home_is_replaced(self, tmp_path, monkeypatch):
        archive = tmp_path / "amd64.tar.gz"
        _make_pbs_archive(archive)
        monkeypatch.setattr(runtime_stage, "_fetch", lambda *a, **k: archive)
        home = tmp_path / "bundle" / "python"
        home.mkdir(parents=True)
        stale = home / "stale-leftover.txt"
        stale.write_text("from a previous stage")

        result = runtime_stage.stage_runtime(
            _runtime(),
            "amd64",
            home,
            project_root=tmp_path,
            system_dir=_fake_system_dir(tmp_path),
        )
        assert result == home
        assert (home / "python.exe").exists()
        assert not stale.exists()  # stale prefix must be wiped, not merged


class TestEnsureVcRuntime:
    def test_noop_when_core_present(self, tmp_path):
        home = tmp_path / "python"
        home.mkdir()
        for dll in runtime_stage.CORE_VC_RUNTIME:
            (home / dll).write_bytes(b"MZ")
        (home / runtime_stage.CXX_VC_RUNTIME).write_bytes(b"MZ")
        placed = runtime_stage.ensure_vc_runtime(home, system_dir=tmp_path / "none")
        assert placed == ()

    def test_places_missing_core_from_system(self, tmp_path):
        home = tmp_path / "python"
        home.mkdir()
        (home / "vcruntime140.dll").write_bytes(b"MZ")  # one present, one missing
        sysdir = _fake_system_dir(tmp_path, "vcruntime140_1.dll")
        placed = runtime_stage.ensure_vc_runtime(home, system_dir=sysdir)
        assert placed == ("vcruntime140_1.dll",)
        assert (home / "vcruntime140_1.dll").read_bytes() == b"MZ-sys"

    def test_raises_when_core_unavailable(self, tmp_path):
        home = tmp_path / "python"
        home.mkdir()
        with pytest.raises(WindowsBundleError, match="cannot start without the VC"):
            runtime_stage.ensure_vc_runtime(home, system_dir=tmp_path / "empty")

    def test_best_effort_msvcp_placed_when_available(self, tmp_path):
        home = tmp_path / "python"
        home.mkdir()
        for dll in runtime_stage.CORE_VC_RUNTIME:
            (home / dll).write_bytes(b"MZ")
        sysdir = _fake_system_dir(tmp_path, runtime_stage.CXX_VC_RUNTIME)
        placed = runtime_stage.ensure_vc_runtime(home, system_dir=sysdir)
        assert placed == (runtime_stage.CXX_VC_RUNTIME,)

    def test_best_effort_msvcp_skipped_when_absent(self, tmp_path):
        home = tmp_path / "python"
        home.mkdir()
        for dll in runtime_stage.CORE_VC_RUNTIME:
            (home / dll).write_bytes(b"MZ")
        placed = runtime_stage.ensure_vc_runtime(home, system_dir=tmp_path / "empty")
        assert placed == ()

    def test_wrong_arch_core_dll_is_refused(self, tmp_path):
        # A 32-bit (x86) System32 fallback (WOW64 redirection) must never satisfy
        # an amd64 bundle's missing core runtime.
        home = tmp_path / "python"
        home.mkdir()
        (home / "vcruntime140.dll").write_bytes(b"MZ")  # one present, one missing
        sysdir = tmp_path / "system32"
        sysdir.mkdir()
        (sysdir / "vcruntime140_1.dll").write_bytes(_pe_bytes(IMAGE_FILE_MACHINE_I386))
        with pytest.raises(WindowsBundleError, match="no amd64 copy was found"):
            runtime_stage.ensure_vc_runtime(home, arch="amd64", system_dir=sysdir)
        assert not (home / "vcruntime140_1.dll").is_file()

    def test_wrong_arch_msvcp_is_skipped(self, tmp_path):
        home = tmp_path / "python"
        home.mkdir()
        for dll in runtime_stage.CORE_VC_RUNTIME:
            (home / dll).write_bytes(b"MZ")
        sysdir = tmp_path / "system32"
        sysdir.mkdir()
        (sysdir / runtime_stage.CXX_VC_RUNTIME).write_bytes(
            _pe_bytes(IMAGE_FILE_MACHINE_I386)
        )
        placed = runtime_stage.ensure_vc_runtime(home, arch="amd64", system_dir=sysdir)
        assert placed == ()
        assert not (home / runtime_stage.CXX_VC_RUNTIME).is_file()

    def test_matching_arch_dll_is_copied(self, tmp_path):
        home = tmp_path / "python"
        home.mkdir()
        for dll in runtime_stage.CORE_VC_RUNTIME:
            (home / dll).write_bytes(b"MZ")
        sysdir = tmp_path / "system32"
        sysdir.mkdir()
        (sysdir / runtime_stage.CXX_VC_RUNTIME).write_bytes(
            _pe_bytes(IMAGE_FILE_MACHINE_AMD64)
        )
        placed = runtime_stage.ensure_vc_runtime(home, arch="amd64", system_dir=sysdir)
        assert placed == (runtime_stage.CXX_VC_RUNTIME,)
        assert (home / runtime_stage.CXX_VC_RUNTIME).is_file()


class TestFetch:
    def test_derives_filename_and_delegates(self, tmp_path, monkeypatch):
        captured = {}

        def fake_fetch_artifact(
            *, name, sha256, filename, url, project_root, cache, no_cache
        ):
            captured.update(
                name=name,
                sha256=sha256,
                filename=filename,
                url=url,
                project_root=project_root,
                no_cache=no_cache,
            )
            return tmp_path / filename

        monkeypatch.setattr(runtime_stage, "fetch_artifact", fake_fetch_artifact)
        artifact = RuntimeArtifact(
            arch="amd64",
            url="https://e/cpython-3.13.14-amd64.tar.gz",
            sha256="deadbeef",
        )
        result = runtime_stage._fetch(
            artifact, "amd64", tmp_path, cache=None, no_cache=True
        )
        assert result == tmp_path / "cpython-3.13.14-amd64.tar.gz"
        assert captured["filename"] == "cpython-3.13.14-amd64.tar.gz"
        assert captured["sha256"] == "deadbeef"
        assert captured["no_cache"] is True

    def test_url_without_filename_falls_back_to_arch_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            runtime_stage,
            "fetch_artifact",
            lambda **kw: tmp_path / kw["filename"],
        )
        artifact = RuntimeArtifact(arch="amd64", url="https://e/", sha256="x")
        result = runtime_stage._fetch(
            artifact, "amd64", tmp_path, cache=None, no_cache=False
        )
        assert result.name == "python-amd64.tar.gz"

    def test_download_error_wrapped(self, tmp_path, monkeypatch):
        def boom(**kw):
            raise DownloadError("network unreachable")

        monkeypatch.setattr(runtime_stage, "fetch_artifact", boom)
        artifact = RuntimeArtifact(arch="amd64", url="https://e/py.tar.gz", sha256="x")
        with pytest.raises(WindowsBundleError, match="network unreachable"):
            runtime_stage._fetch(
                artifact, "amd64", tmp_path, cache=None, no_cache=False
            )


class TestDefaultSystemDir:
    def test_64bit_interpreter_uses_default_system32(self, monkeypatch):
        monkeypatch.setattr(runtime_stage.struct, "calcsize", lambda fmt: 8)
        assert runtime_stage._default_system_dir() == runtime_stage.DEFAULT_SYSTEM_DIR

    def test_32bit_interpreter_prefers_sysnative_when_present(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(runtime_stage.struct, "calcsize", lambda fmt: 4)
        sysroot = tmp_path / "Windows"
        (sysroot / "Sysnative").mkdir(parents=True)
        monkeypatch.setattr(runtime_stage.os, "environ", {"SystemRoot": str(sysroot)})
        assert runtime_stage._default_system_dir() == sysroot / "Sysnative"

    def test_32bit_interpreter_falls_back_without_sysnative(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(runtime_stage.struct, "calcsize", lambda fmt: 4)
        sysroot = tmp_path / "Windows"
        sysroot.mkdir()
        monkeypatch.setattr(runtime_stage.os, "environ", {"SystemRoot": str(sysroot)})
        assert runtime_stage._default_system_dir() == runtime_stage.DEFAULT_SYSTEM_DIR


class TestExtract:
    def test_rejects_unknown_provider(self, tmp_path):
        archive = tmp_path / "a.tar.gz"
        _make_pbs_archive(archive)
        with pytest.raises(WindowsBundleError, match="no runtime staging layout"):
            runtime_stage._extract(archive, tmp_path / "out", "mystery")

    def test_rejects_path_traversal(self, tmp_path):
        evil = tmp_path / "evil.tar.gz"
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "f").write_text("x")
        with tarfile.open(evil, "w:gz") as tf:
            ti = tf.gettarinfo(payload / "f", arcname="../escape")
            with (payload / "f").open("rb") as fh:
                tf.addfile(ti, fh)
        with pytest.raises(WindowsBundleError, match="unsafe path"):
            runtime_stage._extract(evil, tmp_path / "out", "python-build-standalone")

    def test_rejects_symlink_target_escape(self, tmp_path):
        # A safely *named* member whose symlink target escapes the tree passes
        # the name check but must be caught by the hardened extraction filter.
        evil = tmp_path / "evil.tar.gz"
        with tarfile.open(evil, "w:gz") as tf:
            link = tarfile.TarInfo("python/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../escape"
            tf.addfile(link)
        with pytest.raises(WindowsBundleError, match="unsafe member"):
            runtime_stage._extract(evil, tmp_path / "out", "python-build-standalone")

    def test_corrupt_archive_reports_extraction_failure(self, tmp_path):
        bogus = tmp_path / "not-a-real-archive.tar.gz"
        bogus.write_bytes(b"this is not gzip/tar data at all")
        with pytest.raises(WindowsBundleError, match="failed to extract"):
            runtime_stage._extract(bogus, tmp_path / "out", "python-build-standalone")
