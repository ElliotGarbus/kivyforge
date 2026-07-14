"""Native-binary staging into the AppDir's ``usr/bin`` (Linux wrapper + wiring).

The detailed single-file / ``.zip`` / ``.tar.gz`` / collision mechanics are
covered once in ``tests/artifacts/test_native_stage_util.py``; these tests prove
the Linux wrapper's error translation (``NativeStageError`` -> ``AppDirError``)
and the ``build_appdir`` wiring (native staged after wheels; ``usr/bin`` absent
when the table is empty).
"""

from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.wheelruntime.model import (
    LockedNativeBinary,
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.linux import AppDirError, bundle
from kivyforge.platforms.linux.native_stage import stage_native_binaries


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _vendor(project_root: Path, rel: str, data: bytes) -> str:
    p = project_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return rel


def _lock(*native_binaries, archs=("x86_64",)):
    return WheelRuntimeLock(
        platform="linux",
        requires_python=">=3.15",
        packages=(),
        python_runtime=PythonRuntime(
            provider="python-build-standalone",
            version="3.15.0",
            artifacts=tuple(
                RuntimeArtifact(arch=a, url=f"https://e/{a}", sha256="x") for a in archs
            ),
            floor="2.17",
        ),
        archs=archs,
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256="0" * 64,
        tool_kivyforge_schema_version=1,
        native_binaries=tuple(native_binaries),
    )


class TestStageNativeBinaries:
    def test_empty_is_noop(self, tmp_path):
        usr = tmp_path / "usr"
        usr.mkdir()
        stage_native_binaries(_lock(), usr, project_root=tmp_path)
        assert not (usr / "bin").exists()

    def test_single_file_staged_executable(self, tmp_path):
        data = b"\x7fELF roll"
        rel = _vendor(tmp_path, "binaries/linux/roll", data)
        usr = tmp_path / "usr"
        usr.mkdir()
        lock = _lock(LockedNativeBinary("roll", "1.0", _sha256(data), path=rel))
        stage_native_binaries(lock, usr, project_root=tmp_path)
        staged = usr / "bin" / "roll"
        assert staged.read_bytes() == data
        assert os.access(staged, os.X_OK)

    def test_tar_gz_extracted_via_wrapper(self, tmp_path):
        archive = tmp_path / "binaries" / "linux" / "sdk.tar.gz"
        archive.parent.mkdir(parents=True)
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("libgreet.so")
            payload = b"greet bytes"
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        usr = tmp_path / "usr"
        usr.mkdir()
        lock = _lock(
            LockedNativeBinary(
                "sdk", "1.0", _sha256(archive.read_bytes()), path="binaries/linux/sdk.tar.gz"
            )
        )
        stage_native_binaries(lock, usr, project_root=tmp_path)
        assert (usr / "bin" / "libgreet.so").read_bytes() == b"greet bytes"

    def test_hash_mismatch_raises_appdir_error(self, tmp_path):
        rel = _vendor(tmp_path, "binaries/linux/roll", b"payload")
        usr = tmp_path / "usr"
        usr.mkdir()
        lock = _lock(LockedNativeBinary("roll", "1.0", "0" * 64, path=rel))
        with pytest.raises(AppDirError):
            stage_native_binaries(lock, usr, project_root=tmp_path)

    def test_missing_vendored_file_raises_appdir_error(self, tmp_path):
        usr = tmp_path / "usr"
        usr.mkdir()
        lock = _lock(
            LockedNativeBinary("roll", "1.0", "0" * 64, path="binaries/linux/absent")
        )
        with pytest.raises(AppDirError):
            stage_native_binaries(lock, usr, project_root=tmp_path)

    def test_collision_raises_appdir_error(self, tmp_path):
        a = _vendor(tmp_path, "binaries/a/roll", b"a")
        b = _vendor(tmp_path, "binaries/b/roll", b"b")
        usr = tmp_path / "usr"
        usr.mkdir()
        lock = _lock(
            LockedNativeBinary("A", "1.0", _sha256(b"a"), path=a),
            LockedNativeBinary("B", "1.0", _sha256(b"b"), path=b),
        )
        with pytest.raises(AppDirError, match=r"colliding path bin/roll"):
            stage_native_binaries(lock, usr, project_root=tmp_path)


_PYPROJECT = (
    "[project]\nname='myapp'\nversion='1.2.0'\nrequires-python='>=3.15'\n"
    "dependencies=[]\n"
    "[tool.kivy]\ndisplay_name='My App'\napp_dir='src'\nentry_point='main'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.myapp'\n"
    "[tool.kivy.linux.python]\nversion='3.15.0'\n"
)


@pytest.fixture
def faked(monkeypatch):
    """Replace the heavy stages with recorders, tracking call order."""
    order: list[str] = []

    def fake_runtime(runtime, arch, home, **k):
        home.mkdir(parents=True, exist_ok=True)
        (home / "bin").mkdir()
        (home / "bin" / "python3").write_text("x")
        order.append("runtime")
        return home

    def fake_wheels(packages, arch, lib, **k):
        lib.mkdir(parents=True, exist_ok=True)
        order.append("wheels")

    def fake_icons(config, project_root, appdir):
        return False

    def fake_apprun(dest, *, entry_point, app_id, has_native_binaries=False):
        dest.write_text("#!/bin/sh\n")
        dest.chmod(0o755)

    def fake_desktop(config, dest):
        dest.write_text("[Desktop Entry]\n")

    def fake_validate_desktop(dest):
        pass

    real_stage_native = bundle.stage_native_binaries

    def spy_native(lock, usr, **k):
        order.append("native")
        return real_stage_native(lock, usr, **k)

    monkeypatch.setattr(bundle, "stage_runtime", fake_runtime)
    monkeypatch.setattr(bundle, "stage_wheels", fake_wheels)
    monkeypatch.setattr(bundle, "stage_icons", fake_icons)
    monkeypatch.setattr(bundle, "build_apprun", fake_apprun)
    monkeypatch.setattr(bundle, "write_desktop_entry", fake_desktop)
    monkeypatch.setattr(bundle, "validate_desktop_file", fake_validate_desktop)
    monkeypatch.setattr(bundle, "stage_native_binaries", spy_native)
    return order


def _config(text=_PYPROJECT):
    return load_config_from_text(text, require_ios=False, require_linux=True)


def _project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    return tmp_path


class TestBuildAppdirWiring:
    def test_native_staged_after_wheels_into_usr_bin(self, tmp_path, faked):
        root = _project(tmp_path)
        data = b"\x7fELF roll"
        rel = _vendor(root, "binaries/linux/roll", data)
        lock = _lock(LockedNativeBinary("roll", "1.0", _sha256(data), path=rel))
        appdir = bundle.build_appdir(
            _config(), lock, root, staging_dir=tmp_path / "out", echo=lambda *a: None
        )
        assert (appdir / "usr" / "bin" / "roll").read_bytes() == data
        # native binaries stage strictly after wheels (so a fetch failure discards
        # the half-built tree, and the atomic-swap discipline covers it for free).
        assert order_index(faked, "native") > order_index(faked, "wheels")

    def test_usr_bin_absent_when_no_native_binaries(self, tmp_path, faked):
        root = _project(tmp_path)
        appdir = bundle.build_appdir(
            _config(), _lock(), root, staging_dir=tmp_path / "out", echo=lambda *a: None
        )
        assert not (appdir / "usr" / "bin").exists()
        assert "native" not in faked


def order_index(order: list[str], key: str) -> int:
    return order.index(key)
