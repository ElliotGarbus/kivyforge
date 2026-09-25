"""``build --json`` / ``package --json``: the envelope, per backend.

Asserts fields rather than a serialised golden blob (the envelope carries
``__version__``), in the style of ``test_lock_json.py``. Every test parses stdout
with a single ``json.loads``, which is itself the first plumbing assertion: one
stray human line, or a second ``emit``, and it fails.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

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
