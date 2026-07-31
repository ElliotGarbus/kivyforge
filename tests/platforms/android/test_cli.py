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
from kivyforge.platforms.android.generate.project import (
    MERGED_MANIFEST_RELPATH,
    MERGED_MANIFEST_TASK,
)
from kivyforge.platforms.android.gradlew import GradleError
from kivyforge.platforms.android.lock import writer as lock_writer
from kivyforge.platforms.android.lock.model import (
    AndroidLockfile,
    LockedIncludeFile,
    PythonAndroidRuntime,
)
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


def _include_pins(project_root: Path, dest: str, *sources: str):
    """The include_files pins `kivyforge lock` would have recorded for *sources*."""
    from kivyforge.artifacts.verify import sha256_file

    pins = []
    for source in sources:
        local = project_root / source
        children = (
            [c for c in sorted(local.rglob("*")) if c.is_file()]
            if local.is_dir()
            else [local]
        )
        for child in children:
            rel = (
                (Path(source) / child.relative_to(local)).as_posix()
                if local.is_dir()
                else source
            )
            pins.append(
                LockedIncludeFile(source=rel, dest=dest, sha256=sha256_file(child))
            )
    return tuple(pins)


def _write_lock(
    project_root: Path,
    *,
    in_sync: bool = True,
    pyjnius_version="1.7.0",
    include_files=(),
):
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
        kivy_generation=2,
        include_files=tuple(include_files),
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
        if task == MERGED_MANIFEST_TASK:
            # Stand in for AGP's manifest merge: with no library manifests to
            # merge, the merged manifest is the generated one.
            merged = dest / MERGED_MANIFEST_RELPATH
            merged.parent.mkdir(parents=True, exist_ok=True)
            source = dest / "app" / "src" / "main" / "AndroidManifest.xml"
            merged.write_text(
                source.read_text(encoding="utf-8")
                if source.is_file()
                else "<manifest/>",
                encoding="utf-8",
            )


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
        calls.setdefault("assemble_bundle", []).append(kw)
        dest.mkdir(parents=True, exist_ok=True)
        return "deadbeef"

    def fake_stdlib_dir(prefix, stem):
        return prefix / "lib" / stem

    def fake_render_bootstrap(*, sdl, python_version, entry_point="main"):
        calls.setdefault("render_bootstrap", []).append(entry_point)
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
        "write_settings_gradle": lambda dest, android: None,
        "write_root_build_gradle": lambda dest, android: None,
        "write_gradle_properties": lambda dest, android: None,
        "stage_gradle_wrapper": lambda dest: None,
        "write_app_build_gradle": lambda dest, config, android, **kw: calls[
            "write_app_build_gradle"
        ].append(kw),
        "write_resources": lambda dest, config, android, **kw: None,
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

    def test_entry_point_reaches_the_bootstrap_and_bundle(self, project, build_env):
        """The configured entry_point has to reach both the rendered activity
        (which exports KF_ENTRY_POINT) and the bundle (which validates that the
        module exists); otherwise the app imports main.py regardless."""
        project, calls = build_env
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                'app_dir = "src"', 'app_dir = "src"\nentry_point = "app.start"'
            ),
            encoding="utf-8",
        )
        _write_lock(project)
        cli.android_build(project)
        assert calls["render_bootstrap"] == ["app.start"]
        assert calls["assemble_bundle"][0]["entry_point"] == "app.start"


SERVICES_TOML = """
[[tool.kivy.android.services]]
name = "Downloader"
entry_point = "service_downloader"
"""


class TestGeneratedServices:
    """A <service> in the manifest is only real if its class is in the APK."""

    def _with_services(self, project, toml=SERVICES_TOML):
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8") + toml, encoding="utf-8"
        )
        (project / "src" / "service_downloader.py").write_text("", encoding="utf-8")
        _write_lock(project)

    def test_declared_service_gets_its_class_written(self, build_env):
        project, calls = build_env
        self._with_services(project)
        dest = cli.android_build(project)
        main = dest / "app" / "src" / "main"
        source = main / "java" / "org" / "kivy" / "android" / "ServiceDownloader.java"
        assert source.is_file()
        assert 'return "service_downloader";' in source.read_text(encoding="utf-8")

    def test_service_entry_points_are_validated_by_the_bundle(self, build_env):
        project, calls = build_env
        self._with_services(project)
        cli.android_build(project)
        assert calls["assemble_bundle"][0]["service_entry_points"] == {
            "Downloader": "service_downloader"
        }

    def test_service_probe_is_generated_with_the_service(self, build_env):
        project, _ = build_env
        self._with_services(project)
        dest = cli.android_build(project)
        probe = (
            dest
            / "app"
            / "src"
            / "androidTest"
            / "java"
            / "org"
            / "kivyforge"
            / "test"
            / "KivyforgeServiceContractTest.java"
        )
        assert probe.is_file()
        assert "ServiceDownloader.class" in probe.read_text(encoding="utf-8")

    def test_no_services_generates_no_class_or_probe(self, build_env):
        project, _ = build_env
        dest = cli.android_build(project)
        android_pkg = (
            dest / "app" / "src" / "main" / "java" / "org" / "kivy" / "android"
        )
        assert not android_pkg.is_dir() or list(android_pkg.glob("Service*.java")) == []
        probe_dir = (
            dest / "app" / "src" / "androidTest" / "java" / "org" / "kivyforge" / "test"
        )
        assert not (probe_dir / "KivyforgeServiceContractTest.java").exists()

    def test_removing_a_service_removes_its_generated_sources(self, build_env):
        """The project dir is incremental, so a class for a service that is gone
        would keep compiling in — and the probe would not compile at all."""
        project, _ = build_env
        self._with_services(project)
        dest = cli.android_build(project)
        stale = (
            dest
            / "app"
            / "src"
            / "main"
            / "java"
            / "org"
            / "kivy"
            / "android"
            / "ServiceDownloader.java"
        )
        probe = (
            dest
            / "app"
            / "src"
            / "androidTest"
            / "java"
            / "org"
            / "kivyforge"
            / "test"
            / "KivyforgeServiceContractTest.java"
        )
        assert stale.is_file() and probe.is_file()

        (project / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        _write_lock(project)
        cli.android_build(project)
        assert not stale.exists()
        assert not probe.exists()


class TestByteCompileResolution:
    """``byte_compile``/``strip_source`` (android/01 §build_settings).

    A .pyc is only loadable by the exact CPython that wrote it, and kivyforge
    runs under whatever Python the user installed it with — usually not the one
    being shipped. So the interesting behavior is which interpreter gets chosen
    and what happens when there is none.
    """

    def _android(self, extra: str = ""):
        from kivyforge.config.loader import load_config_from_text

        text = PYPROJECT.replace(
            "[tool.kivy.android.python]", extra + "\n[tool.kivy.android.python]"
        )
        config = load_config_from_text(text, require_ios=False, require_android=True)
        return config.android_required

    def _resolve(self, android, *, debug=False):
        return cli._resolve_byte_compile(android, python_version="3.14.6", debug=debug)

    def _found(self, monkeypatch, argv=("py", "-3.14")):
        monkeypatch.setattr(cli, "_byte_compile_interpreter", lambda _v: argv)

    def _missing(self, monkeypatch):
        monkeypatch.setattr(cli, "_byte_compile_interpreter", lambda _v: None)

    def test_release_default_compiles_and_strips(self, monkeypatch):
        self._found(monkeypatch)
        assert self._resolve(self._android()) == (("py", "-3.14"), True)

    def test_debug_build_keeps_readable_sources(self, monkeypatch):
        self._found(monkeypatch)
        assert self._resolve(self._android(), debug=True) == (None, False)

    def test_false_never_compiles(self, monkeypatch):
        self._found(monkeypatch)
        android = self._android(
            "[tool.kivy.android.build_settings]\nbyte_compile = false\n"
        )
        assert self._resolve(android) == (None, False)

    def test_strip_source_is_ignored_without_byte_compile(self, monkeypatch):
        self._found(monkeypatch)
        android = self._android(
            "[tool.kivy.android.build_settings]\n"
            "byte_compile = false\nstrip_source = true\n"
        )
        assert self._resolve(android) == (None, False)

    def test_true_compiles_for_debug_too(self, monkeypatch):
        self._found(monkeypatch)
        android = self._android(
            "[tool.kivy.android.build_settings]\n"
            "byte_compile = true\nstrip_source = false\n"
        )
        assert self._resolve(android, debug=True) == (("py", "-3.14"), False)

    def test_default_degrades_when_no_interpreter_exists(self, monkeypatch, capsys):
        """The default must not break a build nobody configured: a user on 3.13
        shipping 3.14 gets source, not a failure."""
        self._missing(monkeypatch)
        assert self._resolve(self._android()) == (None, False)
        assert "not byte-compiling" in capsys.readouterr().out

    def test_explicit_true_fails_when_no_interpreter_exists(self, monkeypatch):
        """Asked for outright, silence would ship a bundle the user believes is
        compiled."""
        self._missing(monkeypatch)
        android = self._android(
            "[tool.kivy.android.build_settings]\nbyte_compile = true\n"
        )
        with pytest.raises(
            AndroidBuildError, match=r"no \*final\* release of CPython 3\.14"
        ):
            self._resolve(android)

    def test_this_interpreter_is_used_when_it_matches(self, monkeypatch):
        import sys

        version = f"{sys.version_info[0]}.{sys.version_info[1]}.0"
        assert cli._byte_compile_interpreter(version) == ()

    def test_the_choice_reaches_the_bundle(self, build_env, monkeypatch):
        project, calls = build_env
        self._found(monkeypatch, ("python3.14",))
        cli.android_build(project)
        assert calls["assemble_bundle"][0]["byte_compile"] == ("python3.14",)
        assert calls["assemble_bundle"][0]["strip_source"] is True


class TestPreReleaseInterpretersRejected:
    """A pre-release of the *right* minor must not be used as the compiler.

    CPython bumps the .pyc magic number through the alpha/beta cycle and only
    freezes it at the first release candidate, so 3.14.0a7 (magic 3621) writes
    bytecode that shipped 3.14.6 (magic 3627) refuses to import — while still
    answering "3.14" to a bare version check. Caught in the field: an Android
    build picked a 3.14.0a7 and produced an unbootable bundle, visible only
    because two 3.14 stdlib modules use t-string syntax the alpha cannot parse.
    """

    def _fake_interpreter(self, monkeypatch, minor: str, releaselevel: str):
        """Stand in for a real interpreter answering the probe."""
        import subprocess

        class _Proc:
            returncode = 0
            stdout = f"{minor} {releaselevel}\n"
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())

    def test_final_release_accepted(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14", "final")
        assert cli._reports_version(("python3.14",), "3.14") is True

    def test_alpha_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14", "alpha")
        assert cli._reports_version(("python3.14",), "3.14") is False

    def test_beta_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.14", "beta")
        assert cli._reports_version(("python3.14",), "3.14") is False

    def test_release_candidate_rejected(self, monkeypatch):
        # Safe in principle (the magic freezes at rc1), but the margin is not
        # worth it when the fallback is simply shipping readable source.
        self._fake_interpreter(monkeypatch, "3.14", "candidate")
        assert cli._reports_version(("python3.14",), "3.14") is False

    def test_wrong_minor_still_rejected(self, monkeypatch):
        self._fake_interpreter(monkeypatch, "3.13", "final")
        assert cli._reports_version(("python3.14",), "3.14") is False

    def test_running_under_a_prerelease_is_not_used_in_process(self, monkeypatch):
        """The `return ()` in-process shortcut needs the same guard."""
        import sys

        version = f"{sys.version_info[0]}.{sys.version_info[1]}.0"
        monkeypatch.setattr(
            "kivyforge.bundle.pycompile.is_final_release", lambda: False
        )
        # No other interpreter can be found either, so the search degrades.
        monkeypatch.setattr(cli, "_reports_version", lambda argv, tag: False)
        assert cli._byte_compile_interpreter(version) is None


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


EXTRA_DEST = "app/src/main/assets/extra"


class TestAndroidBuildIncludeFiles:
    def _project_with_extra(self, project, monkeypatch, tmp_path, *, pins=True):
        text = PYPROJECT + (
            "\n[[tool.kivy.android.include_files]]\n"
            f'dest = "{EXTRA_DEST}"\n'
            'sources = ["extra"]\n'
        )
        (project / "pyproject.toml").write_text(text, encoding="utf-8")
        (project / "extra").mkdir(exist_ok=True)
        (project / "extra" / "data.txt").write_text("hi", encoding="utf-8")
        _write_lock(
            project,
            include_files=(_include_pins(project, EXTRA_DEST, "extra") if pins else ()),
        )
        monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "sdk"))
        _patch_collaborators(monkeypatch, downloads=tmp_path / "dl", calls={})

    def test_include_files_copied(self, project, monkeypatch, tmp_path):
        self._project_with_extra(project, monkeypatch, tmp_path)
        dest = cli.android_build(project)
        copied = dest / "app" / "src" / "main" / "assets" / "extra" / "data.txt"
        assert copied.read_text(encoding="utf-8") == "hi"

    def test_edited_file_fails_with_both_hashes(self, project, monkeypatch, tmp_path):
        """The lock records a hash per staged file so drift is detectable; an
        edited vendored asset used to ship with a lock that said otherwise."""
        self._project_with_extra(project, monkeypatch, tmp_path)
        (project / "extra" / "data.txt").write_text("edited", encoding="utf-8")
        with pytest.raises(AndroidBuildError, match="has changed since the lock") as e:
            cli.android_build(project)
        message = str(e.value)
        assert "locked:" in message and "on disk:" in message
        assert "kivyforge lock" in message

    def test_new_file_in_a_directory_source_fails(self, project, monkeypatch, tmp_path):
        """A directory source is expanded per file at lock time, so a file added
        afterwards has no pin at all."""
        self._project_with_extra(project, monkeypatch, tmp_path)
        (project / "extra" / "added.txt").write_text("new", encoding="utf-8")
        with pytest.raises(AndroidBuildError, match="records no hash"):
            cli.android_build(project)

    def test_deleted_file_fails(self, project, monkeypatch, tmp_path):
        """The per-file walk cannot see a deletion, so the leftover pins are."""
        self._project_with_extra(project, monkeypatch, tmp_path)
        (project / "extra" / "gone.txt").write_text("bye", encoding="utf-8")
        _write_lock(project, include_files=_include_pins(project, EXTRA_DEST, "extra"))
        (project / "extra" / "gone.txt").unlink()
        with pytest.raises(AndroidBuildError, match="no longer exists"):
            cli.android_build(project)

    def test_no_verify_lock_skips_the_drift_check(self, project, monkeypatch, tmp_path):
        """--no-verify-lock means the lock is not being enforced at all."""
        self._project_with_extra(project, monkeypatch, tmp_path, pins=False)
        dest = cli.android_build(project, no_verify_lock=True)
        copied = dest / "app" / "src" / "main" / "assets" / "extra" / "data.txt"
        assert copied.is_file()

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
        _write_lock(
            project,
            include_files=_include_pins(project, ".", "evil/settings.gradle"),
        )
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


class TestArtifactExistenceGate:
    """A green Gradle run plus a missing artifact means AGP's output layout
    moved — announcing a path that isn't there is worse than failing."""

    def test_missing_debug_artifact_fails(self, build_env, monkeypatch):
        project, _ = build_env
        monkeypatch.setattr(cli, "run_gradle", lambda dest, tasks, **kw: None)
        with pytest.raises(AndroidBuildError, match="no artifact is at"):
            cli.android_build(project, debug=True)

    def test_present_artifact_is_returned(self, tmp_path):
        apk = tmp_path / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        apk.parent.mkdir(parents=True)
        apk.write_bytes(b"fake")
        assert cli._require_artifact(apk, "assembleDebug") == apk


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
            policy_mod, "enforce_release_manifest", lambda xml, **kw: []
        )

    def test_success_assembles_release_apk(self, build_env, monkeypatch):
        project, calls = build_env
        self._fake_signing(monkeypatch)
        self._fake_manifest_ok(monkeypatch)
        out = cli.android_package(project, fmt="apk")
        assert out.name == "app-release.apk"
        assert calls["run_gradle"] == [
            ("lintRelease", MERGED_MANIFEST_TASK),
            ("assembleRelease",),
        ]

    def test_success_bundles_release_aab(self, build_env, monkeypatch):
        project, calls = build_env
        self._fake_signing(monkeypatch)
        self._fake_manifest_ok(monkeypatch)
        out = cli.android_package(project, fmt="aab")
        assert out.name == "app-release.aab"
        assert calls["run_gradle"] == [
            ("lintRelease", MERGED_MANIFEST_TASK),
            ("bundleRelease",),
        ]

    def test_manifest_policy_violation_blocks_before_gradle(
        self, build_env, monkeypatch
    ):
        project, calls = build_env
        self._fake_signing(monkeypatch)

        def boom(manifest_xml, **kw):
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
            lambda xml, **kw: [
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


_CLEAN_MANIFEST = (
    '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
    "<application>"
    '<activity android:name="org.kivy.android.PythonActivity" '
    'android:exported="true">'
    '<intent-filter><action android:name="android.intent.action.MAIN"/>'
    '<category android:name="android.intent.category.LAUNCHER"/>'
    "</intent-filter></activity>"
    "</application></manifest>\n"
)


def _merged_manifest_with(dest: Path, body: str) -> None:
    out = dest / MERGED_MANIFEST_RELPATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        f"<application>{body}</application></manifest>\n",
        encoding="utf-8",
    )


class TestMergedManifestPolicy:
    """The generated manifest is only half the story: AGP merges library
    manifests into what actually ships, so the policy runs again on that."""

    def _ready(self, build_env, monkeypatch, *, extra_toml: str = ""):
        """A project the *real* policy passes: a non-placeholder applicationId
        and a generated manifest with exactly one bootstrap LAUNCHER."""
        project, calls = build_env
        TestAndroidPackage()._fake_signing(monkeypatch)
        text = (project / "pyproject.toml").read_text(encoding="utf-8")
        (project / "pyproject.toml").write_text(
            text.replace("org.example.demoapp", "com.acme.demoapp") + extra_toml,
            encoding="utf-8",
        )
        _write_lock(project)
        monkeypatch.setattr(
            cli, "generate_manifest", lambda android, *, orientation: _CLEAN_MANIFEST
        )
        return project, calls

    def test_lint_and_the_export_task_run_before_assembling(
        self, build_env, monkeypatch, capsys
    ):
        project, calls = self._ready(build_env, monkeypatch)
        cli.android_package(project)
        assert calls["run_gradle"][0] == ("lintRelease", MERGED_MANIFEST_TASK)
        out = capsys.readouterr().out
        assert "lintRelease" in out
        assert "merged release manifest" in out

    def _merge_in(self, monkeypatch, calls, body):
        """Let the export task 'merge' an extra component into the manifest."""

        def fake_run_gradle(dest, tasks, **kw):
            calls["run_gradle"].append(tuple(tasks))
            _gradle_output_for(dest, tasks)
            if MERGED_MANIFEST_TASK in tasks:
                _merged_manifest_with(dest, body)

        monkeypatch.setattr(cli, "run_gradle", fake_run_gradle)

    _VENDOR_EXPORTED = (
        '<activity android:name="com.vendor.sdk.Trampoline" android:exported="true"/>'
    )

    def test_a_merged_only_violation_blocks_the_release(self, build_env, monkeypatch):
        # The generated manifest is clean; the merge adds a library's exported
        # activity, which only the second pass can see.
        project, calls = self._ready(build_env, monkeypatch)
        self._merge_in(monkeypatch, calls, self._VENDOR_EXPORTED)
        with pytest.raises(AndroidBuildError, match="com.vendor.sdk.Trampoline"):
            cli.android_package(project)
        # Blocked before the release was assembled (and therefore signed).
        assert calls["run_gradle"] == [("lintRelease", MERGED_MANIFEST_TASK)]

    def test_allow_exported_admits_a_library_component(self, build_env, monkeypatch):
        project, calls = self._ready(
            build_env,
            monkeypatch,
            extra_toml="\n[tool.kivy.android.manifest]\n"
            'allow_exported = ["com.vendor.sdk.Trampoline"]\n',
        )
        self._merge_in(
            monkeypatch,
            calls,
            self._VENDOR_EXPORTED
            + '<activity android:name="org.kivy.android.PythonActivity" '
            'android:exported="true"><intent-filter>'
            '<action android:name="android.intent.action.MAIN"/>'
            '<category android:name="android.intent.category.LAUNCHER"/>'
            "</intent-filter></activity>",
        )
        out = cli.android_package(project)
        assert out.name == "app-release.apk"

    def test_a_lint_finding_points_at_the_report(self, build_env, monkeypatch):
        project, _ = self._ready(build_env, monkeypatch)

        def boom(dest, tasks, **kw):
            raise GradleError("Lint found 1 error")

        monkeypatch.setattr(cli, "run_gradle", boom)
        with pytest.raises(AndroidBuildError, match="lint-results-release.html"):
            cli.android_package(project)

    def test_a_missing_merged_manifest_is_an_error_not_a_pass(
        self, build_env, monkeypatch
    ):
        project, calls = self._ready(build_env, monkeypatch)

        def no_export(dest, tasks, **kw):
            calls["run_gradle"].append(tuple(tasks))

        monkeypatch.setattr(cli, "run_gradle", no_export)
        with pytest.raises(AndroidBuildError, match="produced no manifest"):
            cli.android_package(project)


def _fake_device(monkeypatch, *, serial="emulator-5554", abi="arm64_v8a"):
    """Stand in for an attached target: `run`/`--smoke` resolve one, then ask it
    which ABI to build for."""
    seen: dict = {}

    def resolve(**kw):
        seen.update(kw)
        return serial

    monkeypatch.setattr(adb_mod, "resolve_device", resolve)
    monkeypatch.setattr(adb_mod, "device_abi", lambda dev: abi)
    return seen


class TestAndroidRun:
    def test_no_build_missing_apk_raises(self, build_env, monkeypatch):
        project, _ = build_env
        _fake_device(monkeypatch)
        with pytest.raises(AndroidBuildError, match="no debug APK"):
            cli.android_run(project, no_build=True)

    def test_builds_then_installs_and_launches(self, build_env, monkeypatch):
        project, calls = build_env
        events = []
        _fake_device(monkeypatch)
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
        _fake_device(monkeypatch)
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

    def test_abi_defaults_to_the_targets_own(self, build_env, monkeypatch):
        """android/06 §run: `--abi`'s default is the target's architecture, and
        the target itself is the accurate source for it."""
        project, calls = build_env
        _fake_device(monkeypatch, abi="arm64_v8a")
        monkeypatch.setattr(adb_mod, "install_apk", lambda dev, apk: None)
        monkeypatch.setattr(adb_mod, "logcat_clear", lambda dev: None)
        monkeypatch.setattr(adb_mod, "launch", lambda dev, pkg, act: None)
        monkeypatch.setattr(adb_mod, "logcat_dump", lambda dev: "")
        cli.android_run(project, wait_sec=0)
        # The build's effective ABI set reaches Gradle's abiFilters, so that is
        # where the restriction is observable.
        assert calls["write_app_build_gradle"][-1]["abis"] == ("arm64_v8a",)

    def test_explicit_abi_still_wins(self, build_env, monkeypatch):
        project, calls = build_env
        _fake_device(monkeypatch, abi="x86_64")
        monkeypatch.setattr(adb_mod, "install_apk", lambda dev, apk: None)
        monkeypatch.setattr(adb_mod, "logcat_clear", lambda dev: None)
        monkeypatch.setattr(adb_mod, "launch", lambda dev, pkg, act: None)
        monkeypatch.setattr(adb_mod, "logcat_dump", lambda dev: "")
        cli.android_run(project, abi="arm64_v8a", wait_sec=0)
        assert calls["write_app_build_gradle"][-1]["abis"] == ("arm64_v8a",)

    def test_device_needing_an_unlocked_abi_fails_before_gradle(
        self, build_env, monkeypatch
    ):
        """Otherwise this only surfaces as adb's INSTALL_FAILED_NO_MATCHING_ABIS
        after a full build."""
        project, calls = build_env
        _fake_device(monkeypatch, abi="x86_64")  # project locks arm64_v8a only
        with pytest.raises(AndroidBuildError, match="needs the x86_64 ABI"):
            cli.android_run(project, wait_sec=0)
        assert not calls["run_gradle"]

    def test_unknown_device_abi_falls_back_to_the_host(self, build_env, monkeypatch):
        project, calls = build_env
        _fake_device(monkeypatch, abi=None)  # e.g. a 32-bit-only device
        monkeypatch.setattr(adb_mod, "host_abi", lambda: "arm64_v8a")
        monkeypatch.setattr(adb_mod, "install_apk", lambda dev, apk: None)
        monkeypatch.setattr(adb_mod, "logcat_clear", lambda dev: None)
        monkeypatch.setattr(adb_mod, "launch", lambda dev, pkg, act: None)
        monkeypatch.setattr(adb_mod, "logcat_dump", lambda dev: "")
        cli.android_run(project, wait_sec=0)
        assert calls["write_app_build_gradle"][-1]["abis"] == ("arm64_v8a",)

    def test_require_physical_reaches_adb(self, build_env, monkeypatch):
        project, _ = build_env
        seen = _fake_device(monkeypatch)
        monkeypatch.setattr(adb_mod, "install_apk", lambda dev, apk: None)
        monkeypatch.setattr(adb_mod, "logcat_clear", lambda dev: None)
        monkeypatch.setattr(adb_mod, "launch", lambda dev, pkg, act: None)
        monkeypatch.setattr(adb_mod, "logcat_dump", lambda dev: "")
        cli.android_run(project, require_physical=True, wait_sec=0)
        assert seen["require_physical"] is True


class TestAndroidSmoke:
    def test_success(self, build_env, monkeypatch, capsys):
        project, calls = build_env
        _fake_device(monkeypatch)
        monkeypatch.setattr(smoke_mod, "run_smoke", lambda dest, *, release: None)
        cli.android_smoke(project)
        assert "PASSED" in capsys.readouterr().out

    def test_smoke_error_is_wrapped(self, build_env, monkeypatch):
        project, _ = build_env
        _fake_device(monkeypatch)

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

    def test_debug_smoke_leaves_the_test_variant_alone(self, build_env, monkeypatch):
        project, calls = build_env
        _fake_device(monkeypatch)
        monkeypatch.setattr(smoke_mod, "run_smoke", lambda dest, *, release: None)
        cli.android_smoke(project)
        gradle_kwargs = calls["write_app_build_gradle"][-1]
        assert gradle_kwargs["test_build_type"] is None
        assert gradle_kwargs["release_signing_config"] is None

    def test_release_smoke_configures_the_release_test_variant(
        self, build_env, monkeypatch, capsys
    ):
        """connectedReleaseAndroidTest only exists when the tests target the
        release variant, and AGP refuses to assemble an unsigned release — so
        without both, `run --smoke --release` could never have worked."""
        project, calls = build_env
        _fake_device(monkeypatch)
        seen = {}
        monkeypatch.setattr(
            smoke_mod,
            "run_smoke",
            lambda dest, *, release: seen.update(release=release),
        )
        cli.android_smoke(project, release=True)
        gradle_kwargs = calls["write_app_build_gradle"][-1]
        assert gradle_kwargs["test_build_type"] == "release"
        assert gradle_kwargs["release_signing_config"] == "debug"
        assert seen["release"] is True
        assert "debug keystore" in capsys.readouterr().out

    def test_release_smoke_prefers_the_configured_release_identity(
        self, project, monkeypatch, tmp_path
    ):
        keystore = tmp_path / "release.keystore"
        keystore.write_bytes(b"fake-keystore")
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8") + "\n[tool.kivy.android.signing]\n"
            f'keystore = "{keystore.as_posix()}"\nkey_alias = "upload"\n',
            encoding="utf-8",
        )
        _write_lock(project)
        monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "fake-sdk"))
        monkeypatch.setenv("KIVYFORGE_KEYSTORE_PASSWORD", "hunter2")
        calls: dict = {}
        _patch_collaborators(monkeypatch, downloads=tmp_path / "dl", calls=calls)
        monkeypatch.setattr(signing_mod, "_verify_alias", lambda *a, **kw: None)
        _fake_device(monkeypatch)
        monkeypatch.setattr(smoke_mod, "run_smoke", lambda dest, *, release: None)
        cli.android_smoke(project, release=True)
        gradle_kwargs = calls["write_app_build_gradle"][-1]
        assert gradle_kwargs["release_signing_config"] == "release"
        assert "upload" in gradle_kwargs["signing_config_block"]


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
