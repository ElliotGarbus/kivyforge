"""Golden lockfile: exact serialized pylock.linux.toml output."""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from pathlib import Path

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.linux.lock import build_linux_lockfile, dumps

from .conftest import FakeLinuxResolver, FakeRuntimeProvider

GOLDEN = Path(__file__).parents[1] / "data" / "golden_pylock.linux.toml"
GOLDEN_NATIVE = (
    Path(__file__).parents[1] / "data" / "golden_pylock.linux.native.toml"
)


def test_golden_lockfile(linux_pyproject, tmp_path, monkeypatch):
    # Pin kivyforge_version so the golden file is stable across releases.
    import kivyforge.lock.wheelruntime.builder as builder

    monkeypatch.setattr(builder, "__version__", "3.0.0")
    cfg = load_config_from_text(
        linux_pyproject, require_ios=False, require_linux=True, project_root=tmp_path
    )
    lock = build_linux_lockfile(
        cfg,
        linux_pyproject,
        project_root=tmp_path,
        resolver=FakeLinuxResolver(),
        runtime_provider=FakeRuntimeProvider(floor="2.17"),
        now=datetime(2026, 5, 27, 0, 0, 0, tzinfo=UTC),
    )
    rendered = dumps(lock)

    if not GOLDEN.exists():  # first run materializes the golden file
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(rendered, encoding="utf-8")

    expected = GOLDEN.read_text(encoding="utf-8")
    assert rendered == expected, (
        "serialized lockfile drifted from the golden file. If this change is "
        "intentional, delete tests/lock/data/golden_pylock.linux.toml and re-run."
    )


def test_golden_lockfile_with_native_binary(tmp_path, monkeypatch):
    # A golden lock that pins a vendored [[tool.kivyforge.native_binaries]] entry,
    # so the serialized shape of the Linux native-binaries channel is nailed down.
    import kivyforge.lock.wheelruntime.builder as builder

    monkeypatch.setattr(builder, "__version__", "3.0.0")
    pyproject = textwrap.dedent(
        """
        [project]
        name = "myapp"
        version = "1.0.0"
        requires-python = ">=3.15"
        dependencies = ["kivy>=3.0,<4", "more-itertools>=10.5"]

        [tool.kivy]
        app_dir = "src"

        [tool.kivy.linux]
        schema_version = 1
        app_id = "org.example.myapp"

        [tool.kivy.linux.python]
        version = "3.15.0"

        [tool.kivy.linux.native.binaries]
        roll = { version = "0.1.0", source = "binaries/linux/roll" }
        """
    ).strip()
    vendored = tmp_path / "binaries" / "linux" / "roll"
    vendored.parent.mkdir(parents=True)
    vendored.write_bytes(b"\x7fELF roll helper")

    cfg = load_config_from_text(
        pyproject, require_ios=False, require_linux=True, project_root=tmp_path
    )
    lock = build_linux_lockfile(
        cfg,
        pyproject,
        project_root=tmp_path,
        resolver=FakeLinuxResolver(),
        runtime_provider=FakeRuntimeProvider(floor="2.17"),
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
        "tests/platforms/linux/data/golden_pylock.linux.native.toml and re-run."
    )
    (nb,) = lock.native_binaries
    assert nb.name == "roll"
    assert nb.path == "binaries/linux/roll"
    assert "[[tool.kivyforge.native_binaries]]" in rendered
