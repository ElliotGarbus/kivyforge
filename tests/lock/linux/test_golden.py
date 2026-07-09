"""Golden lockfile: exact serialized pylock.linux.toml output."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.linux import build_linux_lockfile, dumps

from .conftest import FakeLinuxResolver, FakeRuntimeProvider

GOLDEN = Path(__file__).parents[1] / "data" / "golden_pylock.linux.toml"


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
