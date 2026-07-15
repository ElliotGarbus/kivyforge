"""Windows-safe in-place tree publishing (reserve/restore + retry)."""

from __future__ import annotations

import os

import pytest

from kivyforge.platforms.windows import WindowsBundleError, fsswap


class TestRenameWithRetry:
    """The rename helper rides out transient Windows sharing locks (WinError 5)."""

    def test_rides_out_transient_permission_error(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "f.txt").write_text("x")
        dst = tmp_path / "dst"
        real = os.replace
        calls = {"n": 0}

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] < 3:  # first two attempts "locked" (WinError 5)
                raise PermissionError(5, "Access is denied")
            return real(a, b)

        monkeypatch.setattr(fsswap.os, "replace", flaky)
        fsswap.rename_with_retry(src, dst, timeout=5, initial_delay=0)
        assert (dst / "f.txt").read_text() == "x"
        assert calls["n"] == 3

    def test_gives_up_after_timeout(self, tmp_path, monkeypatch):
        def always_locked(a, b):
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr(fsswap.os, "replace", always_locked)
        with pytest.raises(PermissionError):
            fsswap.rename_with_retry(
                tmp_path / "a", tmp_path / "b", timeout=0.2, initial_delay=0.01
            )


class TestReserveRestore:
    """A tree is written in place; any prior copy is reserved and restorable."""

    def test_reserve_none_when_absent(self, tmp_path):
        assert fsswap.reserve_previous(tmp_path / "nope") is None

    def test_reserve_persistent_lock_raises_actionable(self, tmp_path, monkeypatch):
        target = tmp_path / "App"
        target.mkdir()

        def always_locked(a, b):
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr(fsswap.os, "replace", always_locked)
        with pytest.raises(WindowsBundleError) as excinfo:
            fsswap.reserve_previous(target, timeout=0.05)
        msg = str(excinfo.value)
        assert str(target) in msg
        assert "another process" in msg

    def test_reserve_and_restore_roundtrip(self, tmp_path):
        target = tmp_path / "App"
        target.mkdir()
        (target / "keep.txt").write_text("prev")

        trash = fsswap.reserve_previous(target)
        assert trash is not None
        assert not target.exists()  # moved aside, not deleted
        assert (trash / "keep.txt").read_text() == "prev"

        # A failed write leaves a partial tree; restore must recover the prior.
        target.mkdir()
        (target / "partial.txt").write_text("half")
        fsswap.restore_previous(trash, target)
        assert (target / "keep.txt").read_text() == "prev"
        assert not (target / "partial.txt").exists()
        assert not trash.exists()

    def test_restore_none_is_noop(self, tmp_path):
        target = tmp_path / "App"
        target.mkdir()
        (target / "x.txt").write_text("x")
        fsswap.restore_previous(None, target)  # nothing was reserved
        assert (target / "x.txt").read_text() == "x"

    def test_discard_reserved(self, tmp_path):
        target = tmp_path / "App"
        target.mkdir()
        trash = fsswap.reserve_previous(target)
        assert trash is not None and trash.exists()
        fsswap.discard_reserved(trash)
        assert not trash.exists()
        fsswap.discard_reserved(None)  # no-op
