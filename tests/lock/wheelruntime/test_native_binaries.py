"""Native-binary channel in the shared wheel+runtime lock engine.

Covers ``resolve_native_binaries`` (local, fake-downloader URL, offline,
escaping path), ``[[tool.kivyforge.native_binaries]]`` serialize round-trip
(with/without the table + old-lock parses to ``()``), and ``diff_summary``.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from kivyforge.config.model import NativeBinaryDep
from kivyforge.lock.wheelruntime import (
    LockedNativeBinary,
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
    diff_summary,
    dumps,
    loads,
    resolve_native_binaries,
)
from kivyforge.lock.wheelruntime.native_binaries import NativeBinaryResolverError


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeDownloader:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.urls: list[str] = []

    def fetch_to(self, url: str, dest: Path) -> None:
        self.urls.append(url)
        dest.write_bytes(self._payload)


class TestResolve:
    def test_empty_is_noop(self, tmp_path):
        assert resolve_native_binaries((), project_root=tmp_path) == ()

    def test_local_file(self, tmp_path):
        (tmp_path / "binaries").mkdir()
        f = tmp_path / "binaries" / "roll"
        f.write_bytes(b"\xca\xfe\xba\xbe helper")
        dep = NativeBinaryDep("roll", "1.0", "binaries/roll")
        (locked,) = resolve_native_binaries((dep,), project_root=tmp_path)
        assert locked == LockedNativeBinary(
            name="roll",
            version="1.0",
            sha256=_sha256_bytes(b"\xca\xfe\xba\xbe helper"),
            path="binaries/roll",
        )
        assert locked.url is None

    def test_url_via_fake_downloader(self, tmp_path):
        payload = b"vendor sdk bytes"
        dl = FakeDownloader(payload)
        dep = NativeBinaryDep("sdk", "2.0", "https://vendor.example/sdk.zip")
        (locked,) = resolve_native_binaries(
            (dep,), project_root=tmp_path, downloader=dl
        )
        assert locked.url == "https://vendor.example/sdk.zip"
        assert locked.path is None
        assert locked.sha256 == _sha256_bytes(payload)
        assert dl.urls == ["https://vendor.example/sdk.zip"]

    def test_url_offline_rejected(self, tmp_path):
        dep = NativeBinaryDep("sdk", "2.0", "https://vendor.example/sdk.zip")
        with pytest.raises(NativeBinaryResolverError, match="offline"):
            resolve_native_binaries((dep,), project_root=tmp_path, offline=True)

    def test_missing_local_rejected(self, tmp_path):
        dep = NativeBinaryDep("sdk", "2.0", "binaries/nope")
        with pytest.raises(NativeBinaryResolverError, match="not found"):
            resolve_native_binaries((dep,), project_root=tmp_path)

    def test_sorted_by_name(self, tmp_path):
        for n in ("zeta", "alpha"):
            f = tmp_path / n
            f.write_bytes(n.encode())
        deps = (
            NativeBinaryDep("zeta", "1", "zeta"),
            NativeBinaryDep("alpha", "1", "alpha"),
        )
        locked = resolve_native_binaries(deps, project_root=tmp_path)
        assert [b.name for b in locked] == ["alpha", "zeta"]


def _base_lock(**kw) -> WheelRuntimeLock:
    runtime = PythonRuntime(
        provider="python-build-standalone",
        version="3.15.0",
        artifacts=(RuntimeArtifact(arch="arm64", url="https://e/a", sha256="c" * 64),),
    )
    defaults = dict(
        platform="macos",
        requires_python=">=3.15",
        packages=(),
        python_runtime=runtime,
        archs=("arm64",),
        kivyforge_version="0.1.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
    )
    defaults.update(kw)
    return WheelRuntimeLock(**defaults)


class TestSerialize:
    def test_round_trip_with_table(self):
        lock = _base_lock(
            native_binaries=(
                LockedNativeBinary("sdk", "2.0", "a" * 64, url="https://e/sdk.zip"),
                LockedNativeBinary("roll", "1.0", "b" * 64, path="binaries/roll"),
            )
        )
        text = dumps(lock)
        assert "[[tool.kivyforge.native_binaries]]" in text
        again = loads(text, platform="macos")
        assert again.native_binaries == tuple(
            sorted(lock.native_binaries, key=lambda b: b.name)
        )

    def test_round_trip_without_table(self):
        lock = _base_lock()
        text = dumps(lock)
        assert "native_binaries" not in text
        assert loads(text, platform="macos").native_binaries == ()

    def test_old_lock_parses_to_empty(self):
        # A lock generated before this field existed simply lacks the table.
        text = dumps(_base_lock())
        assert loads(text, platform="macos").native_binaries == ()

    def test_deterministic(self):
        lock = _base_lock(
            native_binaries=(
                LockedNativeBinary("sdk", "2.0", "a" * 64, url="https://e/sdk.zip"),
            )
        )
        assert dumps(lock) == dumps(loads(dumps(lock), platform="macos"))

    def test_xor_url_path_enforced(self):
        text = dumps(_base_lock()).replace(
            "[tool.kivyforge.python_runtime]",
            "[[tool.kivyforge.native_binaries]]\nname='x'\nversion='1'\n"
            "sha256='a'\nurl='u'\npath='p'\n\n[tool.kivyforge.python_runtime]",
        )
        with pytest.raises(Exception, match="exactly one of url/path"):
            loads(text, platform="macos")


class TestDiffSummary:
    def test_added_removed_changed(self):
        old = _base_lock(
            native_binaries=(
                LockedNativeBinary("keep", "1.0", "1" * 64, path="a"),
                LockedNativeBinary("gone", "1.0", "2" * 64, path="b"),
                LockedNativeBinary("bump", "1.0", "3" * 64, path="c"),
            )
        )
        new = _base_lock(
            native_binaries=(
                LockedNativeBinary("keep", "1.0", "1" * 64, path="a"),
                LockedNativeBinary("bump", "2.0", "9" * 64, path="c"),
                LockedNativeBinary("fresh", "1.0", "4" * 64, path="d"),
            )
        )
        summary = "\n".join(diff_summary(old, new))
        assert "+ native binary fresh 1.0 (added)" in summary
        assert "- native binary gone 1.0 (removed)" in summary
        assert "~ native binary bump: 1.0 -> 2.0" in summary
        assert "keep" not in summary

    def test_no_change_no_lines(self):
        lock = _base_lock(
            native_binaries=(LockedNativeBinary("x", "1.0", "1" * 64, path="a"),)
        )
        assert diff_summary(lock, dataclasses.replace(lock)) == []
