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

        monkeypatch.setattr(
            smoke_mod, "run_gradle", lambda d, t, **k: calls.append((d, t))
        )
        run_smoke(tmp_path, device="emulator-5554")
        assert calls == [(tmp_path, ["connectedDebugAndroidTest"])]

    def test_release_task(self, monkeypatch, tmp_path):
        calls = []
        import kivyforge.platforms.android.smoke as smoke_mod

        monkeypatch.setattr(smoke_mod, "run_gradle", lambda d, t, **k: calls.append(t))
        run_smoke(tmp_path, device="emulator-5554", release=True)
        assert calls == [["connectedReleaseAndroidTest"]]

    def test_only_the_chosen_device_runs_the_test(self, monkeypatch, tmp_path):
        """Gradle's connected test runs on every attached device unless
        ANDROID_SERIAL names one; the probe is built for the chosen device's
        ABI, so a second attached device (an emulator beside a phone) failed
        the run."""
        seen = {}
        import kivyforge.platforms.android.smoke as smoke_mod

        monkeypatch.setattr(smoke_mod, "run_gradle", lambda d, t, **k: seen.update(k))
        run_smoke(tmp_path, device="56051JEKB16396")
        assert seen["env_overrides"] == {"ANDROID_SERIAL": "56051JEKB16396"}

    def test_failure_wrapped(self, monkeypatch, tmp_path):
        import kivyforge.platforms.android.smoke as smoke_mod

        def _boom(d, t, **k):
            raise gradlew_mod.GradleError("gradle said no")

        monkeypatch.setattr(smoke_mod, "run_gradle", _boom)
        with pytest.raises(SmokeError, match="load-bearing runtime mechanism"):
            run_smoke(tmp_path, device="emulator-5554")


class TestRunCliRouting:
    def test_android_only_flags_rejected_elsewhere(self):
        from click.testing import CliRunner

        from kivyforge.cli.run import run

        result = CliRunner().invoke(run, ["-p", "ios", "--smoke"])
        assert result.exit_code != 0
        assert "Android-only" in result.output
