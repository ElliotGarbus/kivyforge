"""The pinned NDK/CMake are installed visibly before Gradle would do it (#74)."""

from __future__ import annotations

import os

import pytest

from kivyforge.platforms.android import gradlew as gradlew_mod
from kivyforge.platforms.android import sdk_packages as sp
from kivyforge.platforms.android.toolchain import CMAKE_VERSION, NDK_VERSION

_BAT = ".bat" if os.name == "nt" else ""


@pytest.fixture
def sdk(tmp_path):
    return tmp_path / "sdk"


def _install_all(sdk):
    for package in sp.PINNED:
        (sdk / package.installed_dir).mkdir(parents=True)


def _with_sdkmanager(sdk):
    tool = sdk / "cmdline-tools" / "latest" / "bin" / f"sdkmanager{_BAT}"
    tool.parent.mkdir(parents=True)
    tool.write_text("")
    return tool


class Recorder:
    def __init__(self):
        self.lines: list[str] = []
        self.transfers: list[tuple] = []

    def progress(self, text):
        self.lines.append(text)

    def transfer(self, *args):
        self.transfers.append(args)


def test_pins_follow_the_toolchain():
    assert {p.package_id for p in sp.PINNED} == {
        f"ndk;{NDK_VERSION}",
        f"cmake;{CMAKE_VERSION}",
    }


def test_no_sdk_is_left_to_doctor_and_gradle(sdk):
    rec = Recorder()
    sp.ensure_sdk_packages(None, on_progress=rec.progress)
    assert rec.lines == []


def test_nothing_to_do_when_installed(sdk, monkeypatch):
    _install_all(sdk)
    monkeypatch.setattr(sp, "run_streaming", lambda *a, **k: pytest.fail("ran"))
    rec = Recorder()
    sp.ensure_sdk_packages(sdk, on_progress=rec.progress)
    assert rec.lines == []


def test_without_sdkmanager_it_warns_that_gradle_will_download(sdk):
    sdk.mkdir()
    rec = Recorder()
    sp.ensure_sdk_packages(sdk, on_progress=rec.progress)
    assert len(rec.lines) == 2
    assert f"NDK {NDK_VERSION} is not installed" in rec.lines[0]
    assert "Gradle shows no progress" in rec.lines[0]


def test_installs_with_progress(sdk, monkeypatch):
    _with_sdkmanager(sdk)
    (sdk / "cmake" / CMAKE_VERSION).mkdir(parents=True)  # only the NDK is missing
    calls = []

    def fake_run(cmd, *, on_segment, on_quiet=None, **kw):
        calls.append(cmd)
        for segment in (
            "Loading package information...",
            "[=====                    ] 12% Downloading android-ndk.zip...",
            "[=========================] 100% Unzipping... source.properties",
        ):
            on_segment(segment)
        (sdk / "ndk" / NDK_VERSION).mkdir(parents=True)
        return 0, ""

    monkeypatch.setattr(sp, "run_streaming", fake_run)
    rec = Recorder()
    sp.ensure_sdk_packages(sdk, on_progress=rec.progress, on_transfer=rec.transfer)
    assert calls[0][1:] == [f"--sdk_root={sdk}", f"ndk;{NDK_VERSION}"]
    assert rec.transfers == [
        (f"[sdk] NDK {NDK_VERSION}", 12, 100, "percent"),
        (f"[sdk] NDK {NDK_VERSION}", 100, 100, "percent"),
    ]
    assert rec.lines[-1] == f"[sdk] NDK {NDK_VERSION}: installed"


def test_unaccepted_license_is_explained_not_fatal(sdk, monkeypatch):
    """sdkmanager prints the license and exits 0 without installing."""
    _with_sdkmanager(sdk)
    (sdk / "cmake" / CMAKE_VERSION).mkdir(parents=True)
    monkeypatch.setattr(
        sp, "run_streaming", lambda *a, **k: (0, "License android-sdk-license:\n...")
    )
    rec = Recorder()
    sp.ensure_sdk_packages(sdk, on_progress=rec.progress)
    assert "sdkmanager --licenses" in rec.lines[-1]
    assert "Gradle will try instead" in rec.lines[-1]


def test_a_failed_launch_falls_back_to_gradle(sdk, monkeypatch):
    _with_sdkmanager(sdk)
    (sdk / "cmake" / CMAKE_VERSION).mkdir(parents=True)

    def boom(*a, **k):
        raise OSError("no java")

    monkeypatch.setattr(sp, "run_streaming", boom)
    rec = Recorder()
    sp.ensure_sdk_packages(sdk, on_progress=rec.progress)
    assert "could not run sdkmanager" in rec.lines[-1]


def test_quiet_install_reports_it_is_still_going(sdk, monkeypatch):
    _with_sdkmanager(sdk)
    (sdk / "cmake" / CMAKE_VERSION).mkdir(parents=True)

    def slow(cmd, *, on_segment, on_quiet=None, **kw):
        assert on_quiet is not None
        on_quiet(95.0)
        (sdk / "ndk" / NDK_VERSION).mkdir(parents=True)
        return 0, ""

    monkeypatch.setattr(sp, "run_streaming", slow)
    rec = Recorder()
    sp.ensure_sdk_packages(sdk, on_progress=rec.progress)
    assert f"[sdk] NDK {NDK_VERSION}: still installing (1m 35s)" in rec.lines


def test_run_gradle_installs_missing_packages_first(tmp_path, monkeypatch):
    """Every Gradle run passes through here, so no build path can skip it."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ("gradlew.bat" if os.name == "nt" else "gradlew")).write_text("")
    order = []
    monkeypatch.setattr(gradlew_mod, "_require_jdk", lambda: None)
    monkeypatch.setattr(
        gradlew_mod,
        "_install_missing_sdk_packages",
        lambda events: order.append(("sdk", events)),
    )

    class Done:
        returncode = 0

    monkeypatch.setattr(
        gradlew_mod.subprocess,
        "run",
        lambda *a, **k: order.append(("gradle",)) or Done(),
    )
    gradlew_mod.run_gradle(project, ["assembleDebug"])
    assert [step[0] for step in order] == ["sdk", "gradle"]
