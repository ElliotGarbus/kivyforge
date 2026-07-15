"""Golden lockfile: exact serialized pylock.windows.toml output."""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from pathlib import Path

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.windows.lock import build_windows_lockfile, dumps

from .conftest import FakeRuntimeProvider, FakeWindowsResolver

GOLDEN = Path(__file__).parents[1] / "data" / "golden_pylock.windows.toml"
GOLDEN_NATIVE = Path(__file__).parents[1] / "data" / "golden_pylock.windows.native.toml"


def test_golden_lockfile(windows_pyproject, tmp_path, monkeypatch):
    # Pin kivyforge_version so the golden file is stable across releases.
    import kivyforge.lock.wheelruntime.builder as builder

    monkeypatch.setattr(builder, "__version__", "3.0.0")
    cfg = load_config_from_text(
        windows_pyproject,
        require_ios=False,
        require_windows=True,
        project_root=tmp_path,
    )
    lock = build_windows_lockfile(
        cfg,
        windows_pyproject,
        project_root=tmp_path,
        resolver=FakeWindowsResolver(),
        runtime_provider=FakeRuntimeProvider(),
        now=datetime(2026, 5, 27, 0, 0, 0, tzinfo=UTC),
    )
    rendered = dumps(lock)

    if not GOLDEN.exists():  # first run materializes the golden file
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(rendered, encoding="utf-8")

    expected = GOLDEN.read_text(encoding="utf-8")
    assert rendered == expected, (
        "serialized lockfile drifted from the golden file. If this change is "
        "intentional, delete tests/platforms/windows/data/golden_pylock.windows.toml "
        "and re-run."
    )


def test_golden_lockfile_with_native_binary(tmp_path, monkeypatch):
    # A golden lock that pins a vendored [[tool.kivyforge.native_binaries]] entry,
    # so the serialized shape of the Windows native-binaries channel is nailed down.
    import kivyforge.lock.wheelruntime.builder as builder

    monkeypatch.setattr(builder, "__version__", "3.0.0")
    pyproject = textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.13"
        dependencies = ["kivy>=2.3,<3", "docutils"]

        [tool.kivy]
        app_dir = "src"

        [tool.kivy.windows]
        schema_version = 1
        app_id = "Example.MyApp"

        [tool.kivy.windows.python]
        version = "3.13.14"

        [tool.kivy.windows.native.binaries]
        sdk = { version = "0.1.0", source = "binaries/windows/sdk.dll" }
        """
    ).strip()
    vendored = tmp_path / "binaries" / "windows" / "sdk.dll"
    vendored.parent.mkdir(parents=True)
    vendored.write_bytes(b"MZ sdk payload")

    cfg = load_config_from_text(
        pyproject, require_ios=False, require_windows=True, project_root=tmp_path
    )
    lock = build_windows_lockfile(
        cfg,
        pyproject,
        project_root=tmp_path,
        resolver=FakeWindowsResolver(),
        runtime_provider=FakeRuntimeProvider(),
        now=datetime(2026, 5, 27, 0, 0, 0, tzinfo=UTC),
    )
    rendered = dumps(lock)

    if not GOLDEN_NATIVE.exists():  # first run materializes the golden file
        GOLDEN_NATIVE.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_NATIVE.write_text(rendered, encoding="utf-8")

    expected = GOLDEN_NATIVE.read_text(encoding="utf-8")
    assert rendered == expected, (
        "serialized native-binary lockfile drifted from the golden file. If this "
        "change is intentional, delete "
        "tests/platforms/windows/data/golden_pylock.windows.native.toml and re-run."
    )
    (nb,) = lock.native_binaries
    assert nb.name == "sdk"
    assert nb.path == "binaries/windows/sdk.dll"
    assert "[[tool.kivyforge.native_binaries]]" in rendered
