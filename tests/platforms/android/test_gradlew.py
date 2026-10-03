"""Gradle wrapper invocation (android/06)."""

from __future__ import annotations

import os
import subprocess

import pytest

from kivyforge.cli._common import ToolchainError
from kivyforge.platforms.android import doctor as doctor_mod
from kivyforge.platforms.android import gradlew as gradlew_mod
from kivyforge.platforms.android.gradlew import GradleError, run_gradle
from kivyforge.report import diagnostics, exit_codes
from tests.platforms.android.test_doctor import FakeProbe


def _wrapper_name() -> str:
    return "gradlew.bat" if os.name == "nt" else "gradlew"


def _use_probe(monkeypatch, probe) -> None:
    monkeypatch.setattr(doctor_mod, "RealAndroidProbe", lambda: probe)


@pytest.fixture(autouse=True)
def _healthy_jdk(monkeypatch):
    """Whether this host has a JDK must not decide what these tests see."""
    _use_probe(monkeypatch, FakeProbe(java_home="/jdk"))


class TestJdkPreflight:
    """Gradle must not start without a compiler: a daemon started on a JRE keeps
    failing builds after a JDK is installed at the same path."""

    @pytest.fixture
    def gradle_runs(self, tmp_path, monkeypatch):
        (tmp_path / _wrapper_name()).write_text("#!/bin/sh", encoding="utf-8")
        ran = []

        def fake_run(cmd, **kw):
            ran.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(gradlew_mod.subprocess, "run", fake_run)
        return ran

    def test_a_jre_stops_gradle_starting(self, tmp_path, monkeypatch, gradle_runs):
        _use_probe(monkeypatch, FakeProbe(which={"java": "/usr/bin/java"}, javac=False))
        with pytest.raises(ToolchainError) as info:
            run_gradle(tmp_path, ["assembleDebug"])
        assert gradle_runs == []
        assert info.value.code == diagnostics.TOOLCHAIN_MISSING
        assert info.value.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert info.value.context == {"tool": "javac"}
        assert "is a JRE, not a JDK" in info.value.message
        assert "jdk-headless" in info.value.remediation

    def test_no_java_at_all_names_java(self, tmp_path, monkeypatch, gradle_runs):
        _use_probe(monkeypatch, FakeProbe())
        with pytest.raises(ToolchainError) as info:
            run_gradle(tmp_path, ["assembleDebug"])
        assert gradle_runs == []
        assert info.value.code == diagnostics.TOOLCHAIN_MISSING
        assert info.value.context == {"tool": "java"}

    def test_a_jdk_of_the_wrong_version_is_left_to_gradle(
        self, tmp_path, monkeypatch, gradle_runs
    ):
        """Present, not missing: no code here says otherwise, so Gradle reports it."""
        _use_probe(
            monkeypatch,
            FakeProbe(java_home="/jdk", java_banner='openjdk version "25.0.3"'),
        )
        run_gradle(tmp_path, ["assembleDebug"])
        assert len(gradle_runs) == 1

    def test_a_missing_wrapper_is_reported_first(self, tmp_path, monkeypatch):
        _use_probe(monkeypatch, FakeProbe(java_home="/jre", javac=False))
        with pytest.raises(GradleError, match="no Gradle wrapper"):
            run_gradle(tmp_path, ["assembleDebug"])


class TestRunGradle:
    def test_missing_wrapper_raises(self, tmp_path):
        with pytest.raises(GradleError, match="no Gradle wrapper"):
            run_gradle(tmp_path, ["assembleDebug"])

    def test_success_runs_expected_command(self, tmp_path, monkeypatch):
        (tmp_path / _wrapper_name()).write_text("#!/bin/sh", encoding="utf-8")
        captured = {}

        def fake_run(cmd, cwd, env, stdout, stderr, stdin=None):
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            captured["env"] = env
            captured["streams"] = (stdout, stderr)
            captured["stdin"] = stdin
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(gradlew_mod.subprocess, "run", fake_run)
        run_gradle(tmp_path, ["assembleDebug", "bundleRelease"])

        assert captured["cmd"][0] == str(tmp_path / _wrapper_name())
        assert captured["cmd"][1:] == [
            "--console=plain",
            "assembleDebug",
            "bundleRelease",
        ]
        assert captured["cwd"] == tmp_path
        # Both of Gradle's streams go to one stderr target, never inherited stdout.
        out, err = captured["streams"]
        assert out is not None and out == err
        # Gradle never prompts, but nothing should be able to: a tool that asks
        # for input gets EOF instead of hanging a CI job on an unanswerable prompt.
        assert captured["stdin"] == subprocess.DEVNULL

    def test_gradle_output_reaches_stderr_not_stdout(self, tmp_path, capfd):
        """A real child through a real descriptor: the production path."""
        if os.name == "nt":
            script = "@echo gradle says hi\r\n@echo gradle warns 1>&2\r\n"
        else:
            script = "#!/bin/sh\necho gradle says hi\necho gradle warns >&2\n"
        wrapper = tmp_path / _wrapper_name()
        wrapper.write_text(script, encoding="utf-8", newline="")
        wrapper.chmod(0o755)

        run_gradle(tmp_path, ["assembleDebug"])

        out, err = capfd.readouterr()
        assert out == ""
        assert "gradle says hi" in err
        assert "gradle warns" in err

    def test_nonzero_exit_raises_gradle_error(self, tmp_path, monkeypatch):
        (tmp_path / _wrapper_name()).write_text("#!/bin/sh", encoding="utf-8")

        def fake_run(cmd, cwd, env, stdout, stderr, stdin=None):
            return subprocess.CompletedProcess(cmd, 1)

        monkeypatch.setattr(gradlew_mod.subprocess, "run", fake_run)
        with pytest.raises(GradleError, match="exit 1"):
            run_gradle(tmp_path, ["assembleDebug"])

    def test_env_overrides_merged_into_environment(self, tmp_path, monkeypatch):
        (tmp_path / _wrapper_name()).write_text("#!/bin/sh", encoding="utf-8")
        monkeypatch.setenv("EXISTING_VAR", "1")
        captured = {}

        def fake_run(cmd, cwd, env, stdout, stderr, stdin=None):
            captured["env"] = env
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(gradlew_mod.subprocess, "run", fake_run)
        run_gradle(
            tmp_path,
            ["assembleDebug"],
            env_overrides={"ANDROID_HOME": "/opt/android-sdk"},
        )

        assert captured["env"]["ANDROID_HOME"] == "/opt/android-sdk"
        assert captured["env"]["EXISTING_VAR"] == "1"
