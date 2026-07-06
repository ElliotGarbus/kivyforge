"""Ad-hoc + Developer ID signing walk and order Mach-O inside-out (hermetic)."""

from __future__ import annotations

import plistlib
import struct
from pathlib import Path

from kivyforge.macos import signing


def _macho(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(">I", 0xFEEDFACF))


def _bundle(tmp_path) -> Path:
    app = tmp_path / "My.app"
    _macho(app / "Contents" / "Resources" / "python" / "bin" / "python3")
    _macho(app / "Contents" / "Resources" / "lib" / "foo" / "_c.so")
    (app / "Contents" / "Resources" / "app").mkdir(parents=True)
    (app / "Contents" / "Resources" / "app" / "main.py").write_text("print(1)")
    return app


def test_signs_deepest_first_then_bundle(tmp_path, monkeypatch):
    app = _bundle(tmp_path)

    order = []
    monkeypatch.setattr(signing, "codesign_adhoc", lambda p: order.append(p))

    count = signing.sign_bundle_adhoc(app)

    assert count == 3  # two Mach-O + the bundle
    # The bundle is signed last.
    assert order[-1] == app
    # Nested binaries are signed deepest-first.
    depths = [len(p.parts) for p in order[:-1]]
    assert depths == sorted(depths, reverse=True)
    # The plain .py source is never signed.
    assert all(p.suffix != ".py" for p in order)


class TestDeveloperId:
    def test_deep_sign_order_and_entitlements(self, tmp_path, monkeypatch):
        app = _bundle(tmp_path)

        calls = []

        def fake_sign(path, identity, *, entitlements=None):
            ent = plistlib.loads(entitlements.read_bytes()) if entitlements else None
            calls.append((path, identity, ent))

        monkeypatch.setattr(signing, "codesign_identity", fake_sign)

        count = signing.sign_bundle_developer_id(
            app, "Developer ID Application: Jane (ABC)"
        )

        assert count == 3
        # Every call uses the identity.
        assert all(c[1] == "Developer ID Application: Jane (ABC)" for c in calls)
        # Nested binaries: no entitlements; the bundle seal: default entitlements.
        *nested, last = calls
        assert all(ent is None for _, _, ent in nested)
        assert last[0] == app
        assert last[2] == signing.DEFAULT_HARDENED_ENTITLEMENTS
        # Deepest-first for nested Mach-O.
        depths = [len(p.parts) for p, _, _ in nested]
        assert depths == sorted(depths, reverse=True)

    def test_user_entitlements_merge_and_win(self, tmp_path, monkeypatch):
        app = _bundle(tmp_path)
        seen = {}

        def fake_sign(path, identity, *, entitlements=None):
            if entitlements is not None:
                seen.update(plistlib.loads(entitlements.read_bytes()))

        monkeypatch.setattr(signing, "codesign_identity", fake_sign)

        signing.sign_bundle_developer_id(
            app,
            "Developer ID Application: Jane (ABC)",
            extra_entitlements={
                "com.apple.security.cs.disable-library-validation": False,
                "com.apple.security.device.camera": True,
            },
        )

        # User value overrides the default; extra keys are added.
        assert seen["com.apple.security.cs.disable-library-validation"] is False
        assert seen["com.apple.security.device.camera"] is True
        assert seen["com.apple.security.cs.allow-unsigned-executable-memory"] is True
