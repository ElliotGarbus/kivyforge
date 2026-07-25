"""The iOS workflow is macOS-only, and says so early (spec 05).

``IosPlatform.check_host_capability`` described this rule from the start, but
nothing called it: an off-macOS invocation got whatever error xcodebuild or SPM
raised first. These tests call the real helpers — the suite-wide autouse
fixture in ``tests/conftest.py`` no-ops them everywhere else — so a regression
that unwires the gate again fails here.
"""

from __future__ import annotations

import pytest

from kivyforge.cli._common import ToolchainError
from kivyforge.cli.lock import _require_host_toolchain
from kivyforge.platforms import get_platform
from kivyforge.platforms.base import HostCapabilityError
from kivyforge.platforms.ios import cli as ios_cli

# Captured at import, before the autouse fixture in tests/conftest.py replaces
# the module attribute with a no-op — these tests need the genuine gate.
# (``_require_host_toolchain`` is already bound to the real function by the
# from-import above, for the same reason.)
_require_macos_host = ios_cli._require_macos_host


class TestIosHostGate:
    @pytest.mark.parametrize("host", ["Linux", "Windows"])
    def test_ios_verbs_refuse_off_macos(self, monkeypatch, host):
        monkeypatch.setattr("platform.system", lambda: host)
        with pytest.raises(ToolchainError) as excinfo:
            _require_macos_host()
        message = str(excinfo.value)
        assert "requires macOS with Xcode" in message
        assert host in message  # names the host it actually found

    def test_ios_verbs_allowed_on_macos(self, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Darwin")
        _require_macos_host()  # must not raise

    def test_ios_lock_is_gated_too(self, monkeypatch):
        """Unlike every other backend, iOS `lock` needs the host toolchain:
        resolving declared Swift packages runs `swift package resolve`."""
        backend = get_platform("ios")
        monkeypatch.setattr("platform.system", lambda: "Linux")
        with pytest.raises(ToolchainError, match="requires macOS"):
            _require_host_toolchain(backend)

    def test_other_backends_lock_anywhere(self):
        """Android in particular: its lock is deliberately host-independent,
        so gating it would be a regression, not a tightening."""
        from kivyforge.cli.lock import _lock_ops

        assert _lock_ops("ios").requires_host_toolchain is True
        for platform in ("android", "macos", "linux", "windows"):
            assert _lock_ops(platform).requires_host_toolchain is False

    def test_raises_host_capability_error_underneath(self):
        with pytest.raises(HostCapabilityError):
            get_platform("ios").check_host_capability(host_system="Linux")
