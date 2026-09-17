"""Human-mode output of ``build`` and ``package``, pinned per backend.

These pin text, order and stream for every backend through the real Click verbs,
with each toolchain collaborator stubbed (fixtures in ``conftest.py``). They exist
so that routing output through structured callbacks
(build-package-output-proposal §5) is provably a no-op for a human reader, except
where the proposal names a deliberate change -- each marked "Deliberate" below.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from kivyforge.cli.build import build
from kivyforge.cli.package import package


def _p(*parts: str) -> str:
    return str(Path(*parts))


def _invoke(command, args):
    result = CliRunner().invoke(command, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result


class TestWindows:
    def test_build(self, windows):
        result = _invoke(build, ["-p", "windows"])
        assert result.stdout == f"Built {_p('build', 'windows', 'My App')}\n"
        assert result.stderr == ""

    def test_package_unsigned(self, windows, monkeypatch):
        monkeypatch.setattr(
            windows, "select_signer", lambda s: SimpleNamespace(configured=False)
        )
        result = _invoke(package, ["-p", "windows"])
        assert result.stdout == (
            f"Packaged {_p('dist', 'windows', 'My App-1.2.3-amd64')} (onedir folder, "
            "unsigned (configure [tool.kivy.windows.signing] to sign)).\n"
            "  Run it by double-clicking My App.exe, or zip the folder to "
            "distribute. An installer is an external step.\n"
        )
        assert result.stderr == ""

    def test_package_signed(self, windows, monkeypatch):
        signer = SimpleNamespace(configured=True, sign=lambda paths: None)
        monkeypatch.setattr(windows, "select_signer", lambda s: signer)
        result = _invoke(package, ["-p", "windows"])
        assert result.stdout == (
            f"Packaged {_p('dist', 'windows', 'My App-1.2.3-amd64')} (onedir folder, "
            "signed + timestamped).\n"
            "  Run it by double-clicking My App.exe, or zip the folder to "
            "distribute. An installer is an external step.\n"
        )
        assert result.stderr == ""


class TestLinux:
    def test_build(self, linux):
        result = _invoke(build, ["-p", "linux"])
        assert result.stdout == f"Built {_p('build', 'linux', 'Demo App.AppDir')}\n"
        assert result.stderr == ""

    def test_package_folder(self, linux):
        result = _invoke(package, ["-p", "linux", "-f", "folder"])
        assert result.stdout == (
            f"Packaged {_p('build', 'linux', 'Demo App.AppDir')} (AppDir folder).\n"
            "  Run it with ./AppRun, or `kivyforge package -f appimage` for a "
            "single-file distributable.\n"
        )
        assert result.stderr == ""

    def test_package_appimage(self, linux):
        result = _invoke(package, ["-p", "linux"])
        assert result.stdout == (
            "Packaging demo-app-1.2.3-x86_64.AppImage with appimagetool 1.9.0 ...\n"
            f"Packaged {_p('dist', 'linux', 'demo-app-1.2.3-x86_64.AppImage')}.\n"
            "  Distribute the .AppImage directly (chmod +x, then run). The host "
            "needs glibc >= the effective floor, libGL/libEGL, and an X11/Wayland "
            "session.\n"
            "  No libfuse2 package is required (static-FUSE runtime embedded). If "
            "the host lacks kernel FUSE (/dev/fuse) — e.g. some containers/CI — "
            "run it with --appimage-extract-and-run (or APPIMAGE_EXTRACT_AND_RUN=1)."
            "\n"
        )
        assert result.stderr == ""


class TestMacos:
    def test_build(self, macos):
        result = _invoke(build, ["-p", "macos"])
        assert result.stdout == f"Built {_p('build', 'macos', 'Demo App.app')}\n"
        assert result.stderr == ""

    def test_package_adhoc(self, macos):
        result = _invoke(package, ["-p", "macos"])
        app = _p("build", "macos", "Demo App.app")
        assert result.stdout == (
            f"Built {app}\n"
            f"Packaged {app} (ad-hoc signed).\n"
            "  Distribute the .app directly, or wrap it in a .dmg with an external "
            "tool (see docs). For Gatekeeper-trusted distribution, configure "
            "[tool.kivy.macos.signing].\n"
        )
        assert result.stderr == ""

    def test_package_developer_id_notarized(self, macos):
        result = _invoke(
            package,
            [
                "-p",
                "macos",
                "--signing-identity",
                "Developer ID Application: Acme",
                "--notary-profile",
                "acme",
            ],
        )
        app = _p("build", "macos", "Demo App.app")
        assert result.stdout == (
            f"Built {app}\n"
            "Developer ID signing with 'Developer ID Application: Acme' ...\n"
            "  signed 12 Mach-O binaries + the bundle\n"
            f"Packaged {app} (Developer ID notarized + stapled).\n"
            "  Distribute the .app directly, or wrap it in a .dmg with an external "
            "tool (see docs).\n"
        )
        assert result.stderr == ""


_IOS_PREPARE = "[stage] app sources\nCollecting artifacts for {tags} ...\n" + (
    "[collect] Python.xcframework\nGenerated demo-ios\n"
)
_IOS_DEVICE_TAGS = "ios_13_0_arm64_iphoneos"
_IOS_SIM_TAGS = "ios_13_0_arm64_iphonesimulator"
_IOS_PRODUCTS = _p("demo-ios", "build", "DerivedData", "Build", "Products")


class TestIos:
    def test_build_project_only(self, ios):
        result = _invoke(build, ["-p", "ios"])
        tags = f"{_IOS_DEVICE_TAGS}, {_IOS_SIM_TAGS}"
        assert result.stdout == _IOS_PREPARE.format(tags=tags) + (
            "Project ready. Open it with `kivyforge open` or build with "
            "`kivyforge build --simulator`.\n"
        )
        assert result.stderr == ""

    def test_build_simulator(self, ios):
        result = _invoke(build, ["-p", "ios", "--simulator"])
        # Deliberate (proposal §5 step 1): the .app is announced, from the pinned
        # project-local DerivedData, where before there was no product line.
        assert result.stdout == _IOS_PREPARE.format(tags=_IOS_SIM_TAGS) + (
            "xcodebuild build (simulator) ...\n"
            f"Built {_IOS_PRODUCTS}{os.sep}Debug-iphonesimulator{os.sep}demo.app\n"
        )
        assert result.stderr == ""

    def test_build_device_warns_on_ungranted_entitlements(self, ios, monkeypatch):
        monkeypatch.setattr(
            ios, "preflight_entitlements", lambda *a: ["com.apple.developer.healthkit"]
        )
        result = _invoke(build, ["-p", "ios", "--device"])
        assert result.stdout == _IOS_PREPARE.format(tags=_IOS_DEVICE_TAGS) + (
            "xcodebuild build (device) ...\n"
            f"Built {_IOS_PRODUCTS}{os.sep}Debug-iphoneos{os.sep}demo.app\n"
        )
        assert result.stderr == (
            "Warning: entitlements not granted by the pinned provisioning profile: "
            "com.apple.developer.healthkit\n"
            "  auto_signing is on, so Xcode may register them at build time.\n"
        )

    def test_build_release(self, ios):
        result = _invoke(build, ["-p", "ios", "--release"])
        assert result.stdout == _IOS_PREPARE.format(tags=_IOS_DEVICE_TAGS) + (
            "xcodebuild archive ...\n"
            "xcodebuild -exportArchive ...\n"
            f"Exported {_p('demo-ios', 'build', 'demo.ipa')}\n"
        )
        assert result.stderr == ""

    def test_package(self, ios):
        result = _invoke(package, ["-p", "ios"])
        assert result.stdout == _IOS_PREPARE.format(tags=_IOS_DEVICE_TAGS) + (
            "xcodebuild archive ...\n"
            "xcodebuild -exportArchive ...\n"
            f"Exported {_p('demo-ios', 'build', 'demo.ipa')}\n"
        )
        assert result.stderr == ""


_ANDROID_NO_BYTECOMPILE = (
    "[stage] not byte-compiling: no final CPython 3.14 found (this project ships "
    "3.14.6).\n"
    "  Pre-releases do not count: CPython only freezes the .pyc magic number at "
    "the first release candidate, so a 3.14 alpha writes bytecode 3.14.6 refuses "
    "to import.\n"
    "  Fix: install a final CPython 3.14 — kivyforge finds it automatically — or "
    "set byte_compile = false in [tool.kivy.android.build_settings].\n"
)


def _android_generate(*, byte_compile_note: bool) -> str:
    return (
        "[collect] python.org runtime 3.14.6 (arm64_v8a)\n"
        "[stage] installing 1 wheels for arm64_v8a\n"
        "[stage] jniLibs/arm64-v8a: 0 extensions flattened\n"
        + (_ANDROID_NO_BYTECOMPILE if byte_compile_note else "")
        + "[stage] asset bundle assembled (stamp deadbeef)\n"
        "[generate] demoapp-android/ regenerated\n"
        # Deliberate (proposal §5 step 1): the project gets a product line, so
        # a plain `build` has one once progress moves to stderr.
        "Generated demoapp-android\n"
    )


# Deliberate (proposal §5 step 1): relative, like the other four backends, rather
# than the absolute path Android used to print.
_ANDROID_OUTPUTS = Path("demoapp-android", "app", "build", "outputs")


class TestAndroid:
    def test_build(self, android):
        result = _invoke(build, ["-p", "android"])
        assert result.stdout == _android_generate(byte_compile_note=True)
        assert result.stderr == ""

    def test_build_debug(self, android):
        result = _invoke(build, ["-p", "android", "--debug"])
        apk = _ANDROID_OUTPUTS / "apk"
        assert result.stdout == _android_generate(byte_compile_note=False) + (
            f"[gradle] assembleDebug\nBuilt {apk / 'debug' / 'app-debug.apk'}\n"
        )
        assert result.stderr == ""

    def test_package(self, android):
        from kivyforge.platforms.android.policy import LINT_CHECKS

        result = _invoke(package, ["-p", "android"])
        apk = _ANDROID_OUTPUTS / "apk"
        assert result.stdout == _android_generate(byte_compile_note=True) + (
            "[policy] INFO: org.example.Receiver is exported\n"
            f"[gradle] lintRelease ({len(LINT_CHECKS)} curated checks)\n"
            "[policy] merged release manifest\n"
            "[policy] INFO (merged): org.example.Receiver is exported\n"
            "[gradle] assembleRelease\n"
            f"Packaged {apk / 'release' / 'app-release.apk'}\n"
        )
        assert result.stderr == ""


def test_expected_separator_matches_host():
    # The expectations above build paths with the host separator, the same way
    # the backends print them; guard the assumption rather than hide it.
    assert _p("a", "b") == f"a{os.sep}b"
