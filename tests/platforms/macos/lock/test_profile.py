"""macOS lock profile: the bundled-Python-version contract."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kivyforge.config.errors import ConfigError
from kivyforge.platforms.macos.lock.profile import MacosProfile


class TestPythonVersion:
    def test_returns_configured_version(self):
        cfg = SimpleNamespace(macos_required=SimpleNamespace(python_version="3.13.14"))
        assert MacosProfile().python_version(cfg) == "3.13.14"

    def test_missing_version_raises_not_silent_default(self):
        # No hidden 3.15.0 fallback: an unset version surfaces as a clear error
        # rather than silently pinning an unexpected (possibly unreleased) Python.
        cfg = SimpleNamespace(macos_required=SimpleNamespace(python_version=None))
        with pytest.raises(ConfigError, match="python.*version"):
            MacosProfile().python_version(cfg)
