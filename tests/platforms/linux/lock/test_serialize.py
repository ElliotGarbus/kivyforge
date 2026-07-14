"""pylock.linux.toml round-trip + drift + malformed handling."""

from __future__ import annotations

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.reader import LockError
from kivyforge.platforms.linux.lock import build_linux_lockfile, dumps, loads

from .conftest import FakeLinuxResolver, FakeRuntimeProvider


def _build(text, tmp_path, **kw):
    cfg = load_config_from_text(
        text, require_ios=False, require_linux=True, project_root=tmp_path
    )
    return build_linux_lockfile(
        cfg,
        text,
        project_root=tmp_path,
        resolver=FakeLinuxResolver(**kw),
        runtime_provider=FakeRuntimeProvider(floor="2.17"),
    )


class TestRoundTrip:
    def test_round_trips(self, linux_pyproject, tmp_path):
        lock = _build(linux_pyproject, tmp_path)
        again = loads(dumps(lock))
        assert again.platform == "linux"
        assert again.archs == lock.archs
        assert again.requires_python == lock.requires_python
        assert {p.name for p in again.packages} == {p.name for p in lock.packages}
        assert again.python_runtime.provider == "python-build-standalone"
        assert again.python_runtime.floor == "2.17"
        assert {a.arch for a in again.python_runtime.artifacts} == {"x86_64"}

    def test_deterministic(self, linux_pyproject, tmp_path):
        lock = _build(linux_pyproject, tmp_path)
        assert dumps(lock) == dumps(loads(dumps(lock)))

    def test_has_expected_tables(self, linux_pyproject, tmp_path):
        text = dumps(_build(linux_pyproject, tmp_path))
        assert "[tool.kivyforge.python_runtime]" in text
        assert "[[tool.kivyforge.python_runtime.artifacts]]" in text
        assert "[[packages]]" in text


class TestNativeBinaries:
    _NB_TABLE = (
        "\n[tool.kivy.linux.native.binaries]\n"
        'roll = { version = "1.0", source = "binaries/linux/roll" }\n'
    )

    def test_vendored_binary_is_pinned(self, linux_pyproject, tmp_path):
        binaries = tmp_path / "binaries" / "linux"
        binaries.mkdir(parents=True)
        (binaries / "roll").write_bytes(b"\x7fELF roll helper")
        lock = _build(linux_pyproject + self._NB_TABLE, tmp_path)
        (nb,) = lock.native_binaries
        assert nb.name == "roll"
        assert nb.version == "1.0"
        assert nb.path == "binaries/linux/roll"
        assert nb.url is None
        assert len(nb.sha256) == 64

    def test_pin_round_trips(self, linux_pyproject, tmp_path):
        binaries = tmp_path / "binaries" / "linux"
        binaries.mkdir(parents=True)
        (binaries / "roll").write_bytes(b"payload")
        lock = _build(linux_pyproject + self._NB_TABLE, tmp_path)
        again = loads(dumps(lock))
        assert again.native_binaries == lock.native_binaries

    def test_serialized_has_native_binaries_table(self, linux_pyproject, tmp_path):
        binaries = tmp_path / "binaries" / "linux"
        binaries.mkdir(parents=True)
        (binaries / "roll").write_bytes(b"payload")
        text = dumps(_build(linux_pyproject + self._NB_TABLE, tmp_path))
        assert "[[tool.kivyforge.native_binaries]]" in text


class TestMalformed:
    def test_not_toml(self):
        with pytest.raises(LockError, match="not valid TOML"):
            loads("this is = = not toml")

    def test_missing_tool_table(self):
        with pytest.raises(LockError, match="missing the \\[tool.kivyforge\\]"):
            loads('lock-version = "1.0"\n')
