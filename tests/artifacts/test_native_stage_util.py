"""Platform-agnostic native-binary staging mechanics (shared util)."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from kivyforge.artifacts.native_stage_util import (
    NativeStageError,
    _claim,
    stage_binaries,
)
from kivyforge.lock.wheelruntime.model import LockedNativeBinary


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _vendor(project_root: Path, rel: str, data: bytes) -> str:
    p = project_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return rel


class TestStageBinaries:
    def test_empty_is_noop(self, tmp_path):
        parent = tmp_path / "parent"
        parent.mkdir()
        stage_binaries((), parent, project_root=tmp_path, bin_label="usr/bin")
        assert not (parent / "bin").exists()

    def test_single_file_copied_executable_basename_kept(self, tmp_path):
        data = b"\x7fELF greet"
        rel = _vendor(tmp_path, "binaries/libgreet.so", data)
        parent = tmp_path / "parent"
        parent.mkdir()
        stage_binaries(
            (LockedNativeBinary("libgreet", "1.0", _sha256(data), path=rel),),
            parent,
            project_root=tmp_path,
            bin_label="usr/bin",
        )
        staged = parent / "bin" / "libgreet.so"
        assert staged.read_bytes() == data
        assert os.access(staged, os.X_OK)
        # basename preserved, not renamed to the config key
        assert not (parent / "bin" / "libgreet").exists()

    def test_zip_extracted(self, tmp_path):
        archive = tmp_path / "binaries" / "pack.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("libfoo.so", b"foo bytes")
            zf.writestr("helper", b"helper bytes")
        parent = tmp_path / "parent"
        parent.mkdir()
        stage_binaries(
            (
                LockedNativeBinary(
                    "pack",
                    "1.0",
                    _sha256(archive.read_bytes()),
                    path="binaries/pack.zip",
                ),
            ),
            parent,
            project_root=tmp_path,
            bin_label="usr/bin",
        )
        bin_dir = parent / "bin"
        assert (bin_dir / "libfoo.so").read_bytes() == b"foo bytes"
        assert (bin_dir / "helper").read_bytes() == b"helper bytes"
        assert os.access(bin_dir / "helper", os.X_OK)

    def test_zip_traversal_rejected(self, tmp_path):
        archive = tmp_path / "binaries" / "evil.zip"
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape", b"nope")
        parent = tmp_path / "parent"
        parent.mkdir()
        with pytest.raises(NativeStageError, match="unsafe path"):
            stage_binaries(
                (
                    LockedNativeBinary(
                        "evil",
                        "1.0",
                        _sha256(archive.read_bytes()),
                        path="binaries/evil.zip",
                    ),
                ),
                parent,
                project_root=tmp_path,
                bin_label="usr/bin",
            )

    def test_collision_raises_native_stage_error(self, tmp_path):
        a = _vendor(tmp_path, "binaries/a/tool", b"a")
        b = _vendor(tmp_path, "binaries/b/tool", b"b")
        parent = tmp_path / "parent"
        parent.mkdir()
        with pytest.raises(NativeStageError, match=r"colliding path bin/tool"):
            stage_binaries(
                (
                    LockedNativeBinary("A", "1.0", _sha256(b"a"), path=a),
                    LockedNativeBinary("B", "1.0", _sha256(b"b"), path=b),
                ),
                parent,
                project_root=tmp_path,
                bin_label="usr/bin",
            )


class TestSafeExtractAndClaim:
    def test_safe_extract_rejects_absolute_and_parent_members(self, tmp_path):
        from kivyforge.artifacts.native_stage_util import _safe_extract

        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../outside", b"x")
        target = tmp_path / "dest"
        target.mkdir()
        with (
            zipfile.ZipFile(archive) as zf,
            pytest.raises(NativeStageError, match="unsafe path"),
        ):
            _safe_extract(zf, target)

    def test_claim_reserves_then_rejects_duplicate(self):
        claimed: dict[str, str] = {}
        _claim(claimed, Path("tool"), "A", "usr/bin")
        assert claimed == {"tool": "A"}
        with pytest.raises(NativeStageError, match=r"colliding path bin/tool"):
            _claim(claimed, Path("tool"), "B", "usr/bin")

    def test_claim_uses_bin_label_in_message(self):
        claimed: dict[str, str] = {"tool": "A"}
        with pytest.raises(NativeStageError, match=r"unique path in usr/bin"):
            _claim(claimed, Path("tool"), "B", "usr/bin")
