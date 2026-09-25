"""Human-mode output of ``build`` and ``package``, pinned per backend.

These go through the real Click verbs with each toolchain collaborator stubbed
(fixtures in ``conftest.py``), and pin two things separately, because the
proposal changes one and not the other (build-package-output-proposal §5):

* **The interleaved text and its order** (``result.output``) -- what a person
  at a terminal reads. Unchanged, except where a comment says "Deliberate".
* **Which lines are on stdout** (``result.stdout``) -- only the product lines
  and the distribution advice. Everything else is progress and moved to stderr
  (§3.1).
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


def _assert_streams(result, *, merged: str, stdout: str) -> None:
    assert result.output == merged
    assert result.stdout == stdout


class TestWindows:
    def test_build(self, windows):
        result = _invoke(build, ["-p", "windows"])
        text = f"Built {_p('build', 'windows', 'My App')}\n"
        _assert_streams(result, merged=text, stdout=text)

    def test_package_unsigned(self, windows, monkeypatch):
        monkeypatch.setattr(
            windows, "select_signer", lambda s: SimpleNamespace(configured=False)
        )
        result = _invoke(package, ["-p", "windows"])
        text = (
            f"Packaged {_p('dist', 'windows', 'My App-1.2.3-amd64')} (onedir folder, "
            "unsigned (configure [tool.kivy.windows.signing] to sign)).\n"
            "  Run it by double-clicking My App.exe, or zip the folder to "
            "distribute. An installer is an external step.\n"
        )
        _assert_streams(result, merged=text, stdout=text)

    def test_package_signed(self, windows, monkeypatch):
        signer = SimpleNamespace(configured=True, sign=lambda paths: None)
        monkeypatch.setattr(windows, "select_signer", lambda s: signer)
        result = _invoke(package, ["-p", "windows"])
        text = (
            f"Packaged {_p('dist', 'windows', 'My App-1.2.3-amd64')} (onedir folder, "
            "signed + timestamped).\n"
            "  Run it by double-clicking My App.exe, or zip the folder to "
            "distribute. An installer is an external step.\n"
        )
        _assert_streams(result, merged=text, stdout=text)


class TestLinux:
    def test_build(self, linux):
        result = _invoke(build, ["-p", "linux"])
        text = f"Built {_p('build', 'linux', 'Demo App.AppDir')}\n"
        _assert_streams(result, merged=text, stdout=text)

    def test_package_folder(self, linux):
        result = _invoke(package, ["-p", "linux", "-f", "folder"])
        text = (
            f"Packaged {_p('build', 'linux', 'Demo App.AppDir')} (AppDir folder).\n"
            "  Run it with ./AppRun, or `kivyforge package -f appimage` for a "
            "single-file distributable.\n"
        )
        _assert_streams(result, merged=text, stdout=text)

    def test_package_appimage(self, linux):
        result = _invoke(package, ["-p", "linux"])
        product = (
            f"Packaged {_p('dist', 'linux', 'demo-app-1.2.3-x86_64.AppImage')}.\n"
            "  Distribute the .AppImage directly (chmod +x, then run). The host "
            "needs glibc >= the effective floor, libGL/libEGL, and an X11/Wayland "
            "session.\n"
            "  No libfuse2 package is required (static-FUSE runtime embedded). If "
            "the host lacks kernel FUSE (/dev/fuse) — e.g. some containers/CI — "
            "run it with --appimage-extract-and-run (or APPIMAGE_EXTRACT_AND_RUN=1)."
            "\n"
        )
        _assert_streams(
            result,
            merged="Packaging demo-app-1.2.3-x86_64.AppImage with appimagetool "
            "1.9.0 ...\n" + product,
            stdout=product,
        )


class TestMacos:
    def test_build(self, macos):
        result = _invoke(build, ["-p", "macos"])
        text = f"Built {_p('build', 'macos', 'Demo App.app')}\n"
        _assert_streams(result, merged=text, stdout=text)

    def test_package_adhoc(self, macos):
        result = _invoke(package, ["-p", "macos"])
        app = _p("build", "macos", "Demo App.app")
        text = (
            f"Built {app}\n"
            f"Packaged {app} (ad-hoc signed).\n"
            "  Distribute the .app directly, or wrap it in a .dmg with an external "
            "tool (see docs). For Gatekeeper-trusted distribution, configure "
            "[tool.kivy.macos.signing].\n"
        )
        _assert_streams(result, merged=text, stdout=text)

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
        packaged = (
            f"Packaged {app} (Developer ID notarized + stapled).\n"
            "  Distribute the .app directly, or wrap it in a .dmg with an external "
            "tool (see docs).\n"
        )
        _assert_streams(
            result,
            merged=f"Built {app}\n"
            "Developer ID signing with 'Developer ID Application: Acme' ...\n"
            "  signed 12 Mach-O binaries + the bundle\n" + packaged,
            stdout=f"Built {app}\n" + packaged,
        )


_IOS_DEVICE_TAGS = "ios_13_0_arm64_iphoneos"
_IOS_SIM_TAGS = "ios_13_0_arm64_iphonesimulator"
_IOS_PRODUCTS = _p("demo-ios", "build", "DerivedData", "Build", "Products")


def _ios_prepare(tags: str) -> str:
    return (
        "[stage] app sources\n"
        f"Collecting artifacts for {tags} ...\n"
        "[collect] Python.xcframework\n"
        "Generated demo-ios\n"
    )


class TestIos:
    def test_build_project_only(self, ios):
        result = _invoke(build, ["-p", "ios"])
        ready = (
            "Project ready. Open it with `kivyforge open` or build with "
            "`kivyforge build --simulator`.\n"
        )
        _assert_streams(
            result,
            merged=_ios_prepare(f"{_IOS_DEVICE_TAGS}, {_IOS_SIM_TAGS}") + ready,
            stdout="Generated demo-ios\n" + ready,
        )

    def test_build_simulator(self, ios):
        result = _invoke(build, ["-p", "ios", "--simulator"])
        # Deliberate (proposal §5 step 1): the .app is announced, from the pinned
        # project-local DerivedData, where before there was no product line.
        built = f"Built {_IOS_PRODUCTS}{os.sep}Debug-iphonesimulator{os.sep}demo.app\n"
        _assert_streams(
            result,
            merged=_ios_prepare(_IOS_SIM_TAGS)
            + "xcodebuild build (simulator) ...\n"
            + built,
            stdout="Generated demo-ios\n" + built,
        )

    def test_build_device(self, ios):
        result = _invoke(build, ["-p", "ios", "--device"])
        built = f"Built {_IOS_PRODUCTS}{os.sep}Debug-iphoneos{os.sep}demo.app\n"
        _assert_streams(
            result,
            merged=_ios_prepare(_IOS_DEVICE_TAGS)
            + "xcodebuild build (device) ...\n"
            + built,
            stdout="Generated demo-ios\n" + built,
        )

    def test_build_release(self, ios):
        result = _invoke(build, ["-p", "ios", "--release"])
        exported = f"Exported {_p('demo-ios', 'build', 'demo.ipa')}\n"
        _assert_streams(
            result,
            merged=_ios_prepare(_IOS_DEVICE_TAGS)
            + "xcodebuild archive ...\n"
            + "xcodebuild -exportArchive ...\n"
            + exported,
            stdout="Generated demo-ios\n" + exported,
        )

    def test_package(self, ios):
        result = _invoke(package, ["-p", "ios"])
        exported = f"Exported {_p('demo-ios', 'build', 'demo.ipa')}\n"
        _assert_streams(
            result,
            merged=_ios_prepare(_IOS_DEVICE_TAGS)
            + "xcodebuild archive ...\n"
            + "xcodebuild -exportArchive ...\n"
            + exported,
            stdout="Generated demo-ios\n" + exported,
        )


_ANDROID_NO_BYTECOMPILE = (
    "[stage] not byte-compiling: no final CPython 3.14 found (this project ships "
    "3.14.6).\n"
    "  Pre-releases do not count: CPython only freezes the .pyc magic number at "
    "the first release candidate, so a 3.14 alpha writes bytecode 3.14.6 refuses "
    "to import.\n"
    "  Fix: install a final CPython 3.14 — kivyforge finds it automatically — or "
    "set byte_compile = false in [tool.kivy.android.build_settings].\n"
)

# Deliberate (proposal §5 step 1): the project gets a product line, so a plain
# `build` still has something on stdout.
_ANDROID_GENERATED = "Generated demoapp-android\n"


def _android_generate(*, byte_compile_note: bool) -> str:
    return (
        "[collect] python.org runtime 3.14.6 (arm64_v8a)\n"
        "[stage] installing 1 wheels for arm64_v8a\n"
        "[stage] jniLibs/arm64-v8a: 0 extensions flattened\n"
        + (_ANDROID_NO_BYTECOMPILE if byte_compile_note else "")
        + "[stage] asset bundle assembled (stamp deadbeef)\n"
        "[generate] demoapp-android/ regenerated\n" + _ANDROID_GENERATED
    )


# Deliberate (proposal §5 step 1): relative, like the other four backends, rather
# than the absolute path Android used to print.
_ANDROID_OUTPUTS = Path("demoapp-android", "app", "build", "outputs")


class TestAndroid:
    def test_build(self, android):
        result = _invoke(build, ["-p", "android"])
        _assert_streams(
            result,
            merged=_android_generate(byte_compile_note=True),
            stdout=_ANDROID_GENERATED,
        )

    def test_build_debug(self, android):
        result = _invoke(build, ["-p", "android", "--debug"])
        built = f"Built {_ANDROID_OUTPUTS / 'apk' / 'debug' / 'app-debug.apk'}\n"
        _assert_streams(
            result,
            merged=_android_generate(byte_compile_note=False)
            + "[gradle] assembleDebug\n"
            + built,
            stdout=_ANDROID_GENERATED + built,
        )

    def test_package(self, android):
        from kivyforge.platforms.android.policy import LINT_CHECKS

        result = _invoke(package, ["-p", "android"])
        packaged = (
            f"Packaged {_ANDROID_OUTPUTS / 'apk' / 'release' / 'app-release.apk'}\n"
        )
        _assert_streams(
            result,
            merged=_android_generate(byte_compile_note=True)
            + "[policy] INFO: org.example.Receiver is exported\n"
            + f"[gradle] lintRelease ({len(LINT_CHECKS)} curated checks)\n"
            + "[policy] merged release manifest\n"
            + "[policy] INFO (merged): org.example.Receiver is exported\n"
            + "[gradle] assembleRelease\n"
            + packaged,
            stdout=_ANDROID_GENERATED + packaged,
        )


def test_expected_separator_matches_host():
    # The expectations above build paths with the host separator, the same way
    # the backends print them; guard the assumption rather than hide it.
    assert _p("a", "b") == f"a{os.sep}b"
