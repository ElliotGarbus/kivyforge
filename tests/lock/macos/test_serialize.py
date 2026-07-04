"""pylock.macos.toml round-trip + drift + malformed handling."""

from __future__ import annotations

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.lock.macos.builder import build_macos_lockfile
from kivyforge.lock.macos.serialize import dumps, loads
from kivyforge.lock.reader import LockError

from .conftest import FakeMacosResolver, FakeRuntimeProvider


def _build(text, tmp_path, **kw):
    cfg = load_config_from_text(
        text, require_ios=False, require_macos=True, project_root=tmp_path
    )
    return build_macos_lockfile(
        cfg,
        text,
        project_root=tmp_path,
        resolver=FakeMacosResolver(**kw),
        runtime_provider=FakeRuntimeProvider(floor="11.0"),
    )


class TestRoundTrip:
    def test_round_trips(self, macos_pyproject, tmp_path):
        lock = _build(macos_pyproject, tmp_path)
        again = loads(dumps(lock))
        assert again.archs == lock.archs
        assert again.requires_python == lock.requires_python
        assert {p.name for p in again.packages} == {p.name for p in lock.packages}
        assert again.python_runtime.provider == "python-build-standalone"
        assert again.python_runtime.floor == "11.0"
        assert {a.arch for a in again.python_runtime.artifacts} == {"arm64", "x86_64"}

    def test_deterministic(self, macos_pyproject, tmp_path):
        lock = _build(macos_pyproject, tmp_path)
        assert dumps(lock) == dumps(loads(dumps(lock)))

    def test_has_expected_tables(self, macos_pyproject, tmp_path):
        text = dumps(_build(macos_pyproject, tmp_path))
        assert "[tool.kivyforge.python_runtime]" in text
        assert "[[tool.kivyforge.python_runtime.artifacts]]" in text
        assert "[[packages]]" in text


class TestMalformed:
    def test_not_toml(self):
        with pytest.raises(LockError, match="not valid TOML"):
            loads("this is = = not toml")

    def test_missing_tool_table(self):
        with pytest.raises(LockError, match="missing the \\[tool.kivyforge\\]"):
            loads('lock-version = "1.0"\n')

    def test_missing_runtime(self):
        text = 'lock-version = "1.0"\n[tool.kivyforge]\nschema_version = 1\n'
        with pytest.raises(LockError, match="python_runtime"):
            loads(text)

    def test_future_lock_version(self):
        text = 'lock-version = "9.0"\n[tool.kivyforge]\nschema_version = 1\n'
        with pytest.raises(LockError, match="newer than"):
            loads(text)

    def test_future_schema_version(self):
        text = (
            'lock-version = "1.0"\n[tool.kivyforge]\nschema_version = 99\n'
            "[tool.kivyforge.python_runtime]\nprovider='pbs'\nversion='3'\n"
            "[[tool.kivyforge.python_runtime.artifacts]]\n"
            "arch='arm64'\nurl='u'\nsha256='s'\n"
        )
        with pytest.raises(LockError, match="newer than"):
            loads(text)
