"""Shared test fixtures.

iOS is a cross-compiled target with no host default, so every platform-aware
verb needs an explicit target (``-p ios`` or ``KIVYFORGE_PLATFORM``). The iOS
test suite predates the resolution chain and invokes verbs without a flag, so we
default the session platform to ``ios`` for all tests. Tests that exercise the
resolution chain itself override or clear this explicitly.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_target_platform(monkeypatch):
    monkeypatch.setenv("KIVYFORGE_PLATFORM", "ios")
