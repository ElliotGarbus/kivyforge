"""Fixtures shared by the macOS bundle tests."""

from __future__ import annotations

import pytest

from kivyforge.platforms.macos import bundle


@pytest.fixture
def faked(monkeypatch):
    """Replace the heavy staging/signing steps with recorders."""
    calls = {
        "runtime": [],
        "wheels": [],
        "native": [],
        "sign": [],
        "icns": [],
        "launcher": None,
        "order": [],
    }

    def fake_runtime(runtime, arch, home, **k):
        home.mkdir(parents=True, exist_ok=True)
        (home / "bin").mkdir()
        (home / "bin" / "python3").write_text("x")
        calls["runtime"].append(arch)
        calls["order"].append("runtime")
        return home

    def fake_wheels(packages, arch, lib, **k):
        lib.mkdir(parents=True, exist_ok=True)
        calls["wheels"].append(arch)
        calls["order"].append("wheels")

    def fake_native(lock, resources, **k):
        calls["native"].append(tuple(b.name for b in lock.native_binaries))
        calls["order"].append("native")

    def fake_launcher(dest, *, entry_point, arch):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\xcf\xfa\xed\xfe")  # Mach-O magic placeholder
        calls["launcher"] = (entry_point, arch)

    monkeypatch.setattr(bundle, "stage_runtime", fake_runtime)
    monkeypatch.setattr(bundle, "stage_wheels", fake_wheels)
    monkeypatch.setattr(bundle, "stage_native_binaries", fake_native)
    monkeypatch.setattr(bundle, "build_launcher", fake_launcher)
    monkeypatch.setattr(
        bundle, "sign_bundle_adhoc", lambda app: calls["sign"].append(app) or 1
    )
    monkeypatch.setattr(
        bundle, "generate_icns", lambda src, dst: calls["icns"].append((src, dst))
    )
    return calls
