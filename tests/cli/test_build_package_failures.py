"""Failure classification for ``build``/``package`` (proposal §4.4).

The §4.4 table is a contract: each row maps to a code, an exit status and, where
it says so, ``context`` keys. Nothing but a test keeps a raise site from quietly
drifting back to ``KF-ERROR`` / exit 1.
"""

from __future__ import annotations

import errno
import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.bundle.pycompile import PycompileError
from kivyforge.cli._common import ToolchainError
from kivyforge.cli.build import build
from kivyforge.cli.package import package
from kivyforge.platforms.ios import cli as ios_cli
from kivyforge.platforms.linux import AppDirError
from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.failures import ClassifiedError, reclassify, spawn_failure

# Bound at import, before the suite-wide autouse fixture replaces it.
_REAL_IOS_GATE = ios_cli._require_macos_host


def _fail(command, args):
    result = CliRunner().invoke(command, [*args, "--json"])
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    (diagnostic,) = envelope["diagnostics"]
    return result.exit_code, diagnostic, envelope


class TestWrap:
    def test_classification_survives_translation(self):
        exc = ClassifiedError("boom", code="KF-X", exit_code=5, context={"tool": "t"})
        wrapped = ToolchainError.wrap(exc)
        assert (wrapped.code, wrapped.exit_code) == ("KF-X", 5)
        assert wrapped.as_diagnostic().context == {"tool": "t"}

    def test_unclassified_errors_keep_the_old_behaviour(self):
        wrapped = ToolchainError.wrap(ValueError("plain"))
        assert wrapped.code == diagnostics.UNSPECIFIED
        assert wrapped.exit_code == exit_codes.CONFIG_ERROR


class TestReclassify:
    """A re-raise one layer down must not be where the classification stops.

    ``ToolchainError.wrap`` only sees the outermost exception. A backend that
    catches ``PycompileError`` and re-raises it as its own type with advice
    appended -- which all four desktop bundlers and both iOS staging paths do --
    silently downgraded a classified spawn failure to ``KF-ERROR``/exit ``1``
    until these forwarded.
    """

    def test_forwards_every_field(self):
        inner = ClassifiedError(
            "inner", code="KF-X", exit_code=3, context={"tool": "t"}
        )
        outer = ClassifiedError("outer, plus advice", **reclassify(inner))
        assert (outer.code, outer.exit_code) == ("KF-X", 3)
        assert outer.context == {"tool": "t"}

    def test_survives_the_whole_chain_to_the_cli_boundary(self):
        # PycompileError -> AppDirError -> ToolchainError, the Linux byte-compile
        # path, asserted end to end because each hop is a separate raise site.
        inner = PycompileError(
            "no interpreter", **spawn_failure("python3.13", OSError())
        )
        middle = AppDirError("byte-compiling failed, or set ...", **reclassify(inner))
        wrapped = ToolchainError.wrap(middle)
        assert wrapped.code == diagnostics.TOOLCHAIN_UNUSABLE
        assert wrapped.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert wrapped.as_diagnostic().context["tool"] == "python3.13"


class TestBuildToolFailed:
    def test_xcodebuild(self, ios, monkeypatch):
        from kivyforge.platforms.ios.xcode import CommandError

        def fail(argv, **kw):
            raise CommandError(argv, 65, "log")

        monkeypatch.setattr(ios, "run_command", fail)
        code, diag, _ = _fail(package, ["-p", "ios"])
        assert code == exit_codes.BUILD_FAILURE
        assert diag["code"] == diagnostics.BUILD_TOOL_FAILED
        assert diag["context"] == {"tool": "xcodebuild", "task": "archive"}

    def test_gradle(self, android, monkeypatch):
        from kivyforge.platforms.android import cli
        from kivyforge.platforms.android.gradlew import GradleError

        def fail(dest, tasks, **kw):
            raise GradleError("Gradle failed (exit 1)", returncode=1)

        monkeypatch.setattr(cli, "run_gradle", fail)
        code, diag, _ = _fail(build, ["-p", "android", "--debug"])
        assert code == exit_codes.BUILD_FAILURE
        assert diag["code"] == diagnostics.BUILD_TOOL_FAILED
        assert diag["context"] == {"tool": "gradle", "task": "assembleDebug"}

    def test_a_gradle_that_never_ran_is_not_a_build_failure(self, android, monkeypatch):
        from kivyforge.platforms.android import cli
        from kivyforge.platforms.android.gradlew import GradleError

        def fail(dest, tasks, **kw):
            raise GradleError("no Gradle wrapper")

        monkeypatch.setattr(cli, "run_gradle", fail)
        code, diag, _ = _fail(build, ["-p", "android", "--debug"])
        assert code == exit_codes.CONFIG_ERROR
        assert diag["code"] == diagnostics.UNSPECIFIED

    def test_appimagetool(self, tmp_path, monkeypatch):
        from kivyforge.artifacts.cache import ArtifactCache
        from kivyforge.platforms.linux import AppDirError, appimage

        monkeypatch.setattr(appimage, "_acquire", lambda *a: tmp_path / "tool")
        monkeypatch.setattr(appimage, "_executable_copy", lambda tool, c: tool)
        monkeypatch.setattr(
            appimage.subprocess,
            "run",
            lambda cmd, **k: subprocess.CompletedProcess(cmd, 2, "", "no"),
        )
        with pytest.raises(AppDirError) as info:
            appimage.build_appimage(
                tmp_path,
                tmp_path / "out.AppImage",
                "x86_64",
                project_root=tmp_path,
                cache=ArtifactCache(root=tmp_path / "cache"),
            )
        assert info.value.code == diagnostics.BUILD_TOOL_FAILED
        assert info.value.exit_code == exit_codes.BUILD_FAILURE
        assert info.value.context == {"tool": "appimagetool", "task": "package"}


class TestArtifactMissing:
    def test_android(self, android, monkeypatch):
        from kivyforge.platforms.android import cli

        monkeypatch.setattr(cli, "run_gradle", lambda dest, tasks, **kw: None)
        code, diag, _ = _fail(build, ["-p", "android", "--debug"])
        assert code == exit_codes.BUILD_FAILURE
        assert diag["code"] == diagnostics.ARTIFACT_MISSING

    def test_ios(self, ios, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            ios, "run_command", lambda argv, **kw: SimpleNamespace(returncode=0)
        )
        code, diag, _ = _fail(build, ["-p", "ios", "--simulator"])
        assert code == exit_codes.BUILD_FAILURE
        assert diag["code"] == diagnostics.ARTIFACT_MISSING


class TestSpawnFailures:
    @pytest.mark.parametrize(
        ("error", "expected_code", "extra"),
        [
            (FileNotFoundError(errno.ENOENT, "nope"), "KF-TOOLCHAIN-MISSING", {}),
            (
                PermissionError(errno.EACCES, "denied"),
                "KF-TOOLCHAIN-UNUSABLE",
                {"errno": "EACCES"},
            ),
        ],
    )
    def test_xcodebuild_that_cannot_start_still_gets_an_envelope(
        self, error, expected_code, extra
    ):
        from kivyforge.platforms.ios.xcode.runner import run_command

        def runner(argv, **kw):
            raise error

        with pytest.raises(ToolchainError) as info:
            run_command(["xcodebuild", "build"], runner=runner)
        assert info.value.code == expected_code
        assert info.value.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert info.value.context == {"tool": "xcodebuild", **extra}

    def test_gradle_wrapper_that_cannot_start(self, tmp_path, monkeypatch):
        import os

        from kivyforge.platforms.android import gradlew

        name = "gradlew.bat" if os.name == "nt" else "gradlew"
        (tmp_path / name).write_text("", encoding="utf-8")

        def denied(*a, **k):
            raise PermissionError(errno.EACCES, "denied")

        monkeypatch.setattr(gradlew.subprocess, "run", denied)
        with pytest.raises(ToolchainError) as info:
            gradlew.run_gradle(tmp_path, ["assembleDebug"])
        assert info.value.code == diagnostics.TOOLCHAIN_UNUSABLE
        assert info.value.exit_code == exit_codes.ENVIRONMENT_ERROR

    def test_missing_signtool(self, tmp_path, monkeypatch):
        from kivyforge.platforms.windows import WindowsBundleError, signing

        signer = signing.SigntoolSigner(
            thumbprint="ab" * 20,
            timestamp_url="http://timestamp.example",
            store_scope="user",
        )

        def missing(*a, **k):
            raise FileNotFoundError(errno.ENOENT, "signtool")

        monkeypatch.setattr(signing.subprocess, "run", missing)
        with pytest.raises(WindowsBundleError) as info:
            signer.sign([tmp_path / "app.exe"])
        assert info.value.code == diagnostics.TOOLCHAIN_MISSING


class TestLock:
    @pytest.mark.parametrize("backend", ["windows", "linux", "macos"])
    def test_desktop_missing_and_unreadable(self, backend, tmp_path):
        import importlib

        cli = importlib.import_module(f"kivyforge.platforms.{backend}.cli")
        with pytest.raises(ToolchainError) as missing:
            cli._load_lock(tmp_path)
        assert missing.value.code == diagnostics.LOCK_MISSING
        assert missing.value.exit_code == exit_codes.LOCK_DRIFT

        (tmp_path / f"pylock.{backend}.toml").write_text("{{ nope", encoding="utf-8")
        with pytest.raises(ToolchainError) as unreadable:
            cli._load_lock(tmp_path)
        assert unreadable.value.code == diagnostics.LOCK_UNREADABLE
        assert unreadable.value.exit_code == exit_codes.LOCK_DRIFT

    def test_ios_missing(self, tmp_path):
        from kivyforge.platforms.ios import cli

        with pytest.raises(ToolchainError) as info:
            cli._load_lock(tmp_path)
        assert info.value.code == diagnostics.LOCK_MISSING

    def test_android_drift(self, android):
        from kivyforge.platforms.android import cli

        pyproject = Path("pyproject.toml")
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8"
        )
        with pytest.raises(ToolchainError) as info:
            cli.android_build(Path.cwd())
        assert info.value.code == diagnostics.LOCK_DRIFT
        assert info.value.exit_code == exit_codes.LOCK_DRIFT

    def test_android_missing(self, tmp_path):
        from tests.platforms.android import test_cli as android_tests

        (tmp_path / "pyproject.toml").write_text(
            android_tests.PYPROJECT, encoding="utf-8"
        )
        from kivyforge.platforms.android import cli

        with pytest.raises(ToolchainError) as info:
            cli.android_build(tmp_path)
        assert info.value.code == diagnostics.LOCK_MISSING


class TestHostIncapable:
    @pytest.mark.parametrize(
        ("backend", "gate"),
        [
            ("windows", "_require_windows_host"),
            ("linux", "_require_linux_host"),
            ("macos", "_require_macos_host"),
            ("ios", "_require_macos_host"),
        ],
    )
    def test_gate(self, backend, gate, monkeypatch):
        import importlib

        from kivyforge.platforms import HostCapabilityError, get_platform

        cli = importlib.import_module(f"kivyforge.platforms.{backend}.cli")
        # The suite neutralizes the iOS gate (tests/conftest.py); use the real one.
        require = _REAL_IOS_GATE if backend == "ios" else getattr(cli, gate)

        def incapable(**kw):
            raise HostCapabilityError("wrong host")

        monkeypatch.setattr(get_platform(backend), "check_host_capability", incapable)
        with pytest.raises(ToolchainError) as info:
            require()
        assert info.value.code == diagnostics.HOST_INCAPABLE
        assert info.value.exit_code == exit_codes.ENVIRONMENT_ERROR
