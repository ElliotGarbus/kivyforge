"""Android orchestration: build/package/run/smoke/open + helpers (android/06).

``cli.py`` is the conductor for the whole pipeline; these tests stub every
network/toolchain collaborator (fetch, extract, install, stage, render,
generate, Gradle, adb) so the *orchestration* — step ordering, argument
wiring, error translation to ``AndroidBuildError`` — is exercised hermetically,
while a handful of pure/filesystem helpers (``select_wheel``, ``python_stem``,
the contract checks, ``_write_local_properties``, ``_copy_include_files``) run
for real.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.lock.reader import compute_pyproject_sha256
from kivyforge.platforms.android import AndroidBuildError, cli
from kivyforge.platforms.android import adb as adb_mod
from kivyforge.platforms.android import policy as policy_mod
from kivyforge.platforms.android import signing as signing_mod
from kivyforge.platforms.android import smoke as smoke_mod
from kivyforge.platforms.android.bootstrap.render import RenderedFile
from kivyforge.platforms.android.doctor import RealAndroidProbe
from kivyforge.platforms.android.gradlew import GradleError
from kivyforge.platforms.android.lock import writer as lock_writer
from kivyforge.platforms.android.lock.model import AndroidLockfile, PythonAndroidRuntime
from kivyforge.platforms.android.stage.bundle import BundleError
from kivyforge.platforms.android.stage.runtime import RuntimeStageError
from kivyforge.platforms.android.stage.wheels import WheelStageError

PYPROJECT = """\
[project]
name = "demoapp"
version = "1.0.0"
dependencies = ["kivy==2.3.1", "pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.example.demoapp"
abis = ["arm64_v8a"]

[tool.kivy.android.python]
version = "3.14.6"
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# entry\n", encoding="utf-8")
    return tmp_path


def _write_lock(project_root: Path, *, in_sync: bool = True, pyjnius_version="1.7.0"):
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    packages = (
        LockedPackage(
            name="pyjnius",
            version=pyjnius_version,
            wheels=(
                LockedWheel(
                    name=(
                        f"pyjnius-{pyjnius_version}-cp314-cp314-"
                        "android_24_arm64_v8a.whl"
                    ),
                    url="https://files.example/pyjnius.whl",
                    sha256="a" * 64,
                ),
            ),
        ),
    )
    lock = AndroidLockfile(
        requires_python=">=3.14",
        packages=packages,
        python_android=(
            PythonAndroidRuntime(
                version="3.14.6",
                abi="arm64_v8a",
                url="https://example.org/python-3.14.6-arm64.tar.gz",
                sha256="b" * 64,
                min_api=24,
            ),
        ),
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256=(compute_pyproject_sha256(text) if in_sync else "0" * 64),
        tool_kivy_android_schema_version=1,
        sdl=2,
    )
    (project_root / "pylock.android.toml").write_text(
        lock_writer.dumps(lock), encoding="utf-8"
    )
    return lock


def _gradle_output_for(dest: Path, tasks: list[str]) -> None:
    outputs = dest / "app" / "build" / "outputs"
    mapping = {
        "assembleDebug": outputs / "apk" / "debug" / "app-debug.apk",
        "bundleDebug": outputs / "bundle" / "debug" / "app-debug.aab",
        "assembleRelease": outputs / "apk" / "release" / "app-release.apk",
        "bundleRelease": outputs / "bundle" / "release" / "app-release.aab",
    }
    for task in tasks:
        path = mapping.get(task)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake")


def _patch_collaborators(monkeypatch, *, downloads: Path, calls: dict):
    """Stub the network/render/Gradle collaborators ``android_build`` drives.

    Left real (pure or filesystem-only, worth exercising as-is): ``select_wheel``,
    ``python_stem``, ``check_pyjnius_contract``, ``check_sdl_glue_contract``,
    ``_write_local_properties``, ``_copy_include_files``.
    """
    downloads.mkdir(parents=True, exist_ok=True)
    calls.setdefault("fetch", [])
    calls.setdefault("run_gradle", [])
    calls.setdefault("write_app_build_gradle", [])
    calls.setdefault("write_gradle_pins", [])

    def fake_fetch_artifact(
        *, name, sha256, filename, url, path, project_root, no_cache
    ):
        calls["fetch"].append(name)
        dest = downloads / filename
        if not dest.exists():
            dest.write_bytes(b"fake-artifact")
        return str(dest)

    def fake_extract_runtime(tarball, dest):
        dest.mkdir(parents=True, exist_ok=True)
        return dest / "prefix"

    def fake_install_wheels(files, target, **kw):
        calls.setdefault("install_wheels", []).append(len(files))

    def fake_stage_runtime_libs(stager, prefix_lib, *, python_stem):
        return (0, 0)

    def fake_stage_wheel_libs_dir(stager, libs_dir, *, wheel_name):
        return 0

    def fake_stage_site_packages_extensions(stager, site_packages, *, wheel_name):
        return 0

    def fake_assemble_bundle(dest, **kw):
        dest.mkdir(parents=True, exist_ok=True)
        return "deadbeef"

    def fake_stdlib_dir(prefix, stem):
        return prefix / "lib" / stem

    def fake_render_bootstrap(*, sdl, python_version):
        return [
            RenderedFile("java/org/kivy/android/PythonActivity.java", "// activity\n")
        ]

    def fake_androidtest_files():
        return [RenderedFile("androidTest/java/Probe.java", "// probe\n")]

    def fake_generate_manifest(android, *, orientation):
        return f"<manifest package='{android.package}'/>\n"

    def fake_run_gradle(dest, tasks, **kw):
        calls["run_gradle"].append(tuple(tasks))
        _gradle_output_for(dest, tasks)

    patches = {
        "fetch_artifact": fake_fetch_artifact,
        "extract_runtime": fake_extract_runtime,
        "install_wheels": fake_install_wheels,
        "stage_runtime_libs": fake_stage_runtime_libs,
        "stage_wheel_libs_dir": fake_stage_wheel_libs_dir,
        "stage_site_packages_extensions": fake_stage_site_packages_extensions,
        "assemble_bundle": fake_assemble_bundle,
        "stdlib_dir": fake_stdlib_dir,
        "render_bootstrap": fake_render_bootstrap,
        "androidtest_files": fake_androidtest_files,
        "finder_source": lambda: "",
        "kivy_bootstrap_source": lambda: "",
        "selftest_source": lambda: "",
        "generate_manifest": fake_generate_manifest,
        "write_settings_gradle": lambda dest: None,
        "write_root_build_gradle": lambda dest, android: None,
        "write_gradle_properties": lambda dest, android: None,
        "stage_gradle_wrapper": lambda dest: None,
        "write_app_build_gradle": lambda dest, config, android, **kw: calls[
            "write_app_build_gradle"
        ].append(kw),
        "write_resources": lambda dest, config, android: None,
        "write_gradle_pins": lambda dest, lock: calls["write_gradle_pins"].append(lock),
        "run_gradle": fake_run_gradle,
    }
    for name, fn in patches.items():
        monkeypatch.setattr(cli, name, fn)


@pytest.fixture
def build_env(project, monkeypatch, tmp_path):
    """A project with an in-sync lock and every collaborator stubbed."""
    _write_lock(project)
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "fake-sdk"))  # skip SDK probe
    calls: dict = {}
    _patch_collaborators(monkeypatch, downloads=tmp_path / "downloads", calls=calls)
    return project, calls


class TestAndroidBuildHappyPath:
    def test_generates_project_without_debug(self, build_env):
        project, calls = build_env
        dest = cli.android_build(project)
        assert dest == project / "demoapp-android"
        assert dest.is_dir()
        assert (
            dest / "AndroidManifest.xml"
        ).exists() is False  # lives under app/src/main
        manifest = dest / "app" / "src" / "main" / "AndroidManifest.xml"
        assert "org.example.demoapp" in manifest.read_text(encoding="utf-8")
        assert calls["fetch"]  # runtime, and the pyjnius wheel were fetched
        assert not calls["run_gradle"]  # no --debug -> no gradle invocation
        assert calls["write_gradle_pins"]

    def test_debug_invokes_assembledebug(self, build_env, capsys):
        project, calls = build_env
        dest = cli.android_build(project, debug=True, fmt="apk")
        assert calls["run_gradle"] == [("assembleDebug",)]
        out = capsys.readouterr().out
        assert "Built" in out
        assert (dest / "app" / "build" / "outputs" / "apk" / "debug").is_dir()

    def test_debug_bundle_invokes_bundledebug(self, build_env):
        project, calls = build_env
        cli.android_build(project, debug=True, fmt="aab")
        assert calls["run_gradle"] == [("bundleDebug",)]

    def test_no_cache_and_abi_forwarded_to_fetch(self, build_env):
        project, _ = build_env
        # Only one ABI is configured; passing it explicitly must not raise.
        cli.android_build(project, abi="arm64_v8a", no_cache=True)


class TestAndroidBuildGates:
    def test_pyjnius_contract_gate_blocks_before_generation(
        self, project, monkeypatch, tmp_path
    ):
        _write_lock(project, pyjnius_version="2.0.0")  # outside the compatible range
        monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "sdk"))
        calls: dict = {}
        _patch_collaborators(monkeypatch, downloads=tmp_path / "dl", calls=calls)
        with pytest.raises(AndroidBuildError, match="invoke0"):
            cli.android_build(project)
        assert not calls["fetch"]  # never got to step 2

    def test_sdl_glue_mismatch_blocks_build(self, project, monkeypatch, tmp_path):
        _write_lock(project)
        monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "sdk"))
        calls: dict = {}
        _patch_collaborators(monkeypatch, downloads=tmp_path / "dl", calls=calls)

        sdl_java = (
            "public static final int SDL_MAJOR_VERSION = 2;\n"
            "public static final int SDL_MINOR_VERSION = 32;\n"
            "public static final int SDL_MICRO_VERSION = 10;\n"
        )
        monkeypatch.setattr(
            cli,
            "render_bootstrap",
            lambda **kw: [
                RenderedFile("java/org/libsdl/app/SDLActivity.java", sdl_java)
            ],
        )

        def fake_stage_wheel_libs_dir(stager, libs_dir, *, wheel_name):
            stager.dest.mkdir(parents=True, exist_ok=True)
            (stager.dest / "libSDL2.so").write_bytes(
                b"junk release-2.30.0-0-gdeadbee junk"
            )
            return 1

        monkeypatch.setattr(cli, "stage_wheel_libs_dir", fake_stage_wheel_libs_dir)

        def fake_install_wheels(files, target, **kw):
            (target / ".libs").mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(cli, "install_wheels", fake_install_wheels)
        with pytest.raises(AndroidBuildError, match="SDL version mismatch"):
            cli.android_build(project)

    def test_runtime_stage_error_wrapped(self, build_env, monkeypatch):
        project, _ = build_env

        def boom(tarball, dest):
            raise RuntimeStageError("bad tarball")

        monkeypatch.setattr(cli, "extract_runtime", boom)
        with pytest.raises(AndroidBuildError, match="bad tarball"):
            cli.android_build(project)

    def test_wheel_stage_error_wrapped(self, build_env, monkeypatch):
        project, _ = build_env

        def boom(files, target, **kw):
            raise WheelStageError("pip blew up")

        monkeypatch.setattr(cli, "install_wheels", boom)
        with pytest.raises(AndroidBuildError, match="pip blew up"):
            cli.android_build(project)

    def test_bundle_error_wrapped(self, build_env, monkeypatch):
        project, _ = build_env

        def boom(dest, **kw):
            raise BundleError("bundle assembly failed")

        monkeypatch.setattr(cli, "assemble_bundle", boom)
        with pytest.raises(AndroidBuildError, match="bundle assembly failed"):
            cli.android_build(project)

    def test_gradle_error_wrapped_on_debug(self, build_env, monkeypatch):
        project, _ = build_env

        def boom(dest, tasks, **kw):
            raise GradleError("gradle exploded")

        monkeypatch.setattr(cli, "run_gradle", boom)
        with pytest.raises(AndroidBuildError, match="gradle exploded"):
            cli.android_build(project, debug=True)

    def test_invalid_abi_raises(self, build_env):
        project, _ = build_env
        with pytest.raises(AndroidBuildError, match="not in"):
            cli.android_build(project, abi="x86")


class TestAndroidBuildIncludeFiles:
    def test_include_files_copied(self, project, monkeypatch, tmp_path):
        text = PYPROJECT + (
            "\n[[tool.kivy.android.include_files]]\n"
            'dest = "app/src/main/assets/extra"\n'
            'sources = ["extra"]\n'
        )
        (project / "pyproject.toml").write_text(text, encoding="utf-8")
        (project / "extra").mkdir()
        (project / "extra" / "data.txt").write_text("hi", encoding="utf-8")
        _write_lock(project)
        monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "sdk"))
        calls: dict = {}
        _patch_collaborators(monkeypatch, downloads=tmp_path / "dl", calls=calls)

        dest = cli.android_build(project)
        copied = dest / "app" / "src" / "main" / "assets" / "extra" / "data.txt"
        assert copied.read_text(encoding="utf-8") == "hi"

    def test_include_files_overwriting_generated_rejected(
        self, project, monkeypatch, tmp_path
    ):
        text = PYPROJECT + (
            "\n[[tool.kivy.android.include_files]]\n"
            'dest = "."\n'
            'sources = ["evil/settings.gradle"]\n'
        )
        (project / "pyproject.toml").write_text(text, encoding="utf-8")
        (project / "evil").mkdir()
        (project / "evil" / "settings.gradle").write_text("x", encoding="utf-8")
        _write_lock(project)
        monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "sdk"))
        calls: dict = {}
        _patch_collaborators(monkeypatch, downloads=tmp_path / "dl", calls=calls)

        with pytest.raises(AndroidBuildError, match="include_files"):
            cli.android_build(project)


class TestLoadHelpers:
    def test_missing_lock_is_actionable(self, project):
        with pytest.raises(AndroidBuildError, match="pylock.android.toml not found"):
            cli._load(project, no_verify_lock=False)

    def test_unreadable_lock_is_wrapped(self, project):
        (project / "pylock.android.toml").write_text("{{ not toml", encoding="utf-8")
        with pytest.raises(AndroidBuildError):
            cli._load(project, no_verify_lock=False)

    def test_stale_lock_blocks_by_default(self, project):
        _write_lock(project, in_sync=False)
        with pytest.raises(AndroidBuildError, match="has changed since"):
            cli._load(project, no_verify_lock=False)

    def test_no_verify_lock_allows_stale(self, project):
        _write_lock(project, in_sync=False)
        config, lock = cli._load(project, no_verify_lock=True)
        assert lock.packages[0].name == "pyjnius"

    def test_bad_config_is_wrapped(self, project):
        (project / "pyproject.toml").write_text(
            "[project]\nname='x'\nversion='1'\n", encoding="utf-8"
        )
        with pytest.raises(AndroidBuildError):
            cli._load(project, no_verify_lock=True)


class TestSelectAbis:
    def test_default_returns_all_configured(self, project):
        config, _ = cli._load_config_only(project)
        assert cli._select_abis(config.android_required, None) == ("arm64_v8a",)

    def test_explicit_valid_abi(self, project):
        config, _ = cli._load_config_only(project)
        assert cli._select_abis(config.android_required, "arm64_v8a") == ("arm64_v8a",)

    def test_explicit_invalid_abi_raises(self, project):
        config, _ = cli._load_config_only(project)
        with pytest.raises(AndroidBuildError, match="not in"):
            cli._select_abis(config.android_required, "x86")


class TestLockedVersionAndStage:
    def test_locked_version_found(self, project):
        lock = _write_lock(project)
        assert cli._locked_version(lock, "pyjnius") == "1.7.0"

    def test_locked_version_missing(self, project):
        lock = _write_lock(project)
        assert cli._locked_version(lock, "kivy") is None

    def test_stage_passthrough_on_success(self):
        assert cli._stage(lambda: 42, RuntimeError) == 42

    def test_stage_wraps_matching_error(self):
        def boom():
            raise RuntimeStageError("nope")

        with pytest.raises(AndroidBuildError, match="nope"):
            cli._stage(boom, RuntimeStageError)


class TestDebugReleaseOutputPaths:
    def test_debug_apk_and_aab(self, tmp_path):
        assert cli._debug_output(tmp_path, "apk").name == "app-debug.apk"
        assert cli._debug_output(tmp_path, "aab").name == "app-debug.aab"

    def test_release_apk_and_aab(self, tmp_path):
        assert cli._release_output(tmp_path, "apk").name == "app-release.apk"
        assert cli._release_output(tmp_path, "aab").name == "app-release.aab"


class TestAndroidPackage:
    def test_signing_not_configured_raises(self, build_env):
        project, _ = build_env
        with pytest.raises(AndroidBuildError, match="code signing required"):
            cli.android_package(project)

    def _fake_signing(self, monkeypatch):
        from kivyforge.platforms.android.signing import ResolvedSigning

        resolved = ResolvedSigning(
            keystore=Path("release.keystore"),
            key_alias="upload",
            store_password_env="KIVYFORGE_KEYSTORE_PASSWORD",
            key_password_env="KIVYFORGE_KEY_PASSWORD",
            v1_signing=True,
            v2_signing=True,
            v3_signing=True,
            v4_signing=True,
        )
        monkeypatch.setattr(signing_mod, "resolve_signing", lambda *a, **k: resolved)

    def _fake_manifest_ok(self, monkeypatch):
        monkeypatch.setattr(
            policy_mod, "enforce_release_manifest", lambda xml, *, package: []
        )

    def test_success_assembles_release_apk(self, build_env, monkeypatch):
        project, calls = build_env
        self._fake_signing(monkeypatch)
        self._fake_manifest_ok(monkeypatch)
        out = cli.android_package(project, fmt="apk")
        assert out.name == "app-release.apk"
        assert calls["run_gradle"] == [("assembleRelease",)]

    def test_success_bundles_release_aab(self, build_env, monkeypatch):
        project, calls = build_env
        self._fake_signing(monkeypatch)
        self._fake_manifest_ok(monkeypatch)
        out = cli.android_package(project, fmt="aab")
        assert out.name == "app-release.aab"
        assert calls["run_gradle"] == [("bundleRelease",)]

    def test_manifest_policy_violation_blocks_before_gradle(
        self, build_env, monkeypatch
    ):
        project, calls = build_env
        self._fake_signing(monkeypatch)

        def boom(manifest_xml, *, package):
            raise policy_mod.ManifestPolicyError(
                [
                    policy_mod.PolicyFinding(
                        "FAIL", "exported component with no permission"
                    )
                ]
            )

        monkeypatch.setattr(policy_mod, "enforce_release_manifest", boom)
        with pytest.raises(AndroidBuildError, match="exported component"):
            cli.android_package(project)
        assert not calls["run_gradle"]  # blocked before Gradle ran

    def test_manifest_policy_infos_are_echoed(self, build_env, monkeypatch, capsys):
        project, _ = build_env
        self._fake_signing(monkeypatch)
        monkeypatch.setattr(
            policy_mod,
            "enforce_release_manifest",
            lambda xml, *, package: [
                policy_mod.PolicyFinding("INFO", "cleartext traffic is disabled")
            ],
        )
        cli.android_package(project)
        assert "cleartext traffic is disabled" in capsys.readouterr().out

    def test_gradle_failure_wrapped(self, build_env, monkeypatch):
        project, _ = build_env
        self._fake_signing(monkeypatch)
        self._fake_manifest_ok(monkeypatch)

        def boom(dest, tasks, **kw):
            raise GradleError("release build failed")

        monkeypatch.setattr(cli, "run_gradle", boom)
        with pytest.raises(AndroidBuildError, match="release build failed"):
            cli.android_package(project)


class TestAndroidRun:
    def test_no_build_missing_apk_raises(self, build_env):
        project, _ = build_env
        with pytest.raises(AndroidBuildError, match="no debug APK"):
            cli.android_run(project, no_build=True)

    def test_builds_then_installs_and_launches(self, build_env, monkeypatch):
        project, calls = build_env
        events = []
        monkeypatch.setattr(adb_mod, "resolve_device", lambda **kw: "emulator-5554")
        monkeypatch.setattr(
            adb_mod, "install_apk", lambda dev, apk: events.append(("install", dev))
        )
        monkeypatch.setattr(
            adb_mod, "logcat_clear", lambda dev: events.append(("clear", dev))
        )
        monkeypatch.setattr(
            adb_mod,
            "launch",
            lambda dev, pkg, act: events.append(("launch", dev, pkg, act)),
        )
        monkeypatch.setattr(
            adb_mod, "logcat_dump", lambda dev: "I/kivyforge: booted\nI/other: noise\n"
        )
        log = cli.android_run(project, wait_sec=0)
        assert calls["run_gradle"] == [("assembleDebug",)]
        assert ("install", "emulator-5554") in events
        assert "booted" in log

    def test_no_build_uses_existing_apk(self, build_env, monkeypatch):
        project, calls = build_env
        apk = (
            project
            / "demoapp-android"
            / "app"
            / "build"
            / "outputs"
            / "apk"
            / "debug"
            / "app-debug.apk"
        )
        apk.parent.mkdir(parents=True)
        apk.write_bytes(b"fake")
        monkeypatch.setattr(adb_mod, "resolve_device", lambda **kw: "emulator-5554")
        monkeypatch.setattr(adb_mod, "install_apk", lambda dev, apk: None)
        monkeypatch.setattr(adb_mod, "logcat_clear", lambda dev: None)
        monkeypatch.setattr(adb_mod, "launch", lambda dev, pkg, act: None)
        monkeypatch.setattr(adb_mod, "logcat_dump", lambda dev: "")
        cli.android_run(project, no_build=True, wait_sec=0)
        assert not calls["run_gradle"]

    def test_adb_error_is_wrapped(self, build_env, monkeypatch):
        project, _ = build_env

        def boom(**kw):
            raise adb_mod.AdbError("no device attached")

        monkeypatch.setattr(adb_mod, "resolve_device", boom)
        with pytest.raises(AndroidBuildError, match="no device attached"):
            cli.android_run(project, wait_sec=0)


class TestAndroidSmoke:
    def test_success(self, build_env, monkeypatch, capsys):
        project, calls = build_env
        monkeypatch.setattr(adb_mod, "resolve_device", lambda **kw: "emulator-5554")
        monkeypatch.setattr(smoke_mod, "run_smoke", lambda dest, *, release: None)
        cli.android_smoke(project)
        assert "PASSED" in capsys.readouterr().out

    def test_smoke_error_is_wrapped(self, build_env, monkeypatch):
        project, _ = build_env
        monkeypatch.setattr(adb_mod, "resolve_device", lambda **kw: "emulator-5554")

        def boom(dest, *, release):
            raise smoke_mod.SmokeError("contract test failed")

        monkeypatch.setattr(smoke_mod, "run_smoke", boom)
        with pytest.raises(AndroidBuildError, match="contract test failed"):
            cli.android_smoke(project)

    def test_adb_error_is_wrapped(self, build_env, monkeypatch):
        project, _ = build_env

        def boom(**kw):
            raise adb_mod.AdbError("no AVD exists")

        monkeypatch.setattr(adb_mod, "resolve_device", boom)
        with pytest.raises(AndroidBuildError, match="no AVD exists"):
            cli.android_smoke(project)


class TestAndroidOpen:
    def test_missing_project_raises(self, project):
        with pytest.raises(AndroidBuildError, match="does not exist yet"):
            cli.android_open(project)

    def test_opens_with_studio_found(self, project, monkeypatch):
        dest = project / "demoapp-android"
        dest.mkdir()
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/studio" if name == "studio" else None,
        )
        popen_calls = []
        monkeypatch.setattr(
            "subprocess.Popen", lambda cmd: popen_calls.append(cmd) or object()
        )
        cli.android_open(project)
        assert popen_calls and popen_calls[0][0] == "/usr/bin/studio"

    def test_prints_manual_instructions_when_no_studio(
        self, project, monkeypatch, capsys
    ):
        dest = project / "demoapp-android"
        dest.mkdir()
        monkeypatch.setattr(shutil, "which", lambda name: None)
        cli.android_open(project)
        out = capsys.readouterr().out
        assert "Open this project manually" in out


class TestWriteLocalProperties:
    def test_skips_when_android_home_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
        dest = tmp_path / "proj"
        dest.mkdir()
        cli._write_local_properties(dest)
        assert not (dest / "local.properties").exists()

    def test_writes_when_sdk_detected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANDROID_HOME", raising=False)
        monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
        sdk = tmp_path / "sdk"
        sdk.mkdir()
        monkeypatch.setattr(RealAndroidProbe, "sdk_root", lambda self: sdk)
        dest = tmp_path / "proj"
        dest.mkdir()
        cli._write_local_properties(dest)
        content = (dest / "local.properties").read_text(encoding="utf-8")
        assert "sdk.dir=" in content

    def test_no_file_when_sdk_not_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANDROID_HOME", raising=False)
        monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
        monkeypatch.setattr(RealAndroidProbe, "sdk_root", lambda self: None)
        dest = tmp_path / "proj"
        dest.mkdir()
        cli._write_local_properties(dest)
        assert not (dest / "local.properties").exists()


class TestAndroidStatusLockStates:
    def test_in_sync(self, project, capsys):
        _write_lock(project, in_sync=True)
        cli.android_status(project)
        assert "in sync" in capsys.readouterr().out

    def test_out_of_date(self, project, capsys):
        _write_lock(project, in_sync=False)
        cli.android_status(project)
        assert "out of date" in capsys.readouterr().out

    def test_unreadable(self, project, capsys):
        (project / "pylock.android.toml").write_text("{{ not toml", encoding="utf-8")
        cli.android_status(project)
        assert "unreadable" in capsys.readouterr().out

    def test_reports_built_artifacts(self, project, capsys):
        _write_lock(project, in_sync=True)
        dest = project / "demoapp-android"
        apk = dest / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        apk.parent.mkdir(parents=True)
        apk.write_bytes(b"x")
        cli.android_status(project)
        out = capsys.readouterr().out
        assert "apk (debug)" in out and "built" in out
