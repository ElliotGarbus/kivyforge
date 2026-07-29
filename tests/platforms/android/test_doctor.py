"""Android doctor: fake-probe matrix + ELF alignment (android/06)."""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config, load_config_from_text
from kivyforge.doctor.result import Status
from kivyforge.lock.model import LockedPackage, LockedWheel
from kivyforge.platforms.android.doctor import (
    RealAndroidProbe,
    _check_16k_alignment,
    _check_abi_coverage,
    _check_build_tools,
    _check_find_links,
    _check_gradle_wrapper,
    _check_icon,
    _check_include_files,
    _check_lock_hosts,
    _check_pyjnius_contract,
    _check_sdk,
    _check_sdl_kivy_match,
    _check_signing,
    _check_splash,
    android_doctor,
)
from kivyforge.platforms.android.elf import PAGE_16K, ElfError, read_elf, scan_alignment
from kivyforge.platforms.android.lock.model import (
    AndroidLockfile,
    LockedIncludeFile,
    PythonAndroidRuntime,
)


class FakeProbe:
    def __init__(self, **kw):
        self._which = kw.get("which", {})
        self._java_home = kw.get("java_home")
        self._sdk = kw.get("sdk")
        self._ndk = kw.get("ndk", [])
        self._build_tools = kw.get("build_tools", [])
        self._platforms = kw.get("platforms", set())
        self._avds = kw.get("avds", [])
        self._accel = kw.get("accel", True)
        self._reachable = kw.get("reachable", True)
        self._licenses = kw.get("licenses", ["android-sdk-license"])
        self._devices = kw.get("devices", ["emulator-5554"])
        self._latest = kw.get("latest")

    def which(self, name):
        return self._which.get(name)

    def java_home(self):
        return self._java_home

    def sdk_root(self):
        return self._sdk

    def ndk_versions(self, sdk):
        return list(self._ndk)

    def build_tools_versions(self, sdk):
        return list(self._build_tools)

    def platform_installed(self, sdk, api):
        return api in self._platforms

    def accepted_licenses(self, sdk):
        return list(self._licenses)

    def avds(self):
        return list(self._avds)

    def connected_devices(self):
        return list(self._devices)

    def has_kvm_or_haxm(self):
        return self._accel

    def tcp_reachable(self, host, port):
        return self._reachable

    def latest_kivyforge_version(self):
        return self._latest


def _healthy_probe(sdk: Path):
    return FakeProbe(
        which={"java": "/jdk/bin/java", "adb": "/sdk/platform-tools/adb"},
        java_home="/jdk",
        sdk=sdk,
        ndk=["27.3.13750724"],
        build_tools=["35.0.0"],
        platforms={35},
        avds=["kivyforge_x86_64"],
        accel=True,
    )


def _by_name(results):
    return {r.name: r for r in results}


class TestEnvironmentChecks:
    def test_all_healthy(self, tmp_path):
        results = android_doctor(
            tmp_path,
            kivyforge_version="0",
            offline=True,
            probe=_healthy_probe(tmp_path),
        )
        by = _by_name(results)
        assert by["JDK"].status is Status.PASS
        assert by["NDK"].status is Status.PASS
        assert by["Emulator / virtualization"].status is Status.PASS

    def test_no_jdk_fails(self, tmp_path):
        probe = FakeProbe(sdk=tmp_path, ndk=["27"], build_tools=["35.0.0"])
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["JDK"].status is Status.FAIL

    def test_no_ndk_fails(self, tmp_path):
        probe = FakeProbe(
            which={"java": "/j"}, sdk=tmp_path, ndk=[], build_tools=["35.0.0"]
        )
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["NDK"].status is Status.FAIL
        assert "every" in by["NDK"].detail.lower()

    def test_no_sdk_fails(self, tmp_path):
        probe = FakeProbe(which={"java": "/j"}, sdk=None)
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["Android SDK"].status is Status.FAIL
        assert by["NDK"].status is Status.SKIP

    def test_no_avd_warns(self, tmp_path):
        probe = _healthy_probe(tmp_path)
        probe._avds = []
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["Emulator / virtualization"].status is Status.WARN

    def test_no_acceleration_warns(self, tmp_path):
        probe = _healthy_probe(tmp_path)
        probe._accel = False
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["Emulator / virtualization"].status is Status.WARN
        assert "acceleration" in by["Emulator / virtualization"].detail

    def test_no_build_tools_fails(self, tmp_path):
        probe = FakeProbe(
            which={"java": "/j"}, sdk=tmp_path, ndk=["27"], build_tools=[]
        )
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["Build-tools / platform"].status is Status.FAIL
        assert "no build-tools" in by["Build-tools / platform"].detail

    def test_adb_found_via_sdk_platform_tools_file(self, tmp_path):
        exe = ".exe" if os.name == "nt" else ""
        adb_path = tmp_path / "platform-tools" / f"adb{exe}"
        adb_path.parent.mkdir(parents=True)
        adb_path.write_bytes(b"x")
        probe = FakeProbe(
            which={"java": "/j"}, sdk=tmp_path, ndk=["27"], build_tools=["35.0.0"]
        )
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["adb"].status is Status.PASS
        assert by["adb"].detail.startswith(str(adb_path))

    def test_adb_without_a_device_warns(self, tmp_path):
        """`run` and `run --smoke` need something attached, so an adb with no
        devices is a real gap, not a pass."""
        probe = FakeProbe(
            which={"java": "/j", "adb": "/sdk/adb"},
            sdk=tmp_path,
            ndk=["27"],
            build_tools=["35.0.0"],
            devices=[],
        )
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["adb"].status is Status.WARN
        assert "no device or emulator" in by["adb"].detail

    def test_unaccepted_sdk_licenses_warn(self, tmp_path):
        probe = FakeProbe(
            which={"java": "/j"},
            sdk=tmp_path,
            ndk=["27"],
            build_tools=["35.0.0"],
            licenses=[],
        )
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["SDK licenses"].status is Status.WARN
        assert "sdkmanager --licenses" in by["SDK licenses"].hint

    def test_newer_kivyforge_on_pypi_warns(self, tmp_path):
        probe = FakeProbe(
            which={"java": "/j"},
            sdk=tmp_path,
            ndk=["27"],
            build_tools=["35.0.0"],
            latest="9.9.9",
        )
        by = _by_name(
            android_doctor(
                tmp_path, kivyforge_version="1.0.0", offline=False, probe=probe
            )
        )
        assert by["kivyforge"].status is Status.WARN
        assert "9.9.9" in by["kivyforge"].detail

    def test_offline_skips_the_pypi_lookup(self, tmp_path):
        probe = FakeProbe(
            which={"java": "/j"},
            sdk=tmp_path,
            ndk=["27"],
            build_tools=["35.0.0"],
            latest="9.9.9",
        )
        by = _by_name(
            android_doctor(
                tmp_path, kivyforge_version="1.0.0", offline=True, probe=probe
            )
        )
        assert by["kivyforge"].status is Status.PASS
        assert "offline" in by["kivyforge"].detail


class TestSdkCheck:
    def test_pass_when_cmdline_tools_present(self, tmp_path):
        bat = ".bat" if os.name == "nt" else ""
        sdkmanager = tmp_path / "cmdline-tools" / "latest" / "bin" / f"sdkmanager{bat}"
        sdkmanager.parent.mkdir(parents=True)
        sdkmanager.write_bytes(b"x")
        assert _check_sdk(tmp_path).status is Status.PASS

    def test_warn_when_cmdline_tools_missing(self, tmp_path):
        result = _check_sdk(tmp_path)
        assert result.status is Status.WARN
        assert "cmdline-tools" in result.detail

    def test_fail_when_no_sdk(self):
        assert _check_sdk(None).status is Status.FAIL


class TestBuildToolsCheckDirect:
    def test_skip_when_no_sdk(self):
        assert _check_build_tools(FakeProbe(), None, None).status is Status.SKIP


class TestRealAndroidProbe:
    def test_java_home_from_env_when_java_binary_exists(self, tmp_path, monkeypatch):
        exe = ".exe" if os.name == "nt" else ""
        jdk = tmp_path / "jdk"
        (jdk / "bin").mkdir(parents=True)
        (jdk / "bin" / f"java{exe}").write_bytes(b"x")
        monkeypatch.setenv("JAVA_HOME", str(jdk))
        assert RealAndroidProbe().java_home() == str(jdk)

    def test_java_home_none_when_binary_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JAVA_HOME", str(tmp_path / "nope"))
        assert RealAndroidProbe().java_home() is None

    def test_java_home_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("JAVA_HOME", raising=False)
        assert RealAndroidProbe().java_home() is None

    def test_sdk_root_from_android_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
        monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
        assert RealAndroidProbe().sdk_root() == tmp_path

    def test_sdk_root_falls_back_to_conventional_location(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANDROID_HOME", raising=False)
        monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
        if os.name == "nt":
            monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
            sdk = tmp_path / "Android" / "Sdk"
        else:
            monkeypatch.setattr(Path, "home", lambda: tmp_path)
            sdk = tmp_path / "Android" / "Sdk"
        sdk.mkdir(parents=True)
        assert RealAndroidProbe().sdk_root() == sdk

    def test_sdk_root_none_when_nothing_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANDROID_HOME", raising=False)
        monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
        if os.name == "nt":
            monkeypatch.delenv("LOCALAPPDATA", raising=False)
        else:
            monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert RealAndroidProbe().sdk_root() is None

    def test_ndk_versions_lists_sorted_dirs(self, tmp_path):
        (tmp_path / "ndk" / "27.3.1").mkdir(parents=True)
        (tmp_path / "ndk" / "26.1.0").mkdir(parents=True)
        assert RealAndroidProbe().ndk_versions(tmp_path) == ["26.1.0", "27.3.1"]

    def test_ndk_versions_empty_when_absent(self, tmp_path):
        assert RealAndroidProbe().ndk_versions(tmp_path) == []

    def test_build_tools_versions_lists_sorted_dirs(self, tmp_path):
        (tmp_path / "build-tools" / "35.0.0").mkdir(parents=True)
        assert RealAndroidProbe().build_tools_versions(tmp_path) == ["35.0.0"]

    def test_build_tools_versions_empty_when_absent(self, tmp_path):
        assert RealAndroidProbe().build_tools_versions(tmp_path) == []

    def test_platform_installed(self, tmp_path):
        (tmp_path / "platforms" / "android-35").mkdir(parents=True)
        assert RealAndroidProbe().platform_installed(tmp_path, 35)
        assert not RealAndroidProbe().platform_installed(tmp_path, 34)

    def test_avds_swallows_errors(self, monkeypatch):
        import kivyforge.platforms.android.adb as adb_mod

        def boom():
            raise RuntimeError("no emulator tool on PATH")

        monkeypatch.setattr(adb_mod, "available_avds", boom)
        assert RealAndroidProbe().avds() == []

    def test_has_kvm_or_haxm_returns_bool(self):
        assert isinstance(RealAndroidProbe().has_kvm_or_haxm(), bool)

    def test_tcp_reachable_false_for_closed_port(self):
        # Port 1 on the loopback address should refuse/time out immediately.
        assert RealAndroidProbe().tcp_reachable("127.0.0.1", 1) is False


class TestProjectChecks:
    def _project(self, tmp_path, *, compile_sdk=35):
        (tmp_path / "src").mkdir(exist_ok=True)
        # target_sdk tracks compile_sdk so the config itself stays valid
        # (compile_sdk >= target_sdk); the check under test is the *platform*
        # install, not config validity.
        (tmp_path / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "app"',
                    'version = "1.0.0"',
                    'dependencies = ["kivy==2.3.1", "pyjnius"]',
                    "[tool.kivy]",
                    'app_dir = "src"',
                    "[tool.kivy.android]",
                    "schema_version = 1",
                    'package = "org.real.app"',
                    f"target_sdk = {compile_sdk}",
                    f"compile_sdk = {compile_sdk}",
                    "[tool.kivy.android.python]",
                    'version = "3.14.6"',
                ]
            ),
            encoding="utf-8",
        )

    def test_config_and_app_source(self, tmp_path):
        self._project(tmp_path)
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["Android config"].status is Status.PASS
        assert by["App source directory"].status is Status.PASS
        assert by["Lock"].status is Status.WARN  # no lock yet

    def test_icon_and_splash_skip_when_unconfigured(self, tmp_path):
        self._project(tmp_path)
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["App icon"].status is Status.SKIP
        assert by["Splash assets"].status is Status.SKIP

    def test_manifest_policy_and_implied_features_run_without_a_build(self, tmp_path):
        """Both read only the config, so they are the preflight's cheapest half."""
        self._project(tmp_path)
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["Manifest policy (release)"].status is Status.PASS
        assert by["Implied features"].status is Status.PASS
        assert by["App-local native binaries"].status is Status.PASS
        assert by["find_links directories"].status is Status.SKIP
        # No generated project yet, so the wrapper cannot be judged.
        assert by["Gradle wrapper"].status is Status.SKIP

    def test_placeholder_package_fails_the_manifest_policy(self, tmp_path):
        self._project(tmp_path)
        text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            text.replace('package = "org.real.app"', 'package = "org.example.app"'),
            encoding="utf-8",
        )
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        policy = by["Manifest policy (release)"]
        assert policy.status is Status.FAIL
        assert "placeholder" in policy.detail

    def test_native_binary_in_app_dir_fails(self, tmp_path):
        self._project(tmp_path)
        (tmp_path / "src" / "vendor").mkdir()
        (tmp_path / "src" / "vendor" / "_fast.so").write_bytes(b"not an elf")
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        native = by["App-local native binaries"]
        assert native.status is Status.FAIL
        assert "src/vendor/_fast.so" in native.detail
        assert "jniLibs" in native.hint

    def test_compile_sdk_platform_missing_fails(self, tmp_path):
        self._project(tmp_path, compile_sdk=34)
        probe = _healthy_probe(tmp_path)  # only android-35 installed
        by = _by_name(
            android_doctor(tmp_path, kivyforge_version="0", offline=True, probe=probe)
        )
        assert by["Build-tools / platform"].status is Status.FAIL

    def test_invalid_config_fails_fast(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "app"',
                    'version = "1.0.0"',
                    "[tool.kivy]",
                    'app_dir = "src"',
                    "[tool.kivy.android]",
                    "schema_version = 1",
                    'package = "nodots"',
                ]
            ),
            encoding="utf-8",
        )
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["Android config"].status is Status.FAIL


_PROJECT_PYPROJECT = """\
[project]
name = "doctorapp"
version = "1.0.0"
dependencies = ["kivy==2.3.1", "pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.example.doctorapp"
abis = ["arm64_v8a", "x86_64"]

[tool.kivy.android.python]
version = "3.14.6"
"""


def _config(text=_PROJECT_PYPROJECT):
    return load_config_from_text(text, require_ios=False, require_android=True)


def _wheel_pkg(name, version, *, abis=("arm64_v8a", "x86_64"), api=24):
    wheels = tuple(
        LockedWheel(
            name=f"{name}-{version}-cp314-cp314-android_{api}_{abi}.whl",
            url=f"https://files.example/{name}-{abi}.whl",
            sha256="a" * 64,
        )
        for abi in abis
    )
    return LockedPackage(name=name, version=version, wheels=wheels)


def _doctor_lock(*, packages=(), vendored=False, include_files=()):
    if vendored:
        runtime = PythonAndroidRuntime(
            version="3.14.6",
            abi="arm64_v8a",
            path="vendor/py.tar.gz",
            sha256="b" * 64,
            min_api=24,
        )
    else:
        runtime = PythonAndroidRuntime(
            version="3.14.6",
            abi="arm64_v8a",
            url="https://example.org/py.tar.gz",
            sha256="b" * 64,
            min_api=24,
        )
    return AndroidLockfile(
        requires_python=">=3.14",
        packages=tuple(packages),
        python_android=(runtime,),
        include_files=tuple(include_files),
        kivyforge_version="3.0.0",
        generated_at="2026-01-01T00:00:00Z",
        pyproject_sha256="0" * 64,
        tool_kivy_android_schema_version=1,
        kivy_generation=2,
    )


class TestSdlKivyMatchDirect:
    def test_skip_when_kivy_not_locked(self):
        result = _check_sdl_kivy_match(_config(), _doctor_lock())
        assert result.status is Status.SKIP

    def test_pass_when_matching(self):
        lock = _doctor_lock(packages=[_wheel_pkg("kivy", "2.3.1")])
        assert _check_sdl_kivy_match(_config(), lock).status is Status.PASS

    def test_warn_on_sdl_generation_mismatch(self):
        lock = _doctor_lock(packages=[_wheel_pkg("kivy", "3.0.0")])
        result = _check_sdl_kivy_match(_config(), lock)
        assert result.status is Status.WARN
        assert "kivy_generation = 3" in result.hint

    def test_warn_on_unparseable_kivy_version(self):
        lock = _doctor_lock(packages=[_wheel_pkg("kivy", "not-a-version")])
        result = _check_sdl_kivy_match(_config(), lock)
        assert result.status is Status.WARN
        assert "unparseable" in result.detail

    def test_pass_on_kivy_3_dev_prerelease(self):
        # Version("3.0.0.devN") < Version("3.0") under PEP 440 dev-release
        # ordering, so a naive `>=` comparison would misclassify every Kivy
        # 3.0 dev build as SDL2 and false-WARN here.
        text = _PROJECT_PYPROJECT.replace(
            'dependencies = ["kivy==2.3.1", "pyjnius"]',
            'dependencies = ["kivy>=3.0.0.dev0", "pyjnius"]',
        ).replace(
            'abis = ["arm64_v8a", "x86_64"]',
            'abis = ["arm64_v8a", "x86_64"]\nkivy_generation = 3',
        )
        config = _config(text)
        lock = _doctor_lock(packages=[_wheel_pkg("kivy", "3.0.0.dev202606221936")])
        assert _check_sdl_kivy_match(config, lock).status is Status.PASS


class TestPyjniusContractDirect:
    def test_skip_when_absent(self):
        assert _check_pyjnius_contract(_doctor_lock()).status is Status.SKIP

    def test_pass_when_in_range(self):
        lock = _doctor_lock(packages=[_wheel_pkg("pyjnius", "1.7.0")])
        assert _check_pyjnius_contract(lock).status is Status.PASS

    def test_fail_when_out_of_range(self):
        lock = _doctor_lock(packages=[_wheel_pkg("pyjnius", "2.0.0")])
        result = _check_pyjnius_contract(lock)
        assert result.status is Status.FAIL
        assert "invoke0" in result.detail


class TestAbiCoverageDirect:
    def test_pass_when_all_abis_covered(self):
        lock = _doctor_lock(packages=[_wheel_pkg("pyjnius", "1.7.0")])
        assert _check_abi_coverage(_config(), lock).status is Status.PASS

    def test_fail_when_an_abi_slice_missing(self):
        lock = _doctor_lock(
            packages=[_wheel_pkg("pyjnius", "1.7.0", abis=("arm64_v8a",))]
        )
        result = _check_abi_coverage(_config(), lock)
        assert result.status is Status.FAIL
        assert "x86_64" in result.detail


class TestSplashCheckDirect:
    """A splash typo should surface in doctor, not as an AAPT failure."""

    def _config_with(self, extra: str):
        return _config(_PROJECT_PYPROJECT + extra)

    def _png(self, path: Path, *, size=(64, 64)):
        from kivyforge.platforms.android.icons import default_icon_png

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(default_icon_png(size[0], (1, 2, 3, 255)))

    def test_skip_when_unconfigured(self, tmp_path):
        assert _check_splash(_config(), tmp_path).status is Status.SKIP

    def test_fail_when_source_missing(self, tmp_path):
        config = self._config_with(
            "\n[tool.kivy.android.splash]\nsource = 'assets/splash.png'\n"
        )
        result = _check_splash(config, tmp_path)
        assert result.status is Status.FAIL
        assert "not found" in result.detail

    def test_pass_for_a_valid_png(self, tmp_path):
        self._png(tmp_path / "splash.png")
        config = self._config_with(
            "\n[tool.kivy.android.splash]\nsource = 'splash.png'\n"
        )
        assert _check_splash(config, tmp_path).status is Status.PASS

    def test_fail_for_a_source_that_is_not_a_png(self, tmp_path):
        (tmp_path / "splash.png").write_bytes(b"not a png")
        config = self._config_with(
            "\n[tool.kivy.android.splash]\nsource = 'splash.png'\n"
        )
        assert _check_splash(config, tmp_path).status is Status.FAIL

    def test_fail_for_xml_that_is_not_a_drawable(self, tmp_path):
        (tmp_path / "splash.xml").write_text("<resources/>", encoding="utf-8")
        config = self._config_with(
            "\n[tool.kivy.android.splash]\nsource = 'splash.xml'\n"
        )
        assert _check_splash(config, tmp_path).status is Status.FAIL

    def test_pass_for_an_animated_vector(self, tmp_path):
        (tmp_path / "splash.xml").write_text(
            '<animated-vector xmlns:android="x"/>', encoding="utf-8"
        )
        config = self._config_with(
            "\n[tool.kivy.android.splash]\n"
            "source = 'splash.xml'\nanimation_duration = 700\n"
        )
        assert _check_splash(config, tmp_path).status is Status.PASS

    def test_warn_when_duration_cannot_apply(self, tmp_path):
        self._png(tmp_path / "splash.png")
        config = self._config_with(
            "\n[tool.kivy.android.splash]\n"
            "source = 'splash.png'\nanimation_duration = 700\n"
        )
        result = _check_splash(config, tmp_path)
        assert result.status is Status.WARN
        assert "ignored" in result.detail

    def test_fail_when_branding_missing(self, tmp_path):
        self._png(tmp_path / "splash.png")
        config = self._config_with(
            "\n[tool.kivy.android.splash]\n"
            "source = 'splash.png'\nbranding = 'brand.png'\n"
        )
        assert _check_splash(config, tmp_path).status is Status.FAIL


class TestIconCheckDirect:
    def test_skip_when_unconfigured(self, tmp_path):
        assert _check_icon(_config(), tmp_path).status is Status.SKIP

    def test_fail_when_source_missing(self, tmp_path):
        config = _config(
            _PROJECT_PYPROJECT + "\n[tool.kivy.android.icons]\nsource = 'icon.png'\n"
        )
        assert _check_icon(config, tmp_path).status is Status.FAIL

    def test_fail_when_wrong_size(self, tmp_path):
        from kivyforge.platforms.android.icons import default_icon_png

        (tmp_path / "icon.png").write_bytes(default_icon_png(64, (1, 2, 3, 255)))
        config = _config(
            _PROJECT_PYPROJECT + "\n[tool.kivy.android.icons]\nsource = 'icon.png'\n"
        )
        result = _check_icon(config, tmp_path)
        assert result.status is Status.FAIL
        assert "64x64" in result.detail

    def test_pass_and_layer_paths_checked(self, tmp_path):
        from kivyforge.platforms.android.icons import default_icon_png

        (tmp_path / "icon.png").write_bytes(default_icon_png(1024, (1, 2, 3, 255)))
        base = _PROJECT_PYPROJECT + "\n[tool.kivy.android.icons]\nsource = 'icon.png'\n"
        assert _check_icon(_config(base), tmp_path).status is Status.PASS
        # A hex background is a color, not a path.
        assert (
            _check_icon(_config(base + "background = '#ffffff'\n"), tmp_path).status
            is Status.PASS
        )
        assert (
            _check_icon(_config(base + "background = 'bg.png'\n"), tmp_path).status
            is Status.FAIL
        )


class TestIncludeFilesCheckDirect:
    """Drift is a warning here and a build failure later, so doctor is where a
    user finds out before Gradle time."""

    def _setup(self, tmp_path, *, content=b"hi"):
        (tmp_path / "extra").mkdir(exist_ok=True)
        (tmp_path / "extra" / "data.txt").write_bytes(content)
        config = _config(
            _PROJECT_PYPROJECT + "\n[[tool.kivy.android.include_files]]\n"
            'dest = "app/src/main/assets/extra"\n'
            'sources = ["extra"]\n'
        )
        return config

    def _lock_with(self, pins):
        return _doctor_lock(include_files=pins)

    def test_skip_when_unconfigured(self, tmp_path):
        result = _check_include_files(_config(), tmp_path, _doctor_lock())
        assert result.status is Status.SKIP

    def test_pass_when_hashes_match(self, tmp_path):
        from kivyforge.artifacts.verify import sha256_file

        config = self._setup(tmp_path)
        pins = (
            LockedIncludeFile(
                source="extra/data.txt",
                dest="app/src/main/assets/extra",
                sha256=sha256_file(tmp_path / "extra" / "data.txt"),
            ),
        )
        result = _check_include_files(config, tmp_path, self._lock_with(pins))
        assert result.status is Status.PASS

    def test_warn_on_changed_content(self, tmp_path):
        config = self._setup(tmp_path)
        pins = (
            LockedIncludeFile(
                source="extra/data.txt",
                dest="app/src/main/assets/extra",
                sha256="c" * 64,
            ),
        )
        result = _check_include_files(config, tmp_path, self._lock_with(pins))
        assert result.status is Status.WARN
        assert "changed" in result.detail

    def test_warn_on_an_unlocked_file(self, tmp_path):
        config = self._setup(tmp_path)
        result = _check_include_files(config, tmp_path, self._lock_with(()))
        assert result.status is Status.WARN
        assert "not in the lock" in result.detail

    def test_warn_on_a_deleted_file(self, tmp_path):
        from kivyforge.artifacts.verify import sha256_file

        config = self._setup(tmp_path)
        pins = (
            LockedIncludeFile(
                source="extra/data.txt",
                dest="app/src/main/assets/extra",
                sha256=sha256_file(tmp_path / "extra" / "data.txt"),
            ),
            LockedIncludeFile(
                source="extra/gone.txt",
                dest="app/src/main/assets/extra",
                sha256="d" * 64,
            ),
        )
        result = _check_include_files(config, tmp_path, self._lock_with(pins))
        assert result.status is Status.WARN
        assert "deleted" in result.detail


class TestSigningCheckDirect:
    def test_skip_when_unconfigured(self, tmp_path):
        assert _check_signing(_config(), tmp_path).status is Status.SKIP

    def test_fail_when_keystore_missing(self, tmp_path):
        text = _PROJECT_PYPROJECT + (
            "\n[tool.kivy.android.signing]\n"
            'keystore = "release.keystore"\n'
            'key_alias = "upload"\n'
        )
        result = _check_signing(_config(text), tmp_path)
        assert result.status is Status.FAIL

    def test_pass_when_signing_resolves(self, tmp_path, monkeypatch):
        text = _PROJECT_PYPROJECT + (
            "\n[tool.kivy.android.signing]\n"
            'keystore = "release.keystore"\n'
            'key_alias = "upload"\n'
        )
        from kivyforge.platforms.android import signing as signing_mod

        monkeypatch.setattr(signing_mod, "resolve_signing", lambda *a, **k: object())
        result = _check_signing(_config(text), tmp_path)
        assert result.status is Status.PASS


class TestLockHostsDirect:
    def test_skip_when_fully_vendored(self):
        lock = _doctor_lock(vendored=True)
        assert _check_lock_hosts(FakeProbe(), lock).status is Status.SKIP

    def test_pass_when_reachable(self):
        lock = _doctor_lock(packages=[_wheel_pkg("pyjnius", "1.7.0")])
        assert _check_lock_hosts(FakeProbe(reachable=True), lock).status is Status.PASS

    def test_warn_when_unreachable(self):
        lock = _doctor_lock(packages=[_wheel_pkg("pyjnius", "1.7.0")])
        result = _check_lock_hosts(FakeProbe(reachable=False), lock)
        assert result.status is Status.WARN


class TestAlignmentCheckDirect:
    def test_skip_when_no_jnilibs_staged(self, tmp_path):
        assert _check_16k_alignment(tmp_path).status is Status.SKIP

    def test_pass_when_aligned(self, tmp_path):
        jni = tmp_path / "app" / "src" / "main" / "jniLibs" / "arm64-v8a"
        jni.mkdir(parents=True)
        (jni / "good.so").write_bytes(_make_elf(PAGE_16K))
        assert _check_16k_alignment(tmp_path).status is Status.PASS

    def test_fail_when_misaligned(self, tmp_path):
        jni = tmp_path / "app" / "src" / "main" / "jniLibs" / "arm64-v8a"
        jni.mkdir(parents=True)
        (jni / "bad.so").write_bytes(_make_elf(0x1000))
        assert _check_16k_alignment(tmp_path).status is Status.FAIL


class TestGradleWrapperCheckDirect:
    def _wrapper(self, project: Path, version: str) -> None:
        project.mkdir(parents=True, exist_ok=True)
        (project / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
        (project / "gradlew.bat").write_text("@echo off\n", encoding="utf-8")
        props = project / "gradle" / "wrapper"
        props.mkdir(parents=True)
        (props / "gradle-wrapper.properties").write_text(
            "distributionUrl=https\\://services.gradle.org/distributions/"
            f"gradle-{version}-bin.zip\n",
            encoding="utf-8",
        )

    def test_skip_before_the_project_is_generated(self, tmp_path):
        assert _check_gradle_wrapper(tmp_path / "nope").status is Status.SKIP

    def test_pass_on_the_pinned_version(self, tmp_path):
        from kivyforge.platforms.android import toolchain

        self._wrapper(tmp_path / "p", toolchain.GRADLE_VERSION)
        result = _check_gradle_wrapper(tmp_path / "p")
        assert result.status is Status.PASS
        assert toolchain.GRADLE_VERSION in result.detail

    def test_warn_when_the_distribution_drifted(self, tmp_path):
        self._wrapper(tmp_path / "p", "7.0")
        result = _check_gradle_wrapper(tmp_path / "p")
        assert result.status is Status.WARN
        assert "pinned Gradle" in result.detail

    def test_fail_when_a_wrapper_piece_is_missing(self, tmp_path):
        from kivyforge.platforms.android import toolchain

        self._wrapper(tmp_path / "p", toolchain.GRADLE_VERSION)
        (tmp_path / "p" / "gradle" / "wrapper" / "gradle-wrapper.properties").unlink()
        result = _check_gradle_wrapper(tmp_path / "p")
        assert result.status is Status.FAIL
        assert "gradle-wrapper.properties" in result.detail


class TestFindLinksCheckDirect:
    def _config(self, tmp_path, entries):
        links = ", ".join(f'"{e}"' for e in entries)
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "pyproject.toml").write_text(
            "\n".join(
                [
                    "[project]",
                    'name = "app"',
                    'version = "1.0.0"',
                    'dependencies = ["kivy==2.3.1", "pyjnius"]',
                    "[tool.kivy]",
                    'app_dir = "src"',
                    "[tool.kivy.android]",
                    "schema_version = 1",
                    'package = "org.real.app"',
                    f"find_links = [{links}]",
                    "[tool.kivy.android.python]",
                    'version = "3.14.6"',
                ]
            ),
            encoding="utf-8",
        )
        return load_config(
            tmp_path / "pyproject.toml", require_ios=False, require_android=True
        )

    def test_fail_when_the_directory_is_gone(self, tmp_path):
        config = self._config(tmp_path, ["wheels"])
        result = _check_find_links(config, tmp_path)
        assert result.status is Status.FAIL
        assert "missing" in result.detail

    def test_warn_when_the_directory_holds_no_wheels(self, tmp_path):
        config = self._config(tmp_path, ["wheels"])
        (tmp_path / "wheels").mkdir()
        result = _check_find_links(config, tmp_path)
        assert result.status is Status.WARN
        assert "no .whl" in result.detail

    def test_pass_when_wheels_are_present(self, tmp_path):
        config = self._config(tmp_path, ["wheels"])
        (tmp_path / "wheels").mkdir()
        (tmp_path / "wheels" / "x-1.0-py3-none-any.whl").write_bytes(b"PK")
        result = _check_find_links(config, tmp_path)
        assert result.status is Status.PASS
        assert "1 wheel(s)" in result.detail


class TestAndroidDoctorWithLock:
    """Full ``android_doctor`` flow once a lock (and generated project) exist."""

    def _project(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "pyproject.toml").write_text(_PROJECT_PYPROJECT, encoding="utf-8")

    def test_lock_checks_run_and_project_dir_alignment(self, tmp_path):
        from kivyforge.platforms.android.lock import writer as lock_writer

        self._project(tmp_path)
        lock = _doctor_lock(
            packages=[_wheel_pkg("kivy", "2.3.1"), _wheel_pkg("pyjnius", "1.7.0")]
        )
        (tmp_path / "pylock.android.toml").write_text(
            lock_writer.dumps(lock), encoding="utf-8"
        )
        # A previously-generated project with a staged, aligned .so.
        jni = (
            tmp_path
            / "doctorapp-android"
            / "app"
            / "src"
            / "main"
            / "jniLibs"
            / "arm64-v8a"
        )
        jni.mkdir(parents=True)
        (jni / "good.so").write_bytes(_make_elf(PAGE_16K))

        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["SDL / Kivy match"].status is Status.PASS
        assert by["pyjnius / bootstrap match"].status is Status.PASS
        assert by["ABI coverage"].status is Status.PASS
        assert by["16 KB alignment"].status is Status.PASS
        assert "Required hosts reachable" not in by  # offline=True skips it

    def test_unreadable_lock_stops_early(self, tmp_path):
        self._project(tmp_path)
        (tmp_path / "pylock.android.toml").write_text("{{ not toml", encoding="utf-8")
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=True,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["Lock"].status is Status.FAIL
        assert "unreadable" in by["Lock"].detail

    def test_online_checks_reachable_hosts(self, tmp_path):
        from kivyforge.platforms.android.lock import writer as lock_writer

        self._project(tmp_path)
        lock = _doctor_lock(packages=[_wheel_pkg("pyjnius", "1.7.0")])
        (tmp_path / "pylock.android.toml").write_text(
            lock_writer.dumps(lock), encoding="utf-8"
        )
        by = _by_name(
            android_doctor(
                tmp_path,
                kivyforge_version="0",
                offline=False,
                probe=_healthy_probe(tmp_path),
            )
        )
        assert by["Required hosts reachable"].status is Status.PASS


def _make_elf(align: int, *, is64=True) -> bytes:
    """A minimal ELF with one PT_LOAD segment at the given p_align."""
    e_phoff = 64 if is64 else 52
    phentsize = 56 if is64 else 32
    buf = bytearray(e_phoff + phentsize)
    buf[:4] = b"\x7fELF"
    buf[4] = 2 if is64 else 1  # class
    buf[5] = 1  # little-endian
    if is64:
        struct.pack_into("<Q", buf, 0x20, e_phoff)  # e_phoff
        struct.pack_into("<H", buf, 0x36, phentsize)
        struct.pack_into("<H", buf, 0x38, 1)  # e_phnum
        off = e_phoff
        struct.pack_into("<I", buf, off, 1)  # PT_LOAD
        struct.pack_into("<Q", buf, off + 0x30, align)  # p_align
    return bytes(buf)


class TestElf:
    def test_16k_aligned(self, tmp_path):
        so = tmp_path / "good.so"
        so.write_bytes(_make_elf(PAGE_16K))
        info = read_elf(so)
        assert info.is_16k_aligned

    def test_4k_flagged(self, tmp_path):
        so = tmp_path / "bad.so"
        so.write_bytes(_make_elf(0x1000))
        info = read_elf(so)
        assert not info.is_16k_aligned
        assert info.max_load_align == 0x1000

    def test_not_elf_raises(self, tmp_path):
        f = tmp_path / "x.so"
        f.write_bytes(b"not an elf at all, just text padding here to be long enough..")
        with pytest.raises(ElfError):
            read_elf(f)

    def test_scan_finds_bad(self, tmp_path):
        (tmp_path / "arm64-v8a").mkdir()
        (tmp_path / "arm64-v8a" / "good.so").write_bytes(_make_elf(PAGE_16K))
        (tmp_path / "arm64-v8a" / "bad.so").write_bytes(_make_elf(0x1000))
        bad = scan_alignment(tmp_path)
        assert [p.name for p, _ in bad] == ["bad.so"]
