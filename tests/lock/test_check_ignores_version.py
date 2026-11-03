"""``lock --check`` ignores which kivyforge wrote the lock, on every platform.

The recorded ``kivyforge_version`` says nothing about whether a lock still
matches its project. Comparing it made every kivyforge upgrade report every lock
as stale, with an empty diff, because ``diff_summary`` has nothing to show for it.

Driven through ``_lock_ops`` and committed locks, so this covers the comparison
each platform's ``--check`` really uses. The hermetic suite did not catch the bug
because its locks are built by the running kivyforge, so their versions always
match.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from kivyforge.cli.lock import _lock_ops

_REPO = Path(__file__).resolve().parents[2]

LOCKS = {
    "android": "examples/mobile/hello-android/pylock.android.toml",
    "ios": "examples/mobile/hello-kivy/pylock.ios.toml",
    "linux": "tests/fixtures/apps/linux-gate/pylock.linux.toml",
    "macos": "tests/fixtures/apps/macos-gate/pylock.macos.toml",
    "windows": "tests/fixtures/apps/windows-gate/pylock.windows.toml",
}


@pytest.mark.parametrize("platform", sorted(LOCKS))
class TestCheckComparison:
    def _load(self, platform: str):
        ops = _lock_ops(platform)
        return ops, ops.load(_REPO / LOCKS[platform])

    def test_a_different_kivyforge_version_is_not_drift(self, platform):
        ops, lock = self._load(platform)
        upgraded = dataclasses.replace(lock, kivyforge_version="99.0.0")
        assert upgraded.kivyforge_version != lock.kivyforge_version
        assert ops.semantic_equal(lock, upgraded)

    def test_a_real_difference_is_still_drift(self, platform):
        ops, lock = self._load(platform)
        changed = dataclasses.replace(
            lock,
            kivyforge_version="99.0.0",
            packages=tuple(
                dataclasses.replace(p, version="99.0.0") for p in lock.packages
            ),
        )
        assert not ops.semantic_equal(lock, changed)
