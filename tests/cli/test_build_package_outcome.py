"""What ``build`` and ``package`` record, per backend (proposal §4.1a/§4.1b).

The human output is pinned in ``test_build_package_human_output.py``; these pin
the other half of the same run -- which artifacts each invocation records, and
which notes it attaches -- by driving each backend with recording callbacks.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from kivyforge.build_outcome import (
    Artifact,
    ArtifactKind,
    BuildEvents,
    BuildOutcome,
    OutcomeBuilder,
)
from kivyforge.cli._common import ToolchainError
from kivyforge.report import diagnostics


class Recorder:
    """Callbacks that remember everything instead of printing it."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.progress: list[str] = []
        self.artifacts: list[Artifact] = []
        self.notes: list[tuple[str, str, Mapping[str, str] | None]] = []
        self.events = BuildEvents(
            on_line=self.lines.append,
            on_progress=self.progress.append,
            on_artifact=self.artifacts.append,
            on_note=lambda code, message, context=None: self.notes.append(
                (code, message, context)
            ),
        )

    @property
    def recorded(self) -> list[tuple[str, ArtifactKind]]:
        return [(a.path.as_posix(), a.kind) for a in self.artifacts]

    @property
    def note_codes(self) -> list[str]:
        return [code for code, _message, _context in self.notes]


def _recorded(outcome: BuildOutcome) -> list[tuple[str, ArtifactKind]]:
    return [(a.path.as_posix(), a.kind) for a in outcome.artifacts]


class TestOutcomeTypes:
    def test_as_dict_is_posix_and_uses_the_kind_value(self):
        outcome = BuildOutcome(
            (Artifact(Path("dist", "linux", "a.AppImage"), ArtifactKind.APPIMAGE),),
            notes=("  advice",),
        )
        assert outcome.as_dict() == {
            "artifacts": [{"path": "dist/linux/a.AppImage", "kind": "appimage"}]
        }

    def test_builder_notifies_as_it_stores(self):
        seen: list[Artifact] = []
        builder = OutcomeBuilder(seen.append)
        first = builder.add(Path("proj"), ArtifactKind.PROJECT)
        assert seen == [first]  # before finish(): a later failure still has it
        builder.add(Path("proj", "app.apk"), ArtifactKind.APK)
        assert builder.finish().artifacts == tuple(seen)

    def test_without_artifacts_keeps_output_and_drops_recording(self):
        rec = Recorder()
        inner = rec.events.without_artifacts()
        inner.on_line("Built x")
        OutcomeBuilder(inner.on_artifact).add(Path("x"), ArtifactKind.APP)
        assert rec.lines == ["Built x"]
        assert rec.artifacts == []


class TestWindows:
    def test_build_records_the_onedir_folder(self, windows):
        rec = Recorder()
        outcome = windows.windows_build(
            Path.cwd(),
            arch=None,
            no_verify_lock=True,
            no_cache=False,
            events=rec.events,
        )
        assert (
            rec.recorded
            == _recorded(outcome)
            == [("build/windows/My App", ArtifactKind.FOLDER)]
        )

    def test_package_records_the_dist_copy_and_notes_unsigned(
        self, windows, monkeypatch
    ):
        from types import SimpleNamespace

        monkeypatch.setattr(
            windows, "select_signer", lambda s: SimpleNamespace(configured=False)
        )
        rec = Recorder()
        outcome = windows.windows_package(
            Path.cwd(),
            fmt="folder",
            arch=None,
            no_verify_lock=True,
            no_cache=False,
            events=rec.events,
        )
        assert rec.recorded == [
            ("dist/windows/My App-1.2.3-amd64", ArtifactKind.FOLDER)
        ]
        assert rec.note_codes == [diagnostics.SIGNING_UNCONFIGURED]
        assert outcome.notes and "double-clicking" in outcome.notes[0]
        # The note is machine-only: the unsigned state is already in the prose.
        assert "unsigned" in rec.lines[-1]

    def test_signer_failure_records_nothing(self, windows, monkeypatch):
        from types import SimpleNamespace

        from kivyforge.platforms.windows import WindowsBundleError

        def fail(paths):
            raise WindowsBundleError("no certificate")

        signer = SimpleNamespace(configured=True, sign=fail)
        monkeypatch.setattr(windows, "select_signer", lambda s: signer)
        rec = Recorder()
        with pytest.raises(ToolchainError):
            windows.windows_package(
                Path.cwd(),
                fmt="folder",
                arch=None,
                no_verify_lock=True,
                no_cache=False,
                events=rec.events,
            )
        assert rec.artifacts == []


class TestLinux:
    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("folder", ("build/linux/Demo App.AppDir", ArtifactKind.FOLDER)),
            (
                "appimage",
                ("dist/linux/demo-app-1.2.3-x86_64.AppImage", ArtifactKind.APPIMAGE),
            ),
        ],
    )
    def test_package_kind_follows_the_format(self, linux, fmt, expected):
        rec = Recorder()
        outcome = linux.linux_package(
            Path.cwd(),
            fmt=fmt,
            arch=None,
            no_verify_lock=True,
            no_cache=False,
            events=rec.events,
        )
        assert rec.recorded == _recorded(outcome) == [expected]
        assert rec.notes == []

    def test_appimage_tool_progress_is_not_product(self, linux):
        rec = Recorder()
        linux.linux_package(
            Path.cwd(),
            fmt="appimage",
            arch=None,
            no_verify_lock=True,
            no_cache=False,
            events=rec.events,
        )
        assert any("appimagetool" in line for line in rec.progress)
        assert not any("appimagetool" in line for line in rec.lines)


class TestMacos:
    def test_adhoc_package_records_once_despite_the_inner_build(self, macos):
        rec = Recorder()
        outcome = macos.macos_package(
            Path.cwd(),
            arch=None,
            no_verify_lock=True,
            no_cache=False,
            events=rec.events,
        )
        # The inner build still prints its line...
        assert rec.lines[0].startswith("Built ")
        # ...but only package's product is recorded.
        assert (
            rec.recorded
            == _recorded(outcome)
            == [("build/macos/Demo App.app", ArtifactKind.APP)]
        )
        assert rec.note_codes == [diagnostics.SIGNING_UNCONFIGURED]

    def test_developer_id_package_records_the_signed_app_only(self, macos):
        rec = Recorder()
        macos.macos_package(
            Path.cwd(),
            arch=None,
            no_verify_lock=True,
            no_cache=False,
            signing_identity="Developer ID Application: Acme",
            events=rec.events,
        )
        assert rec.recorded == [("build/macos/Demo App.app", ArtifactKind.APP)]
        assert rec.notes == []
        assert any("Developer ID signing" in line for line in rec.progress)


class TestIos:
    def _build(self, ios, target, rec):
        return ios.ios_build(
            Path.cwd(),
            target=target,
            arch=None,
            no_verify_lock=True,
            no_cache=False,
            team_id=None,
            signing_identity=None,
            export_method="app-store",
            events=rec.events,
        )

    def test_bare_build_records_the_project(self, ios):
        rec = Recorder()
        outcome = self._build(ios, None, rec)
        assert _recorded(outcome) == [("demo-ios", ArtifactKind.PROJECT)]

    @pytest.mark.parametrize(
        ("target", "product"),
        [
            (
                "simulator",
                (
                    "demo-ios/build/DerivedData/Build/Products/"
                    "Debug-iphonesimulator/demo.app",
                    ArtifactKind.APP,
                ),
            ),
            ("release", ("demo-ios/build/demo.ipa", ArtifactKind.IPA)),
        ],
    )
    def test_targeted_build_records_project_then_product(self, ios, target, product):
        rec = Recorder()
        outcome = self._build(ios, target, rec)
        assert (
            rec.recorded
            == _recorded(outcome)
            == [
                ("demo-ios", ArtifactKind.PROJECT),
                product,
            ]
        )

    def test_failed_build_still_reports_the_fresh_project(self, ios, monkeypatch):
        from kivyforge.platforms.ios.xcode import CommandError

        def fail(argv, **kw):
            raise CommandError(argv, 65, "** BUILD FAILED **")

        monkeypatch.setattr(ios, "run_command", fail)
        rec = Recorder()
        with pytest.raises(ToolchainError):
            self._build(ios, "simulator", rec)
        assert rec.recorded == [("demo-ios", ArtifactKind.PROJECT)]

    def test_missing_product_is_an_error_not_an_announcement(self, ios, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            ios, "run_command", lambda argv, **kw: SimpleNamespace(returncode=0)
        )
        rec = Recorder()
        with pytest.raises(ToolchainError, match="no product"):
            self._build(ios, "simulator", rec)
        assert not any(line.startswith("Built ") for line in rec.lines)

    def test_package_records_only_the_ipa(self, ios):
        rec = Recorder()
        outcome = ios.ios_package(
            Path.cwd(),
            team_id=None,
            signing_identity=None,
            export_method="app-store",
            no_verify_lock=True,
            no_cache=False,
            events=rec.events,
        )
        # The project line printed, but the project is package's intermediate.
        assert "Generated demo-ios" in rec.lines
        assert (
            rec.recorded
            == _recorded(outcome)
            == [("demo-ios/build/demo.ipa", ArtifactKind.IPA)]
        )

    def test_failed_package_records_nothing(self, ios, monkeypatch):
        from kivyforge.platforms.ios.xcode import CommandError

        def fail(argv, **kw):
            raise CommandError(argv, 65, "** ARCHIVE FAILED **")

        monkeypatch.setattr(ios, "run_command", fail)
        rec = Recorder()
        with pytest.raises(ToolchainError):
            ios.ios_package(
                Path.cwd(),
                team_id=None,
                signing_identity=None,
                export_method="app-store",
                no_verify_lock=True,
                no_cache=False,
                events=rec.events,
            )
        assert rec.artifacts == []

    def test_ungranted_entitlements_are_noted(self, ios, monkeypatch):
        monkeypatch.setattr(
            ios, "preflight_entitlements", lambda *a: ["com.apple.developer.healthkit"]
        )
        rec = Recorder()
        self._build(ios, "device", rec)
        assert rec.note_codes == [diagnostics.ENTITLEMENTS_UNGRANTED]
        # The human warning goes where it always went (stderr), not through
        # on_line or on_progress.
        assert not any("entitlements" in line for line in rec.lines + rec.progress)


class TestAndroid:
    def test_package_records_only_the_release_artifact(self, android):
        from kivyforge.platforms.android import cli

        rec = Recorder()
        outcome = cli.android_package(Path.cwd(), events=rec.events)
        assert "Generated demoapp-android" in rec.lines
        assert (
            rec.recorded
            == _recorded(outcome)
            == [
                (
                    "demoapp-android/app/build/outputs/apk/release/app-release.apk",
                    ArtifactKind.APK,
                )
            ]
        )

    def test_package_notes_policy_and_byte_compile(self, android):
        from kivyforge.platforms.android import cli

        rec = Recorder()
        cli.android_package(Path.cwd(), events=rec.events)
        assert rec.note_codes == [
            diagnostics.BYTECOMPILE_NO_INTERP,
            diagnostics.MANIFEST_POLICY,
            diagnostics.MANIFEST_POLICY,
        ]
        assert [context for *_rest, context in rec.notes[1:]] == [
            {"manifest": "generated"},
            {"manifest": "merged"},
        ]

    def test_failed_package_records_nothing(self, android, monkeypatch):
        from kivyforge.platforms.android import cli
        from kivyforge.platforms.android.gradlew import GradleError

        def fail(dest, tasks, **kw):
            raise GradleError("assembleRelease failed")

        monkeypatch.setattr(cli, "run_gradle", fail)
        rec = Recorder()
        with pytest.raises(ToolchainError):
            cli.android_package(Path.cwd(), events=rec.events)
        assert rec.artifacts == []

    def test_failed_debug_build_still_reports_the_fresh_project(
        self, android, monkeypatch
    ):
        from kivyforge.platforms.android import cli
        from kivyforge.platforms.android.gradlew import GradleError

        def fail(dest, tasks, **kw):
            raise GradleError("assembleDebug failed")

        monkeypatch.setattr(cli, "run_gradle", fail)
        rec = Recorder()
        with pytest.raises(ToolchainError):
            cli.android_build(Path.cwd(), debug=True, events=rec.events)
        assert rec.recorded == [("demoapp-android", ArtifactKind.PROJECT)]


def test_ios_byte_compile_notes_carry_their_payload(tmp_path, monkeypatch):
    from kivyforge.artifacts import collect
    from kivyforge.config.model import DesktopBuildSettings

    monkeypatch.setattr(collect, "select_compiler", lambda **kw: None)
    rec = Recorder()
    collect._compile_pip_deps(
        tmp_path,
        python_version="3.14.0",
        release=True,
        build_settings=DesktopBuildSettings(),
        echo=rec.events.on_progress,
        note=rec.events.note,
    )
    assert rec.notes == [
        (
            diagnostics.BYTECOMPILE_NO_INTERP,
            "not byte-compiling pip-deps: no final CPython 3.14 found (this "
            "project ships 3.14.0).",
            {"payload": "pip-deps"},
        )
    ]
    assert rec.progress and rec.progress[0].startswith("[stage] not byte-compiling")
