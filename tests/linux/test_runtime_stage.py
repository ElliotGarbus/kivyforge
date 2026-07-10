"""Linux runtime extraction (hermetic; single arch, no lipo)."""

from __future__ import annotations

import tarfile

import pytest

from kivyforge.linux import AppDirError, runtime_stage
from kivyforge.lock.wheelruntime.model import PythonRuntime, RuntimeArtifact


def _make_pbs_archive(path, *, marker: bytes = b"x") -> None:
    """A minimal python-build-standalone-shaped install_only archive."""
    root = path.parent / f"stage_{path.stem}"
    (root / "python" / "bin").mkdir(parents=True)
    (root / "python" / "lib").mkdir(parents=True)
    (root / "python" / "bin" / "python3").write_bytes(marker)
    (root / "python" / "lib" / "note.txt").write_text("data")
    with tarfile.open(path, "w:gz") as tf:
        tf.add(root / "python", arcname="python")


def _runtime(archs=("x86_64",)):
    return PythonRuntime(
        provider="python-build-standalone",
        version="3.15.0",
        artifacts=tuple(
            RuntimeArtifact(arch=a, url=f"https://e/{a}.tar.gz", sha256="x")
            for a in archs
        ),
        floor="2.17",
    )


class TestStageRuntime:
    def test_copies_tree(self, tmp_path, monkeypatch):
        archive = tmp_path / "x86.tar.gz"
        _make_pbs_archive(archive)
        monkeypatch.setattr(runtime_stage, "_fetch", lambda *a, **k: archive)
        home = tmp_path / "appdir" / "usr" / "python"
        result = runtime_stage.stage_runtime(
            _runtime(), "x86_64", home, project_root=tmp_path
        )
        assert result == home
        assert (home / "bin" / "python3").exists()
        assert (home / "lib" / "note.txt").read_text() == "data"

    def test_missing_arch_artifact_fails(self, tmp_path, monkeypatch):
        archive = tmp_path / "x86.tar.gz"
        _make_pbs_archive(archive)
        monkeypatch.setattr(runtime_stage, "_fetch", lambda *a, **k: archive)
        with pytest.raises(AppDirError, match="no aarch64 runtime artifact"):
            runtime_stage.stage_runtime(
                _runtime(("x86_64",)),
                "aarch64",
                tmp_path / "home",
                project_root=tmp_path,
            )


class TestExtract:
    def test_rejects_non_pbs_archive(self, tmp_path):
        bad = tmp_path / "bad.tar.gz"
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "f").write_text("x")
        with tarfile.open(bad, "w:gz") as tf:
            tf.add(tmp_path / "other", arcname="other")
        with pytest.raises(AppDirError, match="top-level python/"):
            runtime_stage._extract(bad, tmp_path / "out", "python-build-standalone")

    def test_rejects_unknown_provider(self, tmp_path):
        archive = tmp_path / "x86.tar.gz"
        _make_pbs_archive(archive)
        with pytest.raises(AppDirError, match="no runtime staging layout"):
            runtime_stage._extract(archive, tmp_path / "out", "mystery-provider")

    def test_rejects_path_traversal(self, tmp_path):
        evil = tmp_path / "evil.tar.gz"
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "f").write_text("x")
        with tarfile.open(evil, "w:gz") as tf:
            ti = tf.gettarinfo(payload / "f", arcname="../escape")
            with (payload / "f").open("rb") as fh:
                tf.addfile(ti, fh)
        with pytest.raises(AppDirError, match="unsafe path"):
            runtime_stage._extract(evil, tmp_path / "out", "python-build-standalone")
