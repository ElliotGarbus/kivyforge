"""Ad-hoc signing walks + orders Mach-O inside-out (hermetic)."""

from __future__ import annotations

import struct

from kivyforge.macos import signing


def _macho(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(">I", 0xFEEDFACF))


def test_signs_deepest_first_then_bundle(tmp_path, monkeypatch):
    app = tmp_path / "My.app"
    _macho(app / "Contents" / "Resources" / "python" / "bin" / "python3")
    _macho(app / "Contents" / "Resources" / "lib" / "foo" / "_c.so")
    (app / "Contents" / "Resources" / "app").mkdir(parents=True)
    (app / "Contents" / "Resources" / "app" / "main.py").write_text("print(1)")

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
