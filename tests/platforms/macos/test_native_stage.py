"""Native-binary staging into ``Resources/bin`` (single file, zip, guards)."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from kivyforge.lock.wheelruntime.model import (
    LockedNativeBinary,
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.macos import AppBundleError
from kivyforge.platforms.macos.native_stage import stage_native_binaries


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lock(*native_binaries):
    return WheelRuntimeLock(
        platform="macos",
        requires_python=">=3.15",
        packages=(),
        python_runtime=PythonRuntime(
            provider="pbs",
            version="3.15.0",
            artifacts=(RuntimeArtifact(arch="arm64", url="https://e/a", sha256="c"),),
        ),
        archs=("arm64",),
        kivyforge_version="0.1.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
        native_binaries=tuple(native_binaries),
    )


def _vendor(project_root: Path, rel: str, data: bytes) -> str:
    p = project_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return rel


class TestStageNativeBinaries:
    def test_empty_is_noop(self, tmp_path):
        resources = tmp_path / "res"
        resources.mkdir()
        stage_native_binaries(_lock(), resources, project_root=tmp_path)
        assert not (resources / "bin").exists()

    def test_single_file_copied_executable(self, tmp_path):
        data = b"\xca\xfe\xba\xbe roll"
        rel = _vendor(tmp_path, "binaries/roll", data)
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(LockedNativeBinary("roll", "1.0", _sha256(data), path=rel))
        stage_native_binaries(lock, resources, project_root=tmp_path)
        staged = resources / "bin" / "roll"
        assert staged.read_bytes() == data
        assert os.access(staged, os.X_OK)

    def test_single_file_keeps_source_basename(self, tmp_path):
        # A dylib must retain its extension (staged "as-is"), not be renamed to
        # the config key, so ctypes can load it by filename.
        data = b"dylib"
        rel = _vendor(tmp_path, "binaries/libgreet.dylib", data)
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(LockedNativeBinary("libgreet", "1.0", _sha256(data), path=rel))
        stage_native_binaries(lock, resources, project_root=tmp_path)
        assert (resources / "bin" / "libgreet.dylib").read_bytes() == data
        assert not (resources / "bin" / "libgreet").exists()

    def test_zip_extracted(self, tmp_path):
        archive = tmp_path / "binaries" / "pack.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("libfoo.dylib", b"dylib bytes")
            zf.writestr("helper", b"helper bytes")
        rel = "binaries/pack.zip"
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(
            LockedNativeBinary("pack", "1.0", _sha256(archive.read_bytes()), path=rel)
        )
        stage_native_binaries(lock, resources, project_root=tmp_path)
        bin_dir = resources / "bin"
        assert (bin_dir / "libfoo.dylib").read_bytes() == b"dylib bytes"
        assert (bin_dir / "helper").read_bytes() == b"helper bytes"
        assert os.access(bin_dir / "helper", os.X_OK)

    def test_zip_traversal_rejected(self, tmp_path):
        archive = tmp_path / "binaries" / "evil.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape", b"nope")
        rel = "binaries/evil.zip"
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(
            LockedNativeBinary("evil", "1.0", _sha256(archive.read_bytes()), path=rel)
        )
        with pytest.raises(AppBundleError, match="unsafe path"):
            stage_native_binaries(lock, resources, project_root=tmp_path)

    def test_hash_mismatch_raises_app_error(self, tmp_path):
        rel = _vendor(tmp_path, "binaries/roll", b"payload")
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(LockedNativeBinary("roll", "1.0", "0" * 64, path=rel))
        with pytest.raises(AppBundleError):
            stage_native_binaries(lock, resources, project_root=tmp_path)

    def test_missing_vendored_file_raises_app_error(self, tmp_path):
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(
            LockedNativeBinary("roll", "1.0", "0" * 64, path="binaries/absent")
        )
        with pytest.raises(AppBundleError):
            stage_native_binaries(lock, resources, project_root=tmp_path)


class TestCollisions:
    def test_two_single_files_same_basename_rejected(self, tmp_path):
        a = _vendor(tmp_path, "binaries/a/tool", b"a")
        b = _vendor(tmp_path, "binaries/b/tool", b"b")
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(
            LockedNativeBinary("A", "1.0", _sha256(b"a"), path=a),
            LockedNativeBinary("B", "1.0", _sha256(b"b"), path=b),
        )
        with pytest.raises(AppBundleError, match=r"colliding path bin/tool"):
            stage_native_binaries(lock, resources, project_root=tmp_path)

    def test_two_zips_sharing_member_rejected(self, tmp_path):
        def make_zip(rel: str) -> tuple[str, str]:
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(p, "w") as zf:
                zf.writestr("libfoo.dylib", rel.encode())
            return rel, _sha256(p.read_bytes())

        a_rel, a_sha = make_zip("binaries/a.zip")
        b_rel, b_sha = make_zip("binaries/b.zip")
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(
            LockedNativeBinary("A", "1.0", a_sha, path=a_rel),
            LockedNativeBinary("B", "1.0", b_sha, path=b_rel),
        )
        with pytest.raises(AppBundleError, match=r"colliding path bin/libfoo.dylib"):
            stage_native_binaries(lock, resources, project_root=tmp_path)

    def test_single_file_vs_zip_member_rejected(self, tmp_path):
        single = _vendor(tmp_path, "binaries/helper", b"single")
        zpath = tmp_path / "binaries" / "pack.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("helper", b"from-zip")
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(
            LockedNativeBinary("single", "1.0", _sha256(b"single"), path=single),
            LockedNativeBinary(
                "pack", "1.0", _sha256(zpath.read_bytes()), path="binaries/pack.zip"
            ),
        )
        with pytest.raises(AppBundleError, match=r"colliding path bin/helper"):
            stage_native_binaries(lock, resources, project_root=tmp_path)

    def test_distinct_names_no_false_positive(self, tmp_path):
        a = _vendor(tmp_path, "binaries/roll", b"roll")
        b = _vendor(tmp_path, "binaries/libgreet.dylib", b"greet")
        resources = tmp_path / "res"
        resources.mkdir()
        lock = _lock(
            LockedNativeBinary("roll", "1.0", _sha256(b"roll"), path=a),
            LockedNativeBinary("libgreet", "1.0", _sha256(b"greet"), path=b),
        )
        stage_native_binaries(lock, resources, project_root=tmp_path)
        assert (resources / "bin" / "roll").exists()
        assert (resources / "bin" / "libgreet.dylib").exists()
