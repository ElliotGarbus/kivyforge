"""Gradle wrapper invocation (android/06)."""

from __future__ import annotations

import os
import subprocess

import pytest

from kivyforge.platforms.android import gradlew as gradlew_mod
from kivyforge.platforms.android.gradlew import GradleError, run_gradle


def _wrapper_name() -> str:
    return "gradlew.bat" if os.name == "nt" else "gradlew"


class TestRunGradle:
    def test_missing_wrapper_raises(self, tmp_path):
        with pytest.raises(GradleError, match="no Gradle wrapper"):
            run_gradle(tmp_path, ["assembleDebug"])

    def test_success_runs_expected_command(self, tmp_path, monkeypatch):
        (tmp_path / _wrapper_name()).write_text("#!/bin/sh", encoding="utf-8")
        captured = {}

        def fake_run(cmd, cwd, env, text):
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            captured["env"] = env
            captured["text"] = text
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
        assert captured["text"] is True

    def test_nonzero_exit_raises_gradle_error(self, tmp_path, monkeypatch):
        (tmp_path / _wrapper_name()).write_text("#!/bin/sh", encoding="utf-8")

        def fake_run(cmd, cwd, env, text):
            return subprocess.CompletedProcess(cmd, 1)

        monkeypatch.setattr(gradlew_mod.subprocess, "run", fake_run)
        with pytest.raises(GradleError, match="exit 1"):
            run_gradle(tmp_path, ["assembleDebug"])

    def test_env_overrides_merged_into_environment(self, tmp_path, monkeypatch):
        (tmp_path / _wrapper_name()).write_text("#!/bin/sh", encoding="utf-8")
        monkeypatch.setenv("EXISTING_VAR", "1")
        captured = {}

        def fake_run(cmd, cwd, env, text):
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
