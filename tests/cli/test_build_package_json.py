"""``build --json`` / ``package --json``: the envelope, per backend.

Asserts fields rather than a serialised golden blob (the envelope carries
``__version__``), in the style of ``test_lock_json.py``. Every test parses stdout
with a single ``json.loads``, which is itself the first plumbing assertion: one
stray human line, or a second ``emit``, and it fails.
"""

from __future__ import annotations

import errno
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from kivyforge.cli.build import build
from kivyforge.cli.package import package
from kivyforge.report import diagnostics, exit_codes


def _run(command, args):
    result = CliRunner().invoke(command, [*args, "--json"])
    envelope = json.loads(result.stdout)  # exactly one document, nothing else
    return result, envelope


def _artifacts(envelope) -> list[tuple[str, str]]:
    return [(a["path"], a["kind"]) for a in envelope["data"]["artifacts"]]


def _codes(envelope) -> list[str]:
    return [d["code"] for d in envelope["diagnostics"]]


class TestSuccess:
    def test_windows_build(self, windows):
        result, env = _run(build, ["-p", "windows"])
        assert result.exit_code == 0
        assert env["command"] == "build"
        assert env["platform"] == "windows"
        assert env["ok"] is True
        assert _artifacts(env) == [("build/windows/My App", "folder")]
        assert env["diagnostics"] == []

    def test_linux_appimage_progress_stays_on_stderr(self, linux):
        result, env = _run(package, ["-p", "linux"])
        assert _artifacts(env) == [
            ("dist/linux/demo-app-1.2.3-x86_64.AppImage", "appimage")
        ]
        assert "appimagetool" in result.stderr
        # The distribution advice is human-only, by construction.
        assert "Distribute" not in result.stdout

    def test_macos_developer_id_package(self, macos):
        result, env = _run(
            package, ["-p", "macos", "--signing-identity", "Developer ID Application"]
        )
        assert _artifacts(env) == [("build/macos/Demo App.app", "app")]
        # The inner build's line is human output: gone from stdout under --json.
        assert "Built" not in result.stdout

    def test_ios_release_build_reports_project_and_ipa(self, ios):
        _, env = _run(build, ["-p", "ios", "--release"])
        assert _artifacts(env) == [
            ("demo-ios", "project"),
            ("demo-ios/build/demo.ipa", "ipa"),
        ]

    def test_ios_package_reports_only_the_ipa(self, ios):
        _, env = _run(package, ["-p", "ios"])
        assert _artifacts(env) == [("demo-ios/build/demo.ipa", "ipa")]

    def test_android_debug_build_reports_project_and_apk(self, android):
        result, env = _run(build, ["-p", "android", "--debug"])
        assert _artifacts(env) == [
            ("demoapp-android", "project"),
            ("demoapp-android/app/build/outputs/apk/debug/app-debug.apk", "apk"),
        ]
        assert "[gradle] assembleDebug" in result.stderr

    def test_android_bare_build_reports_only_the_project(self, android):
        result, env = _run(build, ["-p", "android"])
        assert result.exit_code == 0
        assert _artifacts(env) == [("demoapp-android", "project")]
        # The "Gradle did not run" hint (#106) is human output: an agent reads
        # the missing apk from `artifacts`, not from prose on stdout.
        assert "Gradle did not run" not in result.stdout


class TestSuccessWithNotes:
    """ok with diagnostics and exit 0: a warning is not a failure."""

    def test_unsigned_windows_package(self, windows, monkeypatch):
        monkeypatch.setattr(
            windows, "select_signer", lambda s: SimpleNamespace(configured=False)
        )
        result, env = _run(package, ["-p", "windows"])
        assert result.exit_code == 0
        assert env["ok"] is True
        (note,) = env["diagnostics"]
        assert note["code"] == diagnostics.SIGNING_UNCONFIGURED
        assert note["severity"] == diagnostics.WARNING

    def test_android_package_notes(self, android):
        result, env = _run(package, ["-p", "android"])
        assert result.exit_code == 0
        assert env["ok"] is True
        assert _codes(env) == [
            diagnostics.BYTECOMPILE_NO_INTERP,
            diagnostics.MANIFEST_POLICY,
            diagnostics.MANIFEST_POLICY,
        ]
        assert [d["severity"] for d in env["diagnostics"]] == [
            diagnostics.WARNING,
            diagnostics.INFO,
            diagnostics.INFO,
        ]
        assert env["diagnostics"][2]["context"] == {"manifest": "merged"}


class TestFailure:
    def test_before_target_resolution_still_has_the_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no pyproject.toml
        result, env = _run(build, [])
        assert result.exit_code == exit_codes.CONFIG_ERROR
        assert env["ok"] is False
        assert env["platform"] is None
        assert env["data"] == {"artifacts": []}

    def test_failed_ios_build_keeps_the_log_out_of_the_envelope(self, ios, monkeypatch):
        from kivyforge.platforms.ios.xcode import CommandError

        transcript = "\n".join(f"CompileC step {i}" for i in range(500))

        def fail(argv, **kw):
            raise CommandError(argv, 65, transcript + "\n** BUILD FAILED **")

        monkeypatch.setattr(ios, "run_command", fail)
        result, env = _run(build, ["-p", "ios", "--simulator"])
        assert result.exit_code != 0
        assert env["ok"] is False
        (diagnostic,) = env["diagnostics"]
        assert diagnostic["message"].startswith("xcodebuild build failed (exit 65)")
        assert "CompileC" not in diagnostic["message"]
        assert "CompileC step 499" in result.stderr
        # The project was generated before xcodebuild failed: a product of build.
        assert _artifacts(env) == [("demo-ios", "project")]

    def test_failed_ios_package_reports_no_artifacts(self, ios, monkeypatch):
        from kivyforge.platforms.ios.xcode import CommandError

        def fail(argv, **kw):
            raise CommandError(argv, 65, "** ARCHIVE FAILED **")

        monkeypatch.setattr(ios, "run_command", fail)
        _, env = _run(package, ["-p", "ios"])
        assert env["ok"] is False
        assert _artifacts(env) == []
        assert env["diagnostics"][0]["message"].startswith("xcodebuild archive failed")

    def test_failed_android_package_reports_no_artifacts(self, android, monkeypatch):
        from kivyforge.platforms.android import cli
        from kivyforge.platforms.android.gradlew import GradleError

        def fail(dest, tasks, **kw):
            raise GradleError("Gradle failed (exit 1) running: assembleRelease")

        monkeypatch.setattr(cli, "run_gradle", fail)
        _, env = _run(package, ["-p", "android"])
        assert env["ok"] is False
        assert _artifacts(env) == []

    def test_android_download_failure_is_an_envelope(self, android, monkeypatch):
        """Not a traceback with empty stdout: a 503 from the wheel host is a
        failure the caller is told about like any other."""
        from kivyforge.artifacts.download import DownloadError
        from kivyforge.platforms.android import cli

        url = "https://example.invalid/Kivy-2.3.1-cp314-cp314-android_24_x86_64.whl"

        def unavailable(**kw):
            raise DownloadError(
                f"failed to download {url}: HTTP Error 503: Service Unavailable"
            )

        monkeypatch.setattr(cli, "fetch_artifact", unavailable)
        result, env = _run(build, ["-p", "android", "--debug"])
        assert result.exit_code == exit_codes.CONFIG_ERROR
        assert env["ok"] is False
        (diagnostic,) = env["diagnostics"]
        assert diagnostic["code"] == diagnostics.UNSPECIFIED
        assert "HTTP Error 503" in diagnostic["message"]
        assert url in diagnostic["message"]
        assert "Traceback" not in result.stderr
        assert _artifacts(env) == []

    def test_android_app_module_conflict_is_an_envelope(self, android):
        (android / "src" / "android.py").write_text("# mine\n", encoding="utf-8")
        result, env = _run(build, ["-p", "android", "--debug"])
        assert result.exit_code == exit_codes.CONFIG_ERROR
        (diagnostic,) = env["diagnostics"]
        assert diagnostic["code"] == diagnostics.ANDROID_APP_CONFLICT
        assert diagnostic["context"] == {"path": "src/android.py"}
        assert diagnostic["remediation"].startswith("rename or remove it")
        assert _artifacts(env) == []

    def test_android_hash_mismatch_is_an_envelope(self, android, monkeypatch):
        from kivyforge.artifacts.verify import HashMismatch
        from kivyforge.platforms.android import cli

        def tampered(**kw):
            raise HashMismatch(
                name=kw["name"], source="x", expected="a" * 64, actual="b" * 64
            )

        monkeypatch.setattr(cli, "fetch_artifact", tampered)
        result, env = _run(package, ["-p", "android"])
        assert env["ok"] is False
        (diagnostic,) = env["diagnostics"]
        assert diagnostic["message"].startswith("SHA-256 mismatch for ")
        assert "Traceback" not in result.stderr

    def test_ios_download_failure_is_an_envelope(self, ios, monkeypatch):
        from kivyforge.artifacts.download import DownloadError

        def unavailable(*a, **kw):
            raise DownloadError("failed to download https://x: HTTP Error 503")

        monkeypatch.setattr(ios, "collect_artifacts", unavailable)
        result, env = _run(build, ["-p", "ios"])
        assert result.exit_code == exit_codes.CONFIG_ERROR
        assert env["ok"] is False
        (diagnostic,) = env["diagnostics"]
        assert "HTTP Error 503" in diagnostic["message"]
        assert "Traceback" not in result.stderr

    def test_android_build_on_a_jre_is_a_missing_tool(self, android, monkeypatch):
        from kivyforge.platforms.android import cli, doctor, gradlew
        from tests.platforms.android.test_doctor import FakeProbe

        jre = FakeProbe(which={"java": "/usr/bin/java"}, javac=False)
        monkeypatch.setattr(doctor, "RealAndroidProbe", lambda: jre)
        monkeypatch.setattr(
            cli, "run_gradle", lambda dest, tasks, **kw: gradlew._require_jdk()
        )
        result, env = _run(build, ["-p", "android", "--debug"])
        assert result.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert env["ok"] is False
        (diagnostic,) = env["diagnostics"]
        assert diagnostic["code"] == diagnostics.TOOLCHAIN_MISSING
        assert diagnostic["context"] == {"tool": "javac"}
        assert "jdk-headless" in diagnostic["remediation"]
        # The project was generated before Gradle was refused: still this run's.
        assert _artifacts(env) == [("demoapp-android", "project")]

    def test_failed_windows_signing_does_not_name_the_old_package(
        self, windows, monkeypatch, desktop_project
    ):
        from kivyforge.platforms.windows import WindowsBundleError

        previous = desktop_project / "dist" / "windows" / "My App-1.2.3-amd64"
        previous.mkdir(parents=True)
        (previous / "OLD.txt").write_text("previous package")

        def fail(paths):
            raise WindowsBundleError("no signing certificate found")

        signer = SimpleNamespace(configured=True, sign=fail)
        monkeypatch.setattr(windows, "select_signer", lambda s: signer)
        _, env = _run(package, ["-p", "windows"])
        assert env["ok"] is False
        assert (previous / "OLD.txt").exists()  # rolled back...
        assert _artifacts(env) == []  # ...and not claimed as this run's product

    @pytest.mark.parametrize("failure", ["immediate", "per_file"])
    def test_failed_windows_dist_copy_is_an_envelope(
        self, windows, monkeypatch, desktop_project, failure
    ):
        # copytree fails two ways: a bare OSError from its first makedirs, or
        # one shutil.Error at the end listing every file that failed, which is
        # what a too-long path with long paths off produces. Neither is a
        # ToolchainError, so both used to escape reporting() as a traceback.
        previous = desktop_project / "dist" / "windows" / "My App-1.2.3-amd64"
        previous.mkdir(parents=True)
        (previous / "OLD.txt").write_text("previous package")
        real_copytree = shutil.copytree

        def immediate(src, dst, **kw):
            raise PermissionError(errno.EACCES, "Permission denied", str(dst))

        def per_file(src, dst, **kw):
            def refuse(s, d):
                raise OSError(errno.ENOENT, "No such file or directory", d)

            return real_copytree(src, dst, copy_function=refuse, **kw)

        copy = {"immediate": immediate, "per_file": per_file}[failure]
        monkeypatch.setattr(windows.shutil, "copytree", copy)
        result, env = _run(package, ["-p", "windows"])
        assert result.exit_code == exit_codes.CONFIG_ERROR
        assert env["ok"] is False
        (diagnostic,) = env["diagnostics"]
        assert diagnostic["code"] == diagnostics.UNSPECIFIED
        assert diagnostic["message"].startswith("could not copy the bundle into ")
        assert "Traceback" not in result.stderr
        assert _artifacts(env) == []
        # The previous package is back, and no reserved copy is left beside it.
        assert (previous / "OLD.txt").read_text() == "previous package"
        assert list(previous.parent.iterdir()) == [previous]

    def test_too_long_windows_paths_name_the_first_and_count_the_rest(
        self, windows, monkeypatch, desktop_project
    ):
        # A bundle that fits in build/ can overflow MAX_PATH under the longer
        # dist/ name, and then every deep file fails: name one, count the rest.
        dest = desktop_project / "dist" / "windows" / "My App-1.2.3-amd64"
        deep = str(dest / ("d" * 300))

        def entry(i):  # shaped as copytree records one: (src, dst, str(why))
            dst = f"{deep}{i}.pyc"
            return (f"src{i}", dst, str(FileNotFoundError(errno.ENOENT, "gone", dst)))

        failures = [entry(i) for i in range(2000)]

        def too_long(src, dst, **kw):
            raise shutil.Error(failures)

        monkeypatch.setattr(windows.shutil, "copytree", too_long)
        _, env = _run(package, ["-p", "windows"])
        (diagnostic,) = env["diagnostics"]
        message = diagnostic["message"]
        assert "2000 paths failed" in message
        assert message.count(f"{deep}0.pyc") == 1  # named once, not twice...
        assert f"{deep}1.pyc" not in message  # ...and not the whole list
        assert "long paths off" in message
        assert diagnostic["remediation"].startswith("move the project to a shorter")

    @pytest.mark.parametrize("blocker", ["dist_is_a_file", "output_is_a_folder"])
    def test_failed_linux_dist_write_is_an_envelope(
        self, linux, monkeypatch, desktop_project, blocker
    ):
        # The real build_appimage, minus the download and the tool: kivyforge's
        # own writes around appimagetool are what is under test.
        from kivyforge.platforms.linux import appimage

        def appimagetool(cmd, **kw):
            Path(cmd[-1]).write_bytes(b"ELF")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(linux, "build_appimage", appimage.build_appimage)
        monkeypatch.setattr(appimage, "_host_appimagetool_arch", lambda: "x86_64")
        monkeypatch.setattr(appimage, "_acquire", lambda *a: desktop_project / "t")
        monkeypatch.setattr(appimage, "_executable_copy", lambda tool, cache: tool)
        monkeypatch.setattr(appimage.subprocess, "run", appimagetool)
        dist = desktop_project / "dist" / "linux"
        if blocker == "dist_is_a_file":
            dist.parent.mkdir()
            dist.write_text("not a folder")
        else:
            (dist / "demo-app-1.2.3-x86_64.AppImage").mkdir(parents=True)

        result, env = _run(package, ["-p", "linux"])
        assert result.exit_code == exit_codes.CONFIG_ERROR
        assert env["ok"] is False
        (diagnostic,) = env["diagnostics"]
        assert diagnostic["code"] == diagnostics.UNSPECIFIED
        assert "Traceback" not in result.stderr
        assert _artifacts(env) == []
        if dist.is_dir():  # no half-written temp file left behind
            assert [p.name for p in dist.iterdir()] == [
                "demo-app-1.2.3-x86_64.AppImage"
            ]
