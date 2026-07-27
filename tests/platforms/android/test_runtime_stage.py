"""python.org Android runtime extraction (android/03 channel 2)."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from kivyforge.platforms.android.stage.runtime import (
    RuntimeStageError,
    extract_runtime,
    stdlib_dir,
)


def _make_runtime_tarball(tmp_path: Path, *, wrapper: str | None = None) -> Path:
    """Build a minimal python.org-shaped tarball (README.md, prefix/lib/...)."""
    root = tmp_path / "build"
    base = (root / wrapper) if wrapper else root
    (base / "prefix" / "lib" / "python3.14").mkdir(parents=True)
    (base / "prefix" / "lib" / "libpython3.14.so").write_bytes(b"fake-so")
    (base / "prefix" / "lib" / "python3.14" / "os.py").write_text(
        "# stdlib", encoding="utf-8"
    )
    (base / "README.md").write_text("readme", encoding="utf-8")

    tarball = tmp_path / "runtime.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(root, arcname=".")
    return tarball


class TestExtractRuntime:
    def test_extracts_and_returns_prefix(self, tmp_path):
        tarball = _make_runtime_tarball(tmp_path)
        dest = tmp_path / "extracted"
        prefix = extract_runtime(tarball, dest)
        assert prefix == dest / "prefix"
        assert (prefix / "lib" / "libpython3.14.so").is_file()
        assert (dest / "README.md").is_file()

    def test_tolerates_single_wrapping_directory(self, tmp_path):
        tarball = _make_runtime_tarball(tmp_path, wrapper="python-3.14.6-embed-android")
        dest = tmp_path / "extracted"
        prefix = extract_runtime(tarball, dest)
        assert prefix.name == "prefix"
        assert (prefix / "lib" / "libpython3.14.so").is_file()

    def test_replaces_existing_destination(self, tmp_path):
        dest = tmp_path / "extracted"
        dest.mkdir()
        (dest / "stale.txt").write_text("old", encoding="utf-8")
        tarball = _make_runtime_tarball(tmp_path)
        extract_runtime(tarball, dest)
        assert not (dest / "stale.txt").exists()

    def test_corrupt_archive_raises(self, tmp_path):
        bad = tmp_path / "bad.tar.gz"
        bad.write_bytes(b"not a tarball at all, just plain text padded out long")
        with pytest.raises(RuntimeStageError, match="could not extract"):
            extract_runtime(bad, tmp_path / "extracted")

    def test_missing_prefix_layout_raises(self, tmp_path):
        root = tmp_path / "build"
        (root / "unexpected").mkdir(parents=True)
        (root / "unexpected" / "file.txt").write_text("x", encoding="utf-8")
        tarball = tmp_path / "runtime.tar.gz"
        with tarfile.open(tarball, "w:gz") as tf:
            tf.add(root, arcname=".")
        with pytest.raises(RuntimeStageError, match="documented prefix"):
            extract_runtime(tarball, tmp_path / "extracted")

    def test_multiple_wrapping_candidates_ambiguous(self, tmp_path):
        root = tmp_path / "build"
        (root / "a" / "prefix").mkdir(parents=True)
        (root / "b" / "prefix").mkdir(parents=True)
        tarball = tmp_path / "runtime.tar.gz"
        with tarfile.open(tarball, "w:gz") as tf:
            tf.add(root, arcname=".")
        with pytest.raises(RuntimeStageError, match="documented prefix"):
            extract_runtime(tarball, tmp_path / "extracted")


class TestStdlibDir:
    def test_returns_stdlib_path(self, tmp_path):
        prefix = tmp_path / "prefix"
        (prefix / "lib" / "python3.14").mkdir(parents=True)
        assert stdlib_dir(prefix, "python3.14") == prefix / "lib" / "python3.14"

    def test_missing_stdlib_raises(self, tmp_path):
        prefix = tmp_path / "prefix"
        prefix.mkdir()
        with pytest.raises(RuntimeStageError, match="no stdlib"):
            stdlib_dir(prefix, "python3.14")
