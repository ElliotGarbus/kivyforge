"""Smoke-test orchestration (android/06 --smoke) — hermetic."""

from __future__ import annotations

import pytest

from kivyforge.platforms.android import gradlew as gradlew_mod
from kivyforge.platforms.android.smoke import SmokeError, run_smoke


class TestRunSmoke:
    def test_debug_task(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(
            gradlew_mod, "run_gradle", lambda d, t, **k: calls.append((d, t))
        )
        # run_smoke imports run_gradle from .gradlew at module load; patch there.
        import kivyforge.platforms.android.smoke as smoke_mod

        monkeypatch.setattr(smoke_mod, "run_gradle", lambda d, t: calls.append((d, t)))
        run_smoke(tmp_path)
        assert calls == [(tmp_path, ["connectedDebugAndroidTest"])]

    def test_release_task(self, monkeypatch, tmp_path):
        calls = []
        import kivyforge.platforms.android.smoke as smoke_mod

        monkeypatch.setattr(smoke_mod, "run_gradle", lambda d, t: calls.append(t))
        run_smoke(tmp_path, release=True)
        assert calls == [["connectedReleaseAndroidTest"]]

    def test_failure_wrapped(self, monkeypatch, tmp_path):
        import kivyforge.platforms.android.smoke as smoke_mod

        def _boom(d, t):
            raise gradlew_mod.GradleError("gradle said no")

        monkeypatch.setattr(smoke_mod, "run_gradle", _boom)
        with pytest.raises(SmokeError, match="load-bearing runtime mechanism"):
            run_smoke(tmp_path)


class TestRunCliRouting:
    def test_android_only_flags_rejected_elsewhere(self):
        from click.testing import CliRunner

        from kivyforge.cli.run import run

        result = CliRunner().invoke(run, ["-p", "ios", "--smoke"])
        assert result.exit_code != 0
        assert "Android-only" in result.output
