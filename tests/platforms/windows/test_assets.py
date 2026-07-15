"""Vendored-binary discovery + SHA-256 integrity checks (host-agnostic)."""

from __future__ import annotations

import hashlib

import pytest

from kivyforge.platforms.windows import WindowsBundleError
from kivyforge.platforms.windows import assets as A


def _redirect(monkeypatch, tmp_path):
    """Point the asset layer at a temp vendor dir + manifest."""
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    manifest = vendor / "SHA256SUMS"
    monkeypatch.setattr(A, "VENDOR_DIR", vendor)
    monkeypatch.setattr(A, "MANIFEST", manifest)
    return vendor, manifest


def _write(vendor, manifest, name, data: bytes, *, pin: bytes | None = None):
    (vendor / name).write_bytes(data)
    digest = hashlib.sha256(pin if pin is not None else data).hexdigest()
    existing = manifest.read_text() if manifest.is_file() else "# manifest\n"
    manifest.write_text(existing + f"{digest}  {name}\n")


class TestManifest:
    def test_missing_manifest_raises(self, monkeypatch, tmp_path):
        _redirect(monkeypatch, tmp_path)
        with pytest.raises(WindowsBundleError, match="manifest missing"):
            A.read_manifest()

    def test_parses_entries(self, monkeypatch, tmp_path):
        vendor, manifest = _redirect(monkeypatch, tmp_path)
        manifest.write_text("# c\n" + ("a" * 64) + "  launcher-amd64.exe\n")
        assert A.read_manifest()["launcher-amd64.exe"] == "a" * 64


class TestVerifiedAsset:
    def test_launcher_ok(self, monkeypatch, tmp_path):
        vendor, manifest = _redirect(monkeypatch, tmp_path)
        _write(vendor, manifest, A.LAUNCHER_NAME, b"MZ launcher bytes")
        assert A.vendored_launcher() == vendor / A.LAUNCHER_NAME

    def test_rcedit_ok(self, monkeypatch, tmp_path):
        vendor, manifest = _redirect(monkeypatch, tmp_path)
        _write(vendor, manifest, A.RCEDIT_NAME, b"MZ rcedit bytes")
        assert A.vendored_rcedit() == vendor / A.RCEDIT_NAME

    def test_missing_binary_raises(self, monkeypatch, tmp_path):
        vendor, manifest = _redirect(monkeypatch, tmp_path)
        manifest.write_text("# c\n" + ("a" * 64) + f"  {A.LAUNCHER_NAME}\n")
        with pytest.raises(WindowsBundleError, match="is missing"):
            A.vendored_launcher()

    def test_no_pin_raises(self, monkeypatch, tmp_path):
        vendor, manifest = _redirect(monkeypatch, tmp_path)
        (vendor / A.LAUNCHER_NAME).write_bytes(b"bytes")
        manifest.write_text("# empty\n")
        with pytest.raises(WindowsBundleError, match="no pinned SHA-256"):
            A.vendored_launcher()

    def test_tampered_binary_raises(self, monkeypatch, tmp_path):
        vendor, manifest = _redirect(monkeypatch, tmp_path)
        # Pin the hash of different bytes than what is on disk.
        _write(vendor, manifest, A.LAUNCHER_NAME, b"real bytes", pin=b"other bytes")
        with pytest.raises(WindowsBundleError, match="integrity check"):
            A.vendored_launcher()


class TestRealVendoredAssets:
    """The actually-shipped vendored binaries must pass their own pins."""

    def test_launcher_matches_pin(self):
        path = A.vendored_launcher()
        assert path.is_file()

    def test_rcedit_matches_pin(self):
        path = A.vendored_rcedit()
        assert path.is_file()
