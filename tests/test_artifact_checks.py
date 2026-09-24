"""The T3 artifact checks, against synthetic APKs and ``.app`` bundles.

Hermetic on purpose: a checker that only runs when a real build exists cannot be
trusted to fail correctly, and the whole point of it is to fail when something
is wrong. Each Android test builds the smallest zip that expresses one fault;
each macOS and Linux test builds the smallest directory tree that does the
same.

Magic 3627 is CPython 3.14's, and 3621 is 3.14.0a7's — the actual pair from
roadmap item 1, where the alpha's bytecode looked fine and was unimportable.
3571 is 3.13's, which is what the desktop examples ship: the Linux tests use
the 3571/3627 pair because that is the real mismatch a Linux build hits, the
AppDir compiling its payload with its own staged 3.13 while pytest runs under
3.14.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import struct
import zipfile
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.config.model import (
    AndroidActivity,
    AndroidConfig,
    AndroidFeature,
    AndroidIconConfig,
    AndroidIntentFilter,
    AndroidManifestConfig,
    AndroidPermissions,
    AndroidService,
)
from kivyforge.platforms.android.elf import EM_AARCH64, EM_X86_64
from kivyforge.platforms.android.generate.manifest import (
    ANDROID_NS,
    GENERATED_THEME,
    MAIN_ACTIVITY,
    ManifestError,
    generate_manifest,
)
from kivyforge.platforms.linux.elftools import ELFCLASS32
from kivyforge.platforms.macos.machotools import CPU_TYPE_ARM64, CPU_TYPE_X86_64
from kivyforge.platforms.windows.petools import (
    IMAGE_FILE_MACHINE_AMD64,
    IMAGE_FILE_MACHINE_ARM64,
)
from tests.artifact_checks import (
    BUNDLE_ROOT,
    ELFCLASS64,
    android_apk_problems,
    android_manifest_problems,
    apksigner_report_problems,
    ios_app_problems,
    ios_expected_plist,
    linux_appdir_problems,
    linux_appimage_file_problems,
    macos_app_problems,
    macos_expected_plist,
    shipped_python_tags,
    shipped_python_tags_appdir,
    signtool_report_problems,
    windows_onedir_problems,
)

MAGIC_314 = struct.pack("<H", 3627) + b"\r\n"
MAGIC_314_ALPHA = struct.pack("<H", 3621) + b"\r\n"
MAGIC_313 = struct.pack("<H", 3571) + b"\r\n"


def _elf(machine: int, *, ei_class: int = ELFCLASS64) -> bytes:
    """A 64-byte ELF header — enough for the six bytes the checks look at."""
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = ei_class
    header[5] = 1  # ELFDATA2LSB
    struct.pack_into("<H", header, 18, machine)
    return bytes(header)


def _apk(tmp_path: Path, entries: dict[str, bytes], name: str = "app.apk") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for entry, payload in entries.items():
            zf.writestr(entry, payload)
    return path


def _stripped_entries(abi: str = "arm64-v8a") -> dict[str, bytes]:
    """A well-formed stripped APK: bytecode only, libs hoisted, right arch."""
    machine = EM_AARCH64 if abi == "arm64-v8a" else EM_X86_64
    return {
        f"lib/{abi}/libmain.so": _elf(machine),
        f"lib/{abi}/libpython3.14.so": _elf(machine),
        f"lib/{abi}/libpy._socket.so": _elf(machine),
        f"{BUNDLE_ROOT}app/main.pyc": MAGIC_314 + b"body",
        f"{BUNDLE_ROOT}stdlib/os.pyc": MAGIC_314 + b"body",
        f"{BUNDLE_ROOT}site-packages/kivy/__init__.pyc": MAGIC_314 + b"body",
        f"{BUNDLE_ROOT}VERSION": b"bf2eaad4cf839f30",
    }


def _check(tmp_path, entries, *, abi="arm64-v8a", stripped=True, magic=MAGIC_314):
    return android_apk_problems(
        _apk(tmp_path, entries),
        abi=abi,
        stripped=stripped,
        expected_magic=magic,
    )


class TestCleanArtifacts:
    def test_a_well_formed_stripped_apk_has_no_problems(self, tmp_path):
        assert _check(tmp_path, _stripped_entries()) == []

    def test_x86_64_is_checked_against_its_own_machine(self, tmp_path):
        entries = _stripped_entries("x86_64")
        assert _check(tmp_path, entries, abi="x86_64") == []

    def test_an_unstripped_apk_wants_source(self, tmp_path):
        entries = _stripped_entries()
        for name in [n for n in entries if n.endswith(".pyc")]:
            entries[name.removesuffix(".pyc") + ".py"] = b"x = 1\n"
            del entries[name]
        assert _check(tmp_path, entries, stripped=False) == []


class TestPayloadStripping:
    def test_a_leftover_source_file_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}site-packages/kivy/leftover.py"] = b"x = 1\n"
        problems = _check(tmp_path, entries)
        assert any("1 .py file(s) remain" in p for p in problems)

    def test_a_payload_with_no_bytecode_is_reported_as_degraded(self, tmp_path):
        entries = {
            k: v for k, v in _stripped_entries().items() if not k.endswith(".pyc")
        }
        entries[f"{BUNDLE_ROOT}app/main.py"] = b"x = 1\n"
        problems = _check(tmp_path, entries)
        assert any("degraded to shipping source" in p for p in problems)

    def test_pycache_defeats_sourceless_import(self, tmp_path):
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}site-packages/x/__pycache__/m.cpython-314.pyc"] = (
            MAGIC_314 + b"body"
        )
        problems = _check(tmp_path, entries)
        assert any("__pycache__" in p for p in problems)

    def test_a_missing_compiled_entry_point_is_reported(self, tmp_path):
        entries = _stripped_entries()
        del entries[f"{BUNDLE_ROOT}app/main.pyc"]
        problems = _check(tmp_path, entries)
        assert any("app/main.pyc is missing" in p for p in problems)

    def test_an_unstripped_build_missing_its_entry_point_is_reported(self, tmp_path):
        entries = {
            k: v for k, v in _stripped_entries().items() if not k.endswith(".pyc")
        }
        problems = _check(tmp_path, entries, stripped=False)
        assert any("app/main.py is missing" in p for p in problems)

    def test_a_shared_object_left_in_the_payload_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}site-packages/x/_speedup.so"] = _elf(EM_AARCH64)
        problems = _check(tmp_path, entries)
        assert any("left inside the payload" in p for p in problems)


class TestPycMagic:
    def test_bytecode_from_the_wrong_interpreter_is_reported(self, tmp_path):
        """Roadmap item 1's bug: a pre-release wrote unimportable bytecode."""
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}stdlib/os.pyc"] = MAGIC_314_ALPHA + b"body"
        problems = _check(tmp_path, entries)
        assert any("3621" in p and "3627" in p for p in problems)

    def test_the_magic_check_is_skipped_when_source_ships_alongside(self, tmp_path):
        """Unstripped, a stale .pyc is ignored by the import system, not fatal."""
        entries = _stripped_entries()
        entries[f"{BUNDLE_ROOT}stdlib/os.pyc"] = MAGIC_314_ALPHA + b"body"
        entries[f"{BUNDLE_ROOT}app/main.py"] = b"x = 1\n"
        problems = _check(tmp_path, entries, stripped=False)
        assert not any("3621" in p for p in problems)


class TestNativeLibraries:
    def test_a_host_binary_in_a_cross_build_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/arm64-v8a/libpy._socket.so"] = _elf(EM_X86_64)
        problems = _check(tmp_path, entries)
        assert any("x86_64" in p and "leaked into a" in p for p in problems)

    def test_a_second_abi_directory_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/x86_64/libmain.so"] = _elf(EM_X86_64)
        problems = _check(tmp_path, entries)
        assert any("unrequested ABI" in p for p in problems)

    def test_a_32_bit_library_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/arm64-v8a/libpy._socket.so"] = _elf(EM_AARCH64, ei_class=1)
        problems = _check(tmp_path, entries)
        assert any("32-bit" in p for p in problems)

    def test_a_non_elf_library_is_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/arm64-v8a/libpy._socket.so"] = b"not an elf at all"
        problems = _check(tmp_path, entries)
        assert any("is not an ELF file" in p for p in problems)


class TestShippedRuntime:
    def test_the_runtime_version_is_read_out_of_the_artifact(self, tmp_path):
        """The expected .pyc magic is anchored to what the APK actually ships."""
        assert shipped_python_tags(_apk(tmp_path, _stripped_entries())) == ["3.14"]

    def test_two_runtimes_are_reported(self, tmp_path):
        entries = _stripped_entries()
        entries["lib/arm64-v8a/libpython3.13.so"] = _elf(EM_AARCH64)
        assert shipped_python_tags(_apk(tmp_path, entries)) == ["3.13", "3.14"]
        assert any("ships 2 CPython runtimes" in p for p in _check(tmp_path, entries))

    def test_no_runtime_is_reported(self, tmp_path):
        entries = _stripped_entries()
        del entries["lib/arm64-v8a/libpython3.14.so"]
        problems = _check(tmp_path, entries)
        assert any("ships no runtime" in p for p in problems)


class TestRequiredEntries:
    def test_a_missing_launcher_is_reported(self, tmp_path):
        entries = _stripped_entries()
        del entries["lib/arm64-v8a/libmain.so"]
        problems = _check(tmp_path, entries)
        assert any("libmain.so is missing" in p for p in problems)

    def test_a_missing_bundle_is_reported(self, tmp_path):
        entries = {
            k: v
            for k, v in _stripped_entries().items()
            if not k.startswith(BUNDLE_ROOT)
        }
        problems = _check(tmp_path, entries)
        assert any(BUNDLE_ROOT in p and "missing" in p for p in problems)

    def test_an_unknown_abi_fails_fast(self, tmp_path):
        problems = _check(tmp_path, _stripped_entries(), abi="armeabi-v7a")
        assert problems == [
            "unknown ABI 'armeabi-v7a'; expected one of ['arm64-v8a', 'x86_64']"
        ]


# --- Android merged manifest ------------------------------------------------
#
# The fixture is deliberately *not* hand-written XML. It is the real generated
# manifest put through the transformations AGP's merge actually performs —
# ``package``/``versionCode``/``versionName`` injected onto ``<manifest>``,
# ``<uses-sdk>`` inserted, and a library's own components and permissions
# appended. Hand-written XML would let the fixture drift into a shape no merge
# produces, and the tolerate-the-extras behaviour (which is most of what makes
# this check usable against a real build) would go untested.
#
# The extras are copied from a real merged manifest of ``hello-android``:
# androidx.startup's InitializationProvider, profileinstaller's exported
# receiver, and the ``DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`` pair AGP
# synthesizes. Every one of them is absent from that project's pyproject.toml,
# so a check asserting set equality would fail on it.

_LIBRARY_PERMISSIONS = """
    <permission
        android:name="org.kivyforge.test.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
        android:protectionLevel="signature" />
    <uses-permission
        android:name="org.kivyforge.test.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION" />
"""

_LIBRARY_COMPONENTS = """
        <provider
            android:name="androidx.startup.InitializationProvider"
            android:authorities="org.kivyforge.test.androidx-startup"
            android:exported="false" />
        <receiver
            android:name="androidx.profileinstaller.ProfileInstallReceiver"
            android:exported="true"
            android:permission="android.permission.DUMP" />
"""


def _android(**overrides) -> AndroidConfig:
    base: dict[str, object] = {
        "schema_version": 1,
        "package": "org.kivyforge.test",
        "min_sdk": 24,
        "target_sdk": 35,
    }
    base.update(overrides)
    return AndroidConfig(**base)  # pyright: ignore[reportArgumentType]


def _merged(
    android: AndroidConfig,
    *,
    orientation: tuple[str, ...] = ("portrait",),
    version_name: str = "1.0.0",
    library_content: bool = True,
) -> str:
    """The generated manifest, transformed the way AGP's merge transforms it."""
    generated = generate_manifest(android, orientation=orientation)
    if library_content:
        generated = generated.replace(
            "    <application", _LIBRARY_PERMISSIONS + "    <application", 1
        )
        generated = generated.replace(
            "    </application>", _LIBRARY_COMPONENTS + "    </application>", 1
        )
    # AGP injects these four out of app/build.gradle's defaultConfig; the
    # generated manifest carries none of them.
    injected = (
        f'<manifest xmlns:android="{ANDROID_NS}"'
        f' package="{android.package}"'
        f' android:versionCode="{android.version_code}"'
        f' android:versionName="{version_name}">\n'
        f'    <uses-sdk android:minSdkVersion="{android.min_sdk}"'
        f' android:targetSdkVersion="{android.target_sdk}" />'
    )
    return generated.replace(f'<manifest xmlns:android="{ANDROID_NS}">', injected, 1)


def _mcheck(
    manifest_xml: str,
    android: AndroidConfig,
    *,
    orientation: tuple[str, ...] = ("portrait",),
    version_name: str = "1.0.0",
) -> list[str]:
    return android_manifest_problems(
        manifest_xml,
        android=android,
        orientation=orientation,
        version_name=version_name,
    )


class TestMergedManifestCleanArtifacts:
    def test_a_plain_merged_manifest_has_no_problems(self):
        android = _android(permissions=AndroidPermissions(uses=("INTERNET",)))
        assert _mcheck(_merged(android), android) == []

    def test_library_contributed_content_is_not_a_fault(self):
        """The check tolerates what it did not ask for; see the note above."""
        android = _android()
        with_extras = _merged(android, library_content=True)
        without = _merged(android, library_content=False)
        assert _mcheck(with_extras, android) == []
        assert _mcheck(without, android) == []

    def test_a_fully_featured_config_round_trips(self):
        android = _android(
            version_code=417,
            icons=AndroidIconConfig(source="icon.png"),
            permissions=AndroidPermissions(
                uses=("CAMERA", "INTERNET"),
                features=(AndroidFeature(name="android.hardware.nfc", required=True),),
            ),
            services=(
                AndroidService(
                    name="Sync",
                    entry_point="sync",
                    foreground=True,
                    foreground_service_type="dataSync",
                ),
            ),
            activities=(AndroidActivity(name="com.example.Second", exported=True),),
            intent_filters=(
                AndroidIntentFilter(
                    action="android.intent.action.VIEW",
                    categories=("android.intent.category.DEFAULT",),
                    data=({"scheme": "kivyforge", "host": "open"},),
                ),
            ),
            manifest=AndroidManifestConfig(
                application={"android:largeHeap": True},
                activity={"android:windowSoftInputMode": "adjustResize"},
            ),
        )
        orientation = ("landscape-left", "landscape-right")
        assert (
            _mcheck(
                _merged(android, orientation=orientation, version_name="2.4.1"),
                android,
                orientation=orientation,
                version_name="2.4.1",
            )
            == []
        )


class TestMergedManifestIdentity:
    """The four values AGP injects, which no generation test can cover."""

    def test_a_package_that_is_not_the_configured_one_is_reported(self):
        android = _android()
        bad = _merged(android).replace(
            'package="org.kivyforge.test"', 'package="org.example.app"'
        )
        assert any("package is 'org.example.app'" in p for p in _mcheck(bad, android))

    def test_a_wrong_version_code_is_reported(self):
        android = _android(version_code=9)
        bad = _merged(android).replace(
            'android:versionCode="9"', 'android:versionCode="1"'
        )
        assert any("versionCode" in p for p in _mcheck(bad, android))

    def test_a_wrong_version_name_is_reported(self):
        android = _android()
        problems = _mcheck(
            _merged(android, version_name="1.0.0"), android, version_name="2.0.0"
        )
        assert any("versionName" in p for p in problems)

    def test_a_lowered_min_sdk_is_reported(self):
        android = _android(min_sdk=24)
        bad = _merged(android).replace(
            'android:minSdkVersion="24"', 'android:minSdkVersion="21"'
        )
        assert any("minSdkVersion is '21'" in p for p in _mcheck(bad, android))

    def test_a_wrong_target_sdk_is_reported(self):
        android = _android(target_sdk=35)
        bad = _merged(android).replace(
            'android:targetSdkVersion="35"', 'android:targetSdkVersion="33"'
        )
        assert any("targetSdkVersion is '33'" in p for p in _mcheck(bad, android))

    def test_a_missing_uses_sdk_is_reported_rather_than_passing_silently(self):
        """The dangerous case: no <uses-sdk> means the check knows nothing."""
        android = _android()
        bad = re.sub(r"<uses-sdk[^>]*/>", "", _merged(android))
        assert any("no <uses-sdk>" in p for p in _mcheck(bad, android))


class TestMergedManifestPermissions:
    def test_a_dropped_permission_is_reported(self):
        android = _android(permissions=AndroidPermissions(uses=("INTERNET",)))
        bad = _merged(android).replace(
            '<uses-permission android:name="android.permission.INTERNET" />', ""
        )
        problems = _mcheck(bad, android)
        assert any("android.permission.INTERNET" in p for p in problems)

    def test_a_foreground_services_auto_added_pair_is_required_too(self):
        """The auto-adds are config's declarations as much as `uses` is."""
        android = _android(
            services=(
                AndroidService(
                    name="Sync",
                    entry_point="sync",
                    foreground=True,
                    foreground_service_type="dataSync",
                ),
            )
        )
        bad = _merged(android).replace(
            "<uses-permission "
            'android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" />',
            "",
        )
        problems = _mcheck(bad, android)
        assert any("FOREGROUND_SERVICE_DATA_SYNC" in p for p in problems)


class TestMergedManifestFeatures:
    def test_a_dropped_implied_feature_is_reported(self):
        android = _android(permissions=AndroidPermissions(uses=("NFC",)))
        bad = _merged(android).replace(
            '<uses-feature android:name="android.hardware.nfc" '
            'android:required="false" />',
            "",
        )
        assert any("android.hardware.nfc" in p for p in _mcheck(bad, android))

    def test_a_required_feature_downgraded_by_the_merge_is_reported(self):
        android = _android(
            permissions=AndroidPermissions(
                auto_features=False,
                features=(AndroidFeature(name="android.hardware.nfc", required=True),),
            )
        )
        bad = _merged(android).replace(
            'android:required="true"', 'android:required="false"'
        )
        problems = _mcheck(bad, android)
        assert any("but config declares it required" in p for p in problems)

    def test_a_feature_the_merge_strengthened_is_not_a_fault(self):
        """A library asking for `required=true` is the merger, not a defect.

        Only losing what the project declared is a fault; gaining a stronger
        requirement from a dependency is the merge working as designed, and
        flagging it would make the check fail on builds that are correct.
        """
        android = _android(
            permissions=AndroidPermissions(
                auto_features=False,
                features=(AndroidFeature(name="android.hardware.nfc", required=False),),
            )
        )
        stronger = _merged(android).replace(
            'android:required="false"', 'android:required="true"'
        )
        assert _mcheck(stronger, android) == []


class TestMergedManifestComponents:
    def _with_service(self, **service_kwargs) -> AndroidConfig:
        return _android(
            services=(
                AndroidService(name="Sync", entry_point="sync", **service_kwargs),
            )
        )

    def test_a_dropped_service_is_reported(self):
        android = self._with_service()
        bad = re.sub(r"<service[^>]*/>", "", _merged(android))
        problems = _mcheck(bad, android)
        assert any("declared service 'Sync' is missing" in p for p in problems)

    def test_a_service_whose_process_changed_is_reported(self):
        android = self._with_service()
        bad = _merged(android).replace(
            'android:process=":service_sync"', 'android:process=":other"'
        )
        assert any("android:process" in p for p in _mcheck(bad, android))

    def test_a_service_silently_exported_by_the_merge_is_reported(self):
        android = self._with_service(exported=False)
        bad = _merged(android).replace(
            'android:name="org.kivy.android.ServiceSync" '
            'android:process=":service_sync" android:exported="false"',
            'android:name="org.kivy.android.ServiceSync" '
            'android:process=":service_sync" android:exported="true"',
        )
        assert any("android:exported" in p for p in _mcheck(bad, android))

    def test_a_lost_foreground_service_type_is_reported(self):
        android = self._with_service(
            foreground=True, foreground_service_type="dataSync"
        )
        bad = _merged(android).replace('android:foregroundServiceType="dataSync"', "")
        assert any("foregroundServiceType" in p for p in _mcheck(bad, android))

    def test_a_dropped_extra_activity_is_reported(self):
        android = _android(activities=(AndroidActivity(name="com.example.Second"),))
        bad = _merged(android).replace(
            '<activity android:name="com.example.Second"',
            '<activity android:name="com.example.Gone"',
        )
        problems = _mcheck(bad, android)
        assert any("com.example.Second" in p and "missing" in p for p in problems)

    def test_an_extra_activity_exported_by_the_merge_is_reported(self):
        android = _android(
            activities=(AndroidActivity(name="com.example.Second", exported=False),)
        )
        bad = _merged(android).replace(
            '<activity android:name="com.example.Second" android:exported="false" />',
            '<activity android:name="com.example.Second" android:exported="true" />',
        )
        assert any("android:exported" in p for p in _mcheck(bad, android))


class TestMergedManifestMainActivity:
    def test_a_missing_launcher_activity_is_reported(self):
        android = _android()
        bad = _merged(android).replace(MAIN_ACTIVITY, "com.other.Activity")
        problems = _mcheck(bad, android)
        assert any("no <activity" in p and "no launcher" in p for p in problems)

    def test_an_orientation_the_merge_changed_is_reported(self):
        android = _android()
        bad = _merged(android).replace(
            'android:screenOrientation="portrait"',
            'android:screenOrientation="landscape"',
        )
        assert any("screenOrientation" in p for p in _mcheck(bad, android))

    def test_the_orientation_asserted_is_the_mapped_one_not_the_raw_config(self):
        """Three orientations map to `fullSensor`; the check must expect that."""
        android = _android()
        orientation = ("portrait", "landscape-left", "landscape-right")
        merged = _merged(android, orientation=orientation)
        assert 'android:screenOrientation="fullSensor"' in merged
        assert _mcheck(merged, android, orientation=orientation) == []

    def test_a_lost_generated_theme_is_reported(self):
        android = _android()
        bad = _merged(android).replace(f'android:theme="{GENERATED_THEME}"', "", 1)
        assert any("android:theme" in p for p in _mcheck(bad, android))

    def test_a_dropped_launcher_category_is_reported(self):
        android = _android()
        bad = _merged(android).replace(
            '<category android:name="android.intent.category.LAUNCHER" />', ""
        )
        assert any("LAUNCHER" in p for p in _mcheck(bad, android))


class TestMergedManifestIntentFilters:
    def _config(self, **kwargs) -> AndroidConfig:
        return _android(intent_filters=(AndroidIntentFilter(**kwargs),))

    def test_a_dropped_declared_filter_is_reported(self):
        android = self._config(
            action="android.intent.action.VIEW",
            categories=("android.intent.category.BROWSABLE",),
        )
        bad = _merged(android).replace(
            'android:name="android.intent.action.VIEW"',
            'android:name="android.intent.action.EDIT"',
        )
        problems = _mcheck(bad, android)
        assert any("android.intent.action.VIEW" in p for p in problems)

    def test_a_filter_that_lost_one_category_is_reported(self):
        android = self._config(
            action="android.intent.action.VIEW",
            categories=(
                "android.intent.category.DEFAULT",
                "android.intent.category.BROWSABLE",
            ),
        )
        bad = _merged(android).replace(
            '<category android:name="android.intent.category.BROWSABLE" />', ""
        )
        assert any("android.intent.action.VIEW" in p for p in _mcheck(bad, android))

    def test_a_filter_whose_deep_link_data_changed_is_reported(self):
        android = self._config(
            action="android.intent.action.VIEW",
            data=({"scheme": "kivyforge", "host": "open"},),
        )
        bad = _merged(android).replace(
            'android:host="open"', 'android:host="elsewhere"'
        )
        assert any("android.intent.action.VIEW" in p for p in _mcheck(bad, android))

    def test_a_category_the_merge_added_is_not_a_fault(self):
        android = self._config(
            action="android.intent.action.VIEW",
            categories=("android.intent.category.DEFAULT",),
        )
        richer = _merged(android).replace(
            '<category android:name="android.intent.category.DEFAULT" />',
            '<category android:name="android.intent.category.DEFAULT" />'
            '<category android:name="android.intent.category.BROWSABLE" />',
        )
        assert _mcheck(richer, android) == []


class TestMergedManifestPassthrough:
    def test_a_passthrough_attribute_the_merge_dropped_is_reported(self):
        android = _android(
            manifest=AndroidManifestConfig(application={"android:largeHeap": True})
        )
        bad = _merged(android).replace('android:largeHeap="true"', "")
        assert any("android:largeHeap" in p for p in _mcheck(bad, android))

    def test_a_generated_default_the_merge_dropped_is_reported(self):
        """The four generated defaults are expectations passthrough cannot move.

        ``android:label``/``icon``/``roundIcon``/``theme`` are all in
        ``MANAGED_ANDROID_APPLICATION_ATTRS``, so the loader rejects a
        pyproject that tries to set them and no real config can override
        them. The check still builds its expectation defaults-then-passthrough
        the way the generator does, so the two cannot disagree if that ever
        changes — but today only the merge can take one of these away.
        """
        android = _android()
        bad = _merged(android).replace('android:icon="@mipmap/ic_launcher"', "", 1)
        assert any("android:icon" in p for p in _mcheck(bad, android))

    def test_the_round_icon_is_expected_only_when_an_icon_source_is_configured(self):
        """Naming a roundIcon with no icon source would fail AAPT, so it is absent."""
        plain = _android()
        assert _mcheck(_merged(plain), plain) == []

        with_icon = _android(icons=AndroidIconConfig(source="icon.png"))
        bad = _merged(with_icon).replace(
            'android:roundIcon="@mipmap/ic_launcher_round"', "", 1
        )
        assert any("android:roundIcon" in p for p in _mcheck(bad, with_icon))

    def test_a_value_containing_an_ampersand_is_compared_unescaped(self):
        """ElementTree un-escapes on the way in; the expectation must not re-escape.

        This is the test whose first run found the generator double-escaping
        passthrough values (fixed in ``generate/manifest.py::_attr_str``), so
        it is pinning the checker and the generator against each other.
        """
        android = _android(
            manifest=AndroidManifestConfig(
                application={"android:description": "Rock & Roll"}
            )
        )
        assert _mcheck(_merged(android), android) == []

    def test_a_non_android_namespaced_key_is_not_looked_for(self):
        """Only ``android:`` keys are expectations; others cannot be asserted.

        A bare (un-prefixed) key lands in the generated manifest verbatim and
        in no namespace, so Android ignores it and this check must too —
        looking for it under the ``android:`` namespace would report a fault
        on every build. ``tools:`` never reaches here at all: the generator
        emits no ``xmlns:tools``, so a ``tools:``-prefixed passthrough key
        fails well-formedness at generation time, which is the right place.
        """
        android = _android(
            manifest=AndroidManifestConfig(application={"largeHeap": True})
        )
        assert _mcheck(_merged(android), android) == []

        with pytest.raises(ManifestError, match="not well-formed"):
            generate_manifest(
                _android(
                    manifest=AndroidManifestConfig(
                        application={"tools:replace": "android:label"}
                    )
                ),
                orientation=("portrait",),
            )


class TestMergedManifestPlaceholders:
    def test_an_unresolved_placeholder_is_reported(self):
        android = _android(
            manifest=AndroidManifestConfig(
                extra_application_xml=(
                    '<meta-data android:name="api.key" android:value="${apiKey}" />'
                )
            )
        )
        problems = _mcheck(_merged(android), android)
        assert any("unresolved placeholder" in p and "${apiKey}" in p for p in problems)

    def test_a_substituted_placeholder_leaves_nothing_behind(self):
        android = _android(
            manifest=AndroidManifestConfig(
                placeholders={"apiKey": "abc123"},
                extra_application_xml=(
                    '<meta-data android:name="api.key" android:value="${apiKey}" />'
                ),
            )
        )
        assert _mcheck(_merged(android), android) == []

    def test_applicationid_substitution_is_not_reported(self):
        android = _android(
            manifest=AndroidManifestConfig(
                extra_application_xml=(
                    '<meta-data android:name="pkg" android:value="${applicationId}" />'
                )
            )
        )
        assert _mcheck(_merged(android), android) == []


class TestMergedManifestMalformed:
    def test_a_manifest_that_does_not_parse_is_reported(self):
        assert any("does not parse" in p for p in _mcheck("<<< not xml", _android()))

    def test_a_manifest_rooted_at_the_wrong_element_is_reported(self):
        problems = _mcheck("<project />", _android())
        assert any("root element is <project>" in p for p in problems)

    def test_a_manifest_with_no_application_is_reported(self):
        problems = _mcheck(
            f'<manifest xmlns:android="{ANDROID_NS}" package="org.kivyforge.test" />',
            _android(),
        )
        assert any("no <application>" in p for p in problems)


# --- Android signature report -----------------------------------------------
#
# The fixture strings are real ``apksigner verify -v`` output, trimmed to the
# lines the parser reads. The spawn that produces them is in the driver
# (``test_apk_artifact.py``), which is why only the parse is tested here.

_V2_V3_REPORT = """Verifies
Verified using v1 scheme (JAR signing): false
Verified using v2 scheme (APK Signature Scheme v2): true
Verified using v3 scheme (APK Signature Scheme v3): true
Verified using v3.1 scheme (APK Signature Scheme v3.1): false
Verified using v4 scheme (APK Signature Scheme v4): false
Verified for SourceStamp: false
Number of signers: 1
"""

_V1_ONLY_REPORT = """Verifies
Verified using v1 scheme (JAR signing): true
Verified using v2 scheme (APK Signature Scheme v2): false
Verified using v3 scheme (APK Signature Scheme v3): false
Number of signers: 1
"""


class TestApksignerReport:
    def test_a_v2_signed_apk_with_v1_off_is_clean(self):
        assert apksigner_report_problems(_V2_V3_REPORT, v1_signing=False) == []

    def test_v1_signing_left_on_when_config_turned_it_off_is_reported(self):
        both = _V2_V3_REPORT.replace(
            "v1 scheme (JAR signing): false", "v1 scheme (JAR signing): true"
        )
        problems = apksigner_report_problems(both, v1_signing=False)
        assert any("v1 (JAR) signing is on" in p for p in problems)

    def test_v1_signing_missing_when_config_asked_for_it_is_reported(self):
        problems = apksigner_report_problems(_V2_V3_REPORT, v1_signing=True)
        assert any("v1 (JAR) signing is off" in p for p in problems)

    def test_a_v1_only_apk_is_reported_even_though_it_verifies(self):
        """The case the check exists for: intact, installable, and still wrong.

        A v1-only APK passes ``apksigner verify`` outright. It is a fault
        because ``min_sdk`` is 24, where the platform verifies v2+, so the
        signature the device actually checks is not the one present.
        """
        problems = apksigner_report_problems(_V1_ONLY_REPORT, v1_signing=True)
        assert any("no modern signature block" in p for p in problems)

    def test_a_report_with_no_scheme_lines_is_a_fault_not_a_pass(self):
        """An unparseable report must never read as "nothing wrong found"."""
        problems = apksigner_report_problems("DOES NOT VERIFY\n", v1_signing=False)
        assert any("no 'Verified using vN scheme' lines" in p for p in problems)

    def test_scheme_lines_without_the_verifies_header_are_reported(self):
        no_header = _V2_V3_REPORT.replace("Verifies\n", "", 1)
        problems = apksigner_report_problems(no_header, v1_signing=False)
        assert any("did not print 'Verifies'" in p for p in problems)

    def test_the_verifies_header_must_be_its_own_line(self):
        """``Verifies`` is matched against whole lines, not as a substring.

        ``DOES NOT VERIFY`` and a warning mentioning the word both contain it;
        apksigner's success marker is the bare line, and anything looser would
        turn a failed verification into a pass.
        """
        sneaky = _V2_V3_REPORT.replace(
            "Verifies\n", "WARNING: Verifies is not what this says\n", 1
        )
        problems = apksigner_report_problems(sneaky, v1_signing=False)
        assert any("did not print 'Verifies'" in p for p in problems)


# --- Windows signature report -----------------------------------------------
#
# All three fixtures are verbatim ``signtool verify /pa /v`` output captured on
# 2026-09-21 from the Windows SDK 10.0.22621.0 signtool: a currently-valid
# Microsoft-signed binary, kivyforge's own unsigned built launcher, and a
# python.org ``python.exe`` whose signing certificate had since been revoked.
# The last one is the fixture that matters most — it prints a full certificate
# chain and "The signature is timestamped", so every marker of a pass except
# the counts is present in a report that must fail.

_SIGNTOOL_GOOD = """
Verifying: signtool.exe

Signature Index: 0 (Primary Signature)
Hash of file (sha256): 68121927396A705450D0FAEF2886F480114E8FD2E0BDC412CBF3758AEA61A61F

Signing Certificate Chain:
    Issued to: Microsoft Root Certificate Authority 2010
    Issued by: Microsoft Root Certificate Authority 2010

The signature is timestamped: Sat Sep 30 02:08:11 2023

Successfully verified: signtool.exe

Number of files successfully Verified: 1
Number of warnings: 0
Number of errors: 0
"""

# The two failing fixtures keep signtool's real quirks, both of which broke a
# first attempt at the parser that a tidier fixture had passed:
#
# 1. signtool separates *every* line of its output with a blank one, so the
#    tab-indented explanation of an error is two lines below the error, not
#    one.
# 2. the verification counts go to **stdout** and the ``SignTool Error`` lines
#    to **stderr**, so in the driver's ``stdout + stderr`` the errors appear
#    after the counts rather than interleaved where signtool's console shows
#    them.
#
# These fixtures are spelled the way the driver actually sees them.

_SIGNTOOL_UNSIGNED = """
Verifying: Dice Roller.exe

Number of files successfully Verified: 0

Number of warnings: 0

Number of errors: 1

SignTool Error: No signature found.
"""

_SIGNTOOL_REVOKED = """
Verifying: python.exe

Signature Index: 0 (Primary Signature)

Hash of file (sha256): 68121927396A705450D0FAEF2886F480114E8FD2E0BDC412CBF3758AEA61A61F

Signing Certificate Chain:

    Issued to: Python Software Foundation

    Issued by: Microsoft ID Verified CS EOC CA 02

The signature is timestamped: Tue Dec 03 13:13:09 2024

Number of files successfully Verified: 0

Number of warnings: 0

Number of errors: 1

SignTool Error: WinVerifyTrust returned error: 0x800B010C

\tA certificate was explicitly revoked by its issuer.
"""


class TestSigntoolReport:
    def test_a_valid_timestamped_signature_is_clean(self):
        assert signtool_report_problems(_SIGNTOOL_GOOD) == []

    def test_an_unsigned_binary_is_reported(self):
        problems = signtool_report_problems(_SIGNTOOL_UNSIGNED)
        assert any("verified 0 file(s)" in p for p in problems)
        assert any("No signature found" in p for p in problems)

    def test_a_revoked_certificate_is_reported_despite_the_full_chain(self):
        """The case that makes counting necessary rather than pattern-matching.

        This report has a certificate chain, a timestamp line, and the word
        "verified" in it. Only the counts and the ``SignTool Error`` line say
        it failed.
        """
        problems = signtool_report_problems(_SIGNTOOL_REVOKED)
        assert any("explicitly revoked" in p for p in problems)

    def test_an_untimestamped_signature_is_reported(self):
        no_stamp = "\n".join(
            line for line in _SIGNTOOL_GOOD.splitlines() if "is timestamped" not in line
        )
        problems = signtool_report_problems(no_stamp)
        assert any("no RFC3161 timestamp" in p for p in problems)

    def test_the_timestamp_requirement_can_be_waived(self):
        no_stamp = "\n".join(
            line for line in _SIGNTOOL_GOOD.splitlines() if "is timestamped" not in line
        )
        assert signtool_report_problems(no_stamp, require_timestamp=False) == []

    def test_a_report_with_no_counts_is_a_fault_not_a_pass(self):
        problems = signtool_report_problems("signtool did something else\n")
        assert any("printed no verification counts" in p for p in problems)

    def test_more_than_one_verified_file_is_reported(self):
        """One file in, one file verified; anything else means the wrong argv."""
        two = _SIGNTOOL_GOOD.replace(
            "Number of files successfully Verified: 1",
            "Number of files successfully Verified: 2",
        )
        problems = signtool_report_problems(two)
        assert any("verified 2 file(s), expected 1" in p for p in problems)


# --- macOS -------------------------------------------------------------------
#
# 0xFEEDFACF is MH_MAGIC_64, hardcoded rather than imported so these fixtures
# stay independent of machotools' internals — same reasoning as the Android
# fixtures above building raw ELF bytes instead of importing a header helper.

MAGIC_MACOS_314 = struct.pack("<H", 3627) + b"\r\n"
MAGIC_MACOS_314_ALPHA = struct.pack("<H", 3621) + b"\r\n"


def _macho(cpu_type: int) -> bytes:
    """Minimal thin 64-bit Mach-O header: real macOS binaries are little-endian."""
    return struct.pack("<II", 0xFEEDFACF, cpu_type) + b"\x00" * 24


def _macos_app(
    tmp_path: Path,
    *,
    name: str = "Test.app",
    arch: int = CPU_TYPE_ARM64,
    executable: str = "test-app",
    bundle_id: str = "org.example.test",
    version: str = "1.0",
    build: str = "1",
    stripped: bool = True,
) -> Path:
    app = tmp_path / name
    resources = app / "Contents" / "Resources"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (resources / "app").mkdir(parents=True)
    (resources / "lib").mkdir(parents=True)
    (resources / "python" / "bin").mkdir(parents=True)

    (app / "Contents" / "MacOS" / executable).write_bytes(_macho(arch))
    (resources / "python" / "bin" / "python3").write_bytes(_macho(arch))

    plist = {
        "CFBundleIdentifier": bundle_id,
        "CFBundleExecutable": executable,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build,
    }
    with (app / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(plist, fh)

    if stripped:
        (resources / "app" / "main.pyc").write_bytes(MAGIC_MACOS_314 + b"body")
        (resources / "lib" / "somepkg.pyc").write_bytes(MAGIC_MACOS_314 + b"body")
    else:
        (resources / "app" / "main.py").write_text("x = 1\n")
        (resources / "lib" / "somepkg.py").write_text("x = 1\n")
    # The embedded stdlib always ships source, stripped or not — verifying
    # that this is *not* flagged is the point of TestMacosStdlibExcluded.
    (resources / "python" / "os.py").write_text("x = 1\n")

    return app


def _check_macos(
    app: Path,
    *,
    arch: str = "arm64",
    stripped: bool = True,
    magic: bytes = MAGIC_MACOS_314,
    expected_plist=None,
    executable=None,
):
    return macos_app_problems(
        app,
        arch=arch,
        stripped=stripped,
        expected_magic=magic,
        expected_plist=expected_plist,
        executable=executable,
    )


class TestMacosCleanArtifacts:
    def test_a_well_formed_stripped_app_has_no_problems(self, tmp_path):
        app = _macos_app(tmp_path)
        assert _check_macos(app) == []

    def test_x86_64_is_checked_against_its_own_arch(self, tmp_path):
        app = _macos_app(tmp_path, arch=CPU_TYPE_X86_64)
        assert _check_macos(app, arch="x86_64") == []

    def test_an_unstripped_app_wants_source(self, tmp_path):
        app = _macos_app(tmp_path, stripped=False)
        assert _check_macos(app, stripped=False) == []

    def test_plist_matching_expected_values_passes(self, tmp_path):
        app = _macos_app(tmp_path, bundle_id="org.kivy.demo", executable="demo")
        assert (
            _check_macos(
                app,
                expected_plist={"CFBundleIdentifier": "org.kivy.demo"},
                executable="demo",
            )
            == []
        )


class TestMacosStdlibExcluded:
    """The embedded CPython framework's stdlib is never stripped — by design."""

    def test_stdlib_py_files_are_not_flagged_when_stripped(self, tmp_path):
        app = _macos_app(tmp_path, stripped=True)
        assert (app / "Contents/Resources/python/os.py").is_file()
        assert _check_macos(app, stripped=True) == []


class TestMacosPayloadStripping:
    def test_a_leftover_source_file_under_app_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/app/leftover.py").write_text("x = 1\n")
        problems = _check_macos(app)
        assert any("1 .py file(s) remain" in p for p in problems)

    def test_a_leftover_source_file_under_lib_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/lib/leftover.py").write_text("x = 1\n")
        problems = _check_macos(app)
        assert any(
            "1 .py file(s) remain under Contents/Resources/lib" in p for p in problems
        )

    def test_a_payload_with_no_bytecode_is_reported_as_degraded(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/app/main.pyc").unlink()
        problems = _check_macos(app)
        assert any("degraded to shipping source" in p for p in problems)

    def test_pycache_defeats_sourceless_import(self, tmp_path):
        app = _macos_app(tmp_path)
        cache = app / "Contents/Resources/lib/__pycache__"
        cache.mkdir()
        (cache / "somepkg.cpython-314.pyc").write_bytes(MAGIC_MACOS_314 + b"body")
        problems = _check_macos(app)
        assert any("__pycache__" in p for p in problems)


class TestMacosArch:
    def test_a_host_binary_leaking_into_a_cross_build_is_reported(self, tmp_path):
        app = _macos_app(tmp_path, arch=CPU_TYPE_ARM64)
        (app / "Contents/Resources/lib/native.so").write_bytes(_macho(CPU_TYPE_X86_64))
        problems = _check_macos(app, arch="arm64")
        assert any("native.so is x86_64 but this build is arm64" in p for p in problems)

    def test_a_non_macho_file_is_not_flagged(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/lib/readme.txt").write_text("not a binary")
        assert _check_macos(app) == []

    def test_an_unknown_arch_fails_fast(self, tmp_path):
        app = _macos_app(tmp_path)
        assert _check_macos(app, arch="armv7") == [
            "unknown arch 'armv7'; expected one of ['arm64', 'x86_64']"
        ]


class TestMacosPlist:
    def test_a_mismatched_bundle_id_is_reported(self, tmp_path):
        app = _macos_app(tmp_path, bundle_id="org.example.test")
        problems = _check_macos(
            app, expected_plist={"CFBundleIdentifier": "org.other.app"}
        )
        assert any("CFBundleIdentifier" in p and "org.other.app" in p for p in problems)

    def test_every_expected_key_is_compared_not_just_the_first(self, tmp_path):
        """One run reports every mismatched key, like every other check here."""
        app = _macos_app(tmp_path, bundle_id="org.example.test")
        problems = _check_macos(
            app,
            expected_plist={
                "CFBundleIdentifier": "org.other.app",
                "CFBundleShortVersionString": "9.9.9",
                "LSMinimumSystemVersion": "14.0",
            },
        )
        assert len(problems) == 3, problems

    def test_a_key_absent_from_the_plist_is_reported(self, tmp_path):
        """A missing key must not read as "nothing to compare, so fine"."""
        app = _macos_app(tmp_path)
        problems = _check_macos(app, expected_plist={"LSMinimumSystemVersion": "11.0"})
        assert any("LSMinimumSystemVersion is None" in p for p in problems)

    def test_keys_not_named_in_the_expectation_are_ignored(self, tmp_path):
        """The plist holds build-time and fixed keys config does not decide."""
        app = _macos_app(tmp_path, bundle_id="org.example.test")
        assert _check_macos(app, expected_plist={}) == []

    def test_the_expected_plist_comes_from_the_production_builder(self):
        """``macos_expected_plist`` must not grow its own copy of the key list.

        Asserting the shape rather than the values: the point is that it is
        ``build_info_plist``'s output minus the two build-time keys, so a key
        added to the production builder is picked up here for free.
        """
        config = load_config_from_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "2.3.4"\n'
            "[tool.kivy]\n"
            'app_dir = "src"\n'
            'entry_point = "main"\n'
            'display_name = "Demo App"\n'
            "[tool.kivy.macos]\n"
            "schema_version = 1\n"
            'bundle_id = "org.kivy.demo"\n'
            "build = 7\n"
            "[tool.kivy.macos.python]\n"
            'version = "3.13.1"\n',
            require_ios=False,
            require_macos=True,
        )
        expected = macos_expected_plist(config)
        assert expected["CFBundleIdentifier"] == "org.kivy.demo"
        assert expected["CFBundleShortVersionString"] == "2.3.4"
        assert expected["CFBundleVersion"] == "7"
        assert expected["CFBundleDisplayName"] == "Demo App"
        # The two a config-only caller cannot know are absent, not empty.
        assert "CFBundleExecutable" not in expected
        assert "CFBundleIconFile" not in expected

    def test_a_mismatched_executable_is_reported(self, tmp_path):
        app = _macos_app(tmp_path, executable="test-app")
        problems = _check_macos(app, executable="something-else")
        assert any("CFBundleExecutable" in p for p in problems)

    def test_an_executable_not_matching_any_file_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        plist_path = app / "Contents/Info.plist"
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
        plist["CFBundleExecutable"] = "does-not-exist"
        with plist_path.open("wb") as fh:
            plistlib.dump(plist, fh)
        problems = _check_macos(app)
        assert any("does not name a file" in p for p in problems)

    def test_an_unparseable_plist_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Info.plist").write_bytes(b"not a plist")
        problems = _check_macos(app)
        assert any("does not parse" in p for p in problems)

    def test_a_missing_required_key_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        plist_path = app / "Contents/Info.plist"
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
        del plist["CFBundleVersion"]
        with plist_path.open("wb") as fh:
            plistlib.dump(plist, fh)
        problems = _check_macos(app)
        assert any("CFBundleVersion" in p for p in problems)


class TestMacosPycMagic:
    def test_bytecode_from_the_wrong_interpreter_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Resources/lib/somepkg.pyc").write_bytes(
            MAGIC_MACOS_314_ALPHA + b"body"
        )
        problems = _check_macos(app)
        assert any("3621" in p and "3627" in p for p in problems)

    def test_the_magic_check_is_skipped_when_unstripped(self, tmp_path):
        app = _macos_app(tmp_path, stripped=False)
        # An unstripped build has no .pyc to mismatch in the first place, but
        # confirm the check path is simply not taken.
        problems = _check_macos(app, stripped=False)
        assert not any("3621" in p for p in problems)


class TestMacosRequiredEntries:
    def test_a_missing_info_plist_is_reported(self, tmp_path):
        app = _macos_app(tmp_path)
        (app / "Contents/Info.plist").unlink()
        problems = _check_macos(app)
        assert any("Info.plist is missing" in p for p in problems)

    def test_a_missing_executable_is_reported(self, tmp_path):
        app = _macos_app(tmp_path, executable="test-app")
        (app / "Contents/MacOS/test-app").unlink()
        problems = _check_macos(app)
        assert any("no executable" in p for p in problems)

    def test_a_missing_runtime_is_reported(self, tmp_path):
        import shutil

        app = _macos_app(tmp_path)
        shutil.rmtree(app / "Contents/Resources/python")
        problems = _check_macos(app)
        assert any("embedded runtime" in p for p in problems)

    def test_a_missing_app_payload_is_reported(self, tmp_path):
        import shutil

        app = _macos_app(tmp_path)
        shutil.rmtree(app / "Contents/Resources/app")
        problems = _check_macos(app)
        assert any("app payload" in p for p in problems)


# ---------------------------------------------------------------------------
# iOS
# ---------------------------------------------------------------------------
#
# The fixture is deliberately flat (no ``Contents/``) — see
# ``artifact_checks.py``'s iOS module note and ios-t3-checks-findings.md's
# Step 0 dump, which is what this shape is read off. No stripped/pyc-magic
# variant exists here, for the same reason ``ios_app_problems`` takes no
# ``stripped`` parameter: there is nothing honest to write a test against yet.


def _ios_app(
    tmp_path: Path,
    *,
    name: str = "Test.app",
    arch: int = CPU_TYPE_ARM64,
    executable: str = "test-app",
    bundle_id: str = "org.example.test",
    version: str = "1.0",
    build: str = "1",
) -> Path:
    app = tmp_path / name
    (app / "Frameworks" / "Python.framework").mkdir(parents=True)
    (app / "python" / "lib" / "python3.15").mkdir(parents=True)
    (app / "app").mkdir(parents=True)
    (app / "pip-deps").mkdir(parents=True)

    (app / executable).write_bytes(_macho(arch))
    (app / "Frameworks" / "Python.framework" / "Python").write_bytes(_macho(arch))
    (app / "app" / "main.py").write_text("x = 1\n")

    plist = {
        "CFBundleIdentifier": bundle_id,
        "CFBundleExecutable": executable,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build,
    }
    with (app / "Info.plist").open("wb") as fh:
        plistlib.dump(plist, fh)

    return app


def _check_ios(app: Path, *, arch: str = "arm64", expected_plist=None):
    return ios_app_problems(app, arch=arch, expected_plist=expected_plist)


class TestIosCleanArtifacts:
    def test_a_well_formed_app_has_no_problems(self, tmp_path):
        app = _ios_app(tmp_path)
        assert _check_ios(app) == []

    def test_x86_64_is_checked_against_its_own_arch(self, tmp_path):
        app = _ios_app(tmp_path, arch=CPU_TYPE_X86_64)
        assert _check_ios(app, arch="x86_64") == []

    def test_plist_matching_expected_values_passes(self, tmp_path):
        app = _ios_app(tmp_path, bundle_id="org.kivy.demo")
        assert (
            _check_ios(app, expected_plist={"CFBundleIdentifier": "org.kivy.demo"})
            == []
        )


class TestIosArch:
    def test_a_host_binary_leaking_into_a_hoisted_framework_is_reported(self, tmp_path):
        """The failure ``install_python`` hoisting exists to make impossible.

        Every compiled extension module lives in its own
        ``Frameworks/<name>.framework/<name>`` (see the module note) — so a
        cross-arch leak there is exactly as real a bug as one in the root
        executable, and the sweep has to reach it.
        """
        app = _ios_app(tmp_path, arch=CPU_TYPE_ARM64)
        (app / "Frameworks" / "_ssl.framework").mkdir(parents=True)
        (app / "Frameworks" / "_ssl.framework" / "_ssl").write_bytes(
            _macho(CPU_TYPE_X86_64)
        )
        problems = _check_ios(app, arch="arm64")
        assert any(
            "Frameworks/_ssl.framework/_ssl is x86_64 but this build is arm64" in p
            for p in problems
        )

    def test_a_fwork_stub_is_not_mistaken_for_a_binary(self, tmp_path):
        """``.fwork`` stubs are plain text (a relative path), never Mach-O."""
        app = _ios_app(tmp_path)
        (app / "pip-deps" / "kivy").mkdir(parents=True)
        (
            app / "pip-deps" / "kivy" / "_clock.cpython-315-iphonesimulator.fwork"
        ).write_text("Frameworks/kivy._clock.framework/kivy._clock\n")
        assert _check_ios(app) == []

    def test_a_non_macho_file_is_not_flagged(self, tmp_path):
        app = _ios_app(tmp_path)
        (app / "app" / "readme.txt").write_text("not a binary")
        assert _check_ios(app) == []

    def test_an_unknown_arch_fails_fast(self, tmp_path):
        app = _ios_app(tmp_path)
        assert _check_ios(app, arch="armv7") == [
            "unknown arch 'armv7'; expected one of ['arm64', 'x86_64']"
        ]


class TestIosPlist:
    def test_a_mismatched_bundle_id_is_reported(self, tmp_path):
        app = _ios_app(tmp_path, bundle_id="org.example.test")
        problems = _check_ios(
            app, expected_plist={"CFBundleIdentifier": "org.other.app"}
        )
        assert any("CFBundleIdentifier" in p and "org.other.app" in p for p in problems)

    def test_every_expected_key_is_compared_not_just_the_first(self, tmp_path):
        app = _ios_app(tmp_path, bundle_id="org.example.test")
        problems = _check_ios(
            app,
            expected_plist={
                "CFBundleIdentifier": "org.other.app",
                "CFBundleShortVersionString": "9.9.9",
                "MinimumOSVersion": "18.0",
            },
        )
        assert len(problems) == 3, problems

    def test_a_key_absent_from_the_plist_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        problems = _check_ios(app, expected_plist={"MinimumOSVersion": "16.0"})
        assert any("MinimumOSVersion is None" in p for p in problems)

    def test_keys_not_named_in_the_expectation_are_ignored(self, tmp_path):
        app = _ios_app(tmp_path, bundle_id="org.example.test")
        assert _check_ios(app, expected_plist={}) == []

    def test_the_expected_plist_comes_from_the_production_builder(self):
        """``ios_expected_plist`` must not grow its own copy of the key list.

        Same reasoning as ``macos_expected_plist``'s own version of this test:
        the point is that it is ``build_info_plist``'s output minus the one
        build-time key, so a key added to the production builder is picked up
        here for free.
        """
        config = load_config_from_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "2.3.4"\n'
            "[tool.kivy]\n"
            'app_dir = "src"\n'
            'entry_point = "main"\n'
            'display_name = "Demo App"\n'
            "[tool.kivy.ios]\n"
            "schema_version = 1\n"
            'bundle_id = "org.kivy.demo"\n'
            "build = 7\n"
            "[tool.kivy.ios.python]\n"
            'version = "3.15.0"\n',
            require_ios=True,
            require_macos=False,
        )
        expected = ios_expected_plist(config)
        assert expected["CFBundleIdentifier"] == "org.kivy.demo"
        assert expected["CFBundleShortVersionString"] == "2.3.4"
        assert expected["CFBundleVersion"] == "7"
        assert expected["CFBundleDisplayName"] == "Demo App"
        # The one key a config-only caller cannot know is absent, not empty.
        assert "CFBundleExecutable" not in expected

    def test_an_executable_not_matching_any_file_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        plist_path = app / "Info.plist"
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
        plist["CFBundleExecutable"] = "does-not-exist"
        with plist_path.open("wb") as fh:
            plistlib.dump(plist, fh)
        problems = _check_ios(app)
        assert any("does not name a file" in p for p in problems)

    def test_an_unparseable_plist_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        (app / "Info.plist").write_bytes(b"not a plist")
        problems = _check_ios(app)
        assert any("does not parse" in p for p in problems)

    def test_a_missing_required_key_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        plist_path = app / "Info.plist"
        with plist_path.open("rb") as fh:
            plist = plistlib.load(fh)
        del plist["CFBundleVersion"]
        with plist_path.open("wb") as fh:
            plistlib.dump(plist, fh)
        problems = _check_ios(app)
        assert any("CFBundleVersion" in p for p in problems)


class TestIosRequiredEntries:
    def test_a_missing_info_plist_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        (app / "Info.plist").unlink()
        problems = _check_ios(app)
        assert any("Info.plist is missing" in p for p in problems)

    def test_a_missing_runtime_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        shutil.rmtree(app / "Frameworks" / "Python.framework")
        problems = _check_ios(app)
        assert any("embedded CPython runtime" in p for p in problems)

    def test_a_missing_stdlib_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        shutil.rmtree(app / "python")
        problems = _check_ios(app)
        assert any("embedded runtime's own stdlib" in p for p in problems)

    def test_a_missing_app_payload_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        shutil.rmtree(app / "app")
        problems = _check_ios(app)
        assert any("app payload" in p for p in problems)

    def test_a_missing_pip_deps_is_reported(self, tmp_path):
        app = _ios_app(tmp_path)
        shutil.rmtree(app / "pip-deps")
        problems = _check_ios(app)
        assert any("pip-deps/ is missing" in p for p in problems)


# ---------------------------------------------------------------------------
# Linux: AppDir / AppImage
# ---------------------------------------------------------------------------

_SCRIPT_APPRUN = 'exec "$HERE/usr/python/bin/python3" "$HERE/usr/app/{entry}.py" "$@"\n'
_MODULE_APPRUN = 'exec "$HERE/usr/python/bin/python3" -m {entry} "$@"\n'


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _appdir(
    tmp_path: Path,
    *,
    stripped: bool = True,
    machine: int = EM_X86_64,
    minor: str = "3.13",
    apprun: str | None = None,
    magic: bytes = MAGIC_313,
) -> Path:
    """A well-formed AppDir: right arch, one runtime, payload in one state.

    Mirrors the real tree — runtime under ``usr/python``, site-packages under
    ``usr/lib``, app sources under ``usr/app`` — including a stdlib that keeps
    its ``.py`` and ``__pycache__`` even when the payload is stripped, because
    the build byte-compiles only the payload and a check that swept the whole
    tree would call the stdlib a fault.

    ``apprun`` defaults to a launcher that can actually start this payload: the
    ``-m`` form when stripped, the script form otherwise. Pairing the script
    form *with* a stripped payload is precisely the shipped bug, so the tests
    that assert on it ask for that combination explicitly rather than getting it
    by default.
    """
    if apprun is None:
        apprun = _MODULE_APPRUN if stripped else _SCRIPT_APPRUN
    root = tmp_path / "Test.AppDir"
    (root / "usr").mkdir(parents=True, exist_ok=True)

    run = root / "AppRun"
    _write(run, ("#!/bin/sh\nHERE=x\n" + apprun.format(entry="main")).encode())
    run.chmod(0o755)
    _write(root / "org.example.test.desktop", b"[Desktop Entry]\nName=Test\n")

    _write(root / f"usr/python/lib/libpython{minor}.so", _elf(machine))
    _write(root / f"usr/python/bin/python{minor}", _elf(machine))
    _write(root / f"usr/python/lib/python{minor}/os.py", b"x = 1\n")
    _write(
        root / f"usr/python/lib/python{minor}/__pycache__/os.cpython-313.pyc",
        magic + b"body",
    )
    _write(root / "usr/lib/kivy/_speedup.so", _elf(machine))

    suffix, body = (".pyc", magic + b"body") if stripped else (".py", b"x = 1\n")
    _write(root / f"usr/app/main{suffix}", body)
    _write(root / f"usr/lib/kivy/__init__{suffix}", body)
    return root


def _lcheck(root: Path, *, arch="x86_64", stripped=True, magic=MAGIC_313):
    return linux_appdir_problems(
        root, arch=arch, stripped=stripped, expected_magic=magic
    )


class TestLinuxCleanArtifacts:
    def test_a_well_formed_stripped_appdir_has_no_problems(self, tmp_path):
        assert _lcheck(_appdir(tmp_path)) == []

    def test_an_unstripped_appdir_wants_source(self, tmp_path):
        assert _lcheck(_appdir(tmp_path, stripped=False), stripped=False) == []

    def test_the_stdlib_keeping_its_source_is_not_a_fault(self, tmp_path):
        """The payload is usr/app + usr/lib; usr/python is the runtime.

        A real stripped dice-roller AppImage ships 1037 stdlib ``.py`` and six
        ``__pycache__`` directories, because ``build_appdir`` byte-compiles only
        the payload. Sweeping the whole tree would report every one of them.
        """
        root = _appdir(tmp_path)
        for i in range(5):
            _write(root / f"usr/python/lib/python3.13/mod{i}.py", b"x = 1\n")
            _write(
                root / f"usr/python/lib/python3.13/__pycache__/m{i}.cpython-313.pyc",
                MAGIC_313 + b"body",
            )
        assert _lcheck(root) == []

    def test_an_aarch64_appdir_is_checked_against_its_own_machine(self, tmp_path):
        root = _appdir(tmp_path, machine=EM_AARCH64)
        assert _lcheck(root, arch="aarch64") == []

    def test_an_unknown_arch_fails_fast(self, tmp_path):
        assert _lcheck(_appdir(tmp_path), arch="riscv64") == [
            "unknown arch 'riscv64'; expected one of ['aarch64', 'x86_64']"
        ]


class TestAppRunEntryPoint:
    """The Linux shape of roadmap item 1, and a bug that actually shipped."""

    def test_apprun_pointing_at_a_stripped_away_source_file_is_reported(self, tmp_path):
        """`kivyforge package` produced exactly this: AppRun execs a deleted file."""
        root = _appdir(
            tmp_path, apprun=_SCRIPT_APPRUN
        )  # main.pyc exists, main.py does not
        problems = _lcheck(root)
        assert any(
            "AppRun execs usr/app/main.py" in p and "cannot start" in p
            for p in problems
        )

    def test_the_diagnosis_names_the_bytecode_sitting_beside_it(self, tmp_path):
        problems = _lcheck(_appdir(tmp_path, apprun=_SCRIPT_APPRUN))
        assert any("usr/app/main.pyc is there" in p for p in problems)

    def test_the_module_form_accepts_a_sourceless_payload(self, tmp_path):
        """The proposed fix: `-m main` resolves main.pyc through the importer."""
        root = _appdir(tmp_path, apprun=_MODULE_APPRUN)
        assert _lcheck(root) == []

    def test_the_module_form_still_catches_a_missing_entry_point(self, tmp_path):
        root = _appdir(tmp_path, apprun=_MODULE_APPRUN)
        (root / "usr/app/main.pyc").unlink()
        problems = _lcheck(root)
        assert any(
            "neither usr/app/main.py nor usr/app/main.pyc" in p for p in problems
        )

    def test_a_dotted_entry_point_maps_to_a_nested_file(self, tmp_path):
        root = _appdir(tmp_path, apprun='exec "$HERE/x" -m pkg.start "$@"\n')
        _write(root / "usr/app/pkg/start.pyc", MAGIC_313 + b"body")
        assert not any("pkg" in p for p in _lcheck(root))

    def test_an_apprun_with_no_exec_line_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "AppRun").write_text("#!/bin/sh\necho nothing\n")
        assert any("no exec line" in p for p in _lcheck(root))

    @pytest.mark.skipif(
        os.name != "posix",
        reason=(
            "NTFS stores no execute bit, so chmod(0o644) is indistinguishable "
            "from chmod(0o755) here and the check deliberately does not ask"
        ),
    )
    def test_a_non_executable_apprun_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "AppRun").chmod(0o644)
        assert any("not executable" in p for p in _lcheck(root))

    def test_a_missing_apprun_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "AppRun").unlink()
        assert any("AppRun is missing" in p for p in _lcheck(root))


class TestLinuxPayloadStripping:
    def test_a_leftover_source_file_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/leftover.py", b"x = 1\n")
        assert any("1 .py file(s) remain" in p for p in _lcheck(root))

    def test_a_payload_with_no_bytecode_is_reported_as_degraded(self, tmp_path):
        root = _appdir(tmp_path)
        for pyc in [root / "usr/app/main.pyc", root / "usr/lib/kivy/__init__.pyc"]:
            pyc.unlink()
        assert any("degraded to shipping source" in p for p in _lcheck(root))

    def test_pycache_in_the_payload_defeats_sourceless_import(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/__pycache__/m.cpython-313.pyc", MAGIC_313 + b"body")
        assert any("__pycache__" in p for p in _lcheck(root))

    def test_pycache_in_an_unstripped_payload_accuses_the_launch(self, tmp_path):
        """A build never writes payload ``__pycache__``; running the AppDir does.

        Measured on dice-roller: ``kivyforge build -p linux`` staged 336 ``.py``
        and zero ``.pyc``, then launching that same AppDir left 100 ``.pyc`` in
        ``usr/app``/``usr/lib``. So this is normal in a working tree and never
        in a freshly staged artifact, which is what makes it worth reporting
        even though the payload is *meant* to be source here.
        """
        root = _appdir(tmp_path, stripped=False)
        _write(root / "usr/lib/kivy/__pycache__/m.cpython-313.pyc", MAGIC_313 + b"body")
        problems = _lcheck(root, stripped=False)
        assert any("written to after the build" in p for p in problems)
        assert not any("strip_source" in p for p in problems)

    def test_an_unstripped_payload_without_pycache_is_clean(self, tmp_path):
        assert _lcheck(_appdir(tmp_path, stripped=False), stripped=False) == []

    def test_an_empty_payload_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        for path in [root / "usr/app", root / "usr/lib"]:
            for f in path.rglob("*"):
                if f.is_file():
                    f.unlink()
        assert any("no payload" in p for p in _lcheck(root))


class TestLinuxPycMagic:
    def test_bytecode_from_the_wrong_interpreter_is_reported(self, tmp_path):
        """The real Linux mismatch: a 3.14 host compiling for a 3.13 runtime."""
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/__init__.pyc", MAGIC_314 + b"body")
        problems = _lcheck(root)
        assert any("3627" in p and "3571" in p for p in problems)

    def test_the_magic_check_is_skipped_when_source_ships_alongside(self, tmp_path):
        root = _appdir(tmp_path, stripped=False)
        _write(root / "usr/lib/kivy/stale.pyc", MAGIC_314 + b"body")
        assert not any("3627" in p for p in _lcheck(root, stripped=False))

    def test_the_stdlib_is_not_judged_for_magic(self, tmp_path):
        """usr/python is the shipped runtime's own business, not the payload's."""
        root = _appdir(tmp_path)
        _write(
            root / "usr/python/lib/python3.13/__pycache__/x.cpython-313.pyc",
            MAGIC_314 + b"body",
        )
        assert not any("3627" in p for p in _lcheck(root))


class TestLinuxElfArch:
    def test_a_foreign_arch_extension_module_is_reported(self, tmp_path):
        """Coverage doctor does not have: site-packages, not usr/bin."""
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/_speedup.so", _elf(EM_AARCH64))
        problems = _lcheck(root)
        assert any("_speedup.so" in p and "aarch64" in p for p in problems)

    def test_a_foreign_arch_runtime_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/python/lib/libpython3.13.so", _elf(EM_AARCH64))
        assert any("libpython3.13.so" in p for p in _lcheck(root))

    def test_a_32_bit_object_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/lib/kivy/_speedup.so", _elf(EM_X86_64, ei_class=ELFCLASS32))
        assert any("ELF32" in p for p in _lcheck(root))

    def test_a_declared_native_binary_is_checked_too(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/bin/helper", _elf(EM_AARCH64))
        assert any("usr/bin/helper" in p for p in _lcheck(root))

    def test_a_non_elf_file_is_not_mistaken_for_one(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/bin/helper.sh", b"#!/bin/sh\necho hi\n")
        assert _lcheck(root) == []


class TestLinuxShippedRuntime:
    def test_the_runtime_version_is_read_out_of_the_artifact(self, tmp_path):
        assert shipped_python_tags_appdir(_appdir(tmp_path)) == ["3.13"]

    def test_a_versioned_soname_is_recognised(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "usr/python/lib/libpython3.13.so").rename(
            root / "usr/python/lib/libpython3.13.so.1.0"
        )
        assert shipped_python_tags_appdir(root) == ["3.13"]

    def test_the_abi_stub_is_not_mistaken_for_a_runtime(self, tmp_path):
        """libpython3.so carries no minor and must not count as a second one."""
        root = _appdir(tmp_path)
        _write(root / "usr/python/lib/libpython3.so", _elf(EM_X86_64))
        assert shipped_python_tags_appdir(root) == ["3.13"]
        assert _lcheck(root) == []

    def test_two_runtimes_are_reported(self, tmp_path):
        root = _appdir(tmp_path)
        _write(root / "usr/python/lib/libpython3.14.so", _elf(EM_X86_64))
        assert shipped_python_tags_appdir(root) == ["3.13", "3.14"]
        assert any("ships 2 CPython runtimes" in p for p in _lcheck(root))

    def test_no_runtime_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "usr/python/lib/libpython3.13.so").unlink()
        assert any("ships no runtime" in p for p in _lcheck(root))

    def test_a_missing_desktop_entry_is_reported(self, tmp_path):
        root = _appdir(tmp_path)
        (root / "org.example.test.desktop").unlink()
        assert any(".desktop" in p for p in _lcheck(root))


class TestAppImageContainer:
    """appimagetool's own output, which inspecting the extracted tree cannot see."""

    def _appimage(self, tmp_path, *, machine=EM_X86_64, marker=b"AI\x02") -> Path:
        header = bytearray(_elf(machine))
        header[8:11] = marker
        return _write(tmp_path / "app.AppImage", bytes(header))

    def test_a_well_formed_type2_appimage_has_no_problems(self, tmp_path):
        assert (
            linux_appimage_file_problems(self._appimage(tmp_path), arch="x86_64") == []
        )

    def test_a_type1_appimage_is_reported(self, tmp_path):
        image = self._appimage(tmp_path, marker=b"AI\x01")
        assert any(
            "type-2" in p for p in linux_appimage_file_problems(image, arch="x86_64")
        )

    def test_a_plain_elf_with_no_marker_is_reported(self, tmp_path):
        image = self._appimage(tmp_path, marker=b"\x00\x00\x00")
        assert any(
            "appimagetool" in p
            for p in linux_appimage_file_problems(image, arch="x86_64")
        )

    def test_a_wrong_arch_runtime_is_reported(self, tmp_path):
        image = self._appimage(tmp_path, machine=EM_AARCH64)
        problems = linux_appimage_file_problems(image, arch="x86_64")
        assert any("type2-runtime" in p for p in problems)

    def test_a_non_elf_is_reported(self, tmp_path):
        image = _write(tmp_path / "app.AppImage", b"not an elf")
        assert any(
            "not an ELF" in p
            for p in linux_appimage_file_problems(image, arch="x86_64")
        )


# --------------------------------------------------------------------------
# Windows: onedir bundle
# --------------------------------------------------------------------------

# app/ (the developer's own sources) and python/Lib/site-packages (third-party
# deps) are the strip-source candidates, mirroring the Linux/macOS scoping.
# python/Lib's own stdlib keeps its source always (item 9), and
# _kivyforge_bootstrap.py lives at the bundle root -- outside both scopes, so a
# correctly scoped sweep never even walks it. TestWindowsPayloadStripping's
# bootstrap test is the regression guard for that.
_WINDOWS_STRIP_SCOPE = ("app", "python/Lib/site-packages")


def _pe(machine: int) -> bytes:
    """Minimal PE image: DOS stub + e_lfanew pointer + PE signature + machine."""
    header = bytearray(0x40)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x40)
    return bytes(header) + b"PE\x00\x00" + struct.pack("<H", machine)


def _windows_bundle(
    tmp_path: Path,
    *,
    stripped: bool = True,
    machine: int = IMAGE_FILE_MACHINE_AMD64,
    magic: bytes = MAGIC_314,
    name: str = "Test",
) -> Path:
    """A well-formed onedir bundle: right arch, one exe, payload in one state.

    Mirrors the real tree -- ``<Name>.exe`` + ``_kivyforge_bootstrap.py`` at
    the root, app sources under ``app/``, third-party deps under
    ``python/Lib/site-packages`` -- including a stdlib module elsewhere under
    ``python/Lib`` that keeps its ``.py`` even when the payload is stripped,
    because the build byte-compiles only ``app`` and ``site-packages``.
    """
    bundle = tmp_path / name
    _write(bundle / f"{name}.exe", _pe(machine))
    _write(bundle / "_kivyforge_bootstrap.py", b'"""Generated bootstrap."""\n')
    _write(bundle / "python" / "python.exe", _pe(machine))
    _write(bundle / "python" / "Lib" / "os.py", b"x = 1\n")

    suffix, body = (".pyc", magic + b"body") if stripped else (".py", b"x = 1\n")
    _write(bundle / f"app/main{suffix}", body)
    _write(bundle / f"python/Lib/site-packages/kivy/__init__{suffix}", body)
    return bundle


def _wcheck(bundle: Path, *, arch="amd64", stripped=True, magic=MAGIC_314):
    return windows_onedir_problems(
        bundle, arch=arch, stripped=stripped, expected_magic=magic
    )


class TestWindowsCleanArtifacts:
    def test_a_well_formed_stripped_bundle_has_no_problems(self, tmp_path):
        assert _wcheck(_windows_bundle(tmp_path)) == []

    def test_an_unstripped_bundle_wants_source(self, tmp_path):
        bundle = _windows_bundle(tmp_path, stripped=False)
        assert _wcheck(bundle, stripped=False) == []

    def test_the_stdlib_keeping_its_source_is_not_a_fault(self, tmp_path):
        """The strip scope is app/ + python/Lib/site-packages, not all of python/.

        A real stripped build byte-compiles only those two, so python/Lib's own
        stdlib modules keep their .py -- sweeping the whole python/ tree would
        call every one of them a fault.
        """
        bundle = _windows_bundle(tmp_path)
        for i in range(5):
            _write(bundle / f"python/Lib/mod{i}.py", b"x = 1\n")
        assert _wcheck(bundle) == []

    def test_an_arm64_bundle_is_checked_against_its_own_machine(self, tmp_path):
        bundle = _windows_bundle(tmp_path, machine=IMAGE_FILE_MACHINE_ARM64)
        assert _wcheck(bundle, arch="arm64") == []

    def test_an_unknown_arch_fails_fast(self, tmp_path):
        assert _wcheck(_windows_bundle(tmp_path), arch="mips") == [
            "unknown arch 'mips'; expected one of ['amd64', 'arm64']"
        ]

    def test_a_bundle_that_is_not_a_directory_is_reported(self, tmp_path):
        missing = tmp_path / "Nope"
        assert _wcheck(missing) == [f"{missing} is not a directory"]


class TestWindowsPayloadStripping:
    def test_the_bootstrap_module_staying_source_is_not_a_fault(self, tmp_path):
        """Regression test for the sweep's scoping.

        ``_kivyforge_bootstrap.py`` is generated at the bundle root, never
        compiled by design -- it is written *after* byte-compilation runs --
        and must never be walked by the strip-source sweep at all, not merely
        excused from the "must be compiled" check. A future change to the
        sweep's scope that starts reaching the bundle root should fail this.
        """
        bundle = _windows_bundle(tmp_path)
        assert (bundle / "_kivyforge_bootstrap.py").is_file()
        assert _wcheck(bundle) == []

    def test_a_leftover_source_file_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        _write(bundle / "python/Lib/site-packages/kivy/leftover.py", b"x = 1\n")
        assert any("1 .py file(s) remain" in p for p in _wcheck(bundle))

    def test_a_payload_with_no_bytecode_is_reported_as_degraded(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        (bundle / "app/main.pyc").unlink()
        (bundle / "python/Lib/site-packages/kivy/__init__.pyc").unlink()
        problems = _wcheck(bundle)
        assert sum("degraded to shipping source" in p for p in problems) == 2

    def test_pycache_in_the_payload_defeats_sourceless_import(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        _write(
            bundle / "python/Lib/site-packages/kivy/__pycache__/m.cpython-314.pyc",
            MAGIC_314 + b"body",
        )
        assert any("__pycache__" in p for p in _wcheck(bundle))

    def test_an_unstripped_app_with_no_entry_point_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path, stripped=False)
        (bundle / "app/main.py").unlink()
        assert any("no entry point" in p for p in _wcheck(bundle, stripped=False))


class TestWindowsPycMagic:
    def test_bytecode_from_the_wrong_interpreter_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        _write(bundle / "python/Lib/site-packages/kivy/stale.pyc", MAGIC_313 + b"body")
        problems = _wcheck(bundle)
        assert any("3627" in p and "3571" in p for p in problems)

    def test_the_magic_check_is_skipped_when_source_ships_alongside(self, tmp_path):
        bundle = _windows_bundle(tmp_path, stripped=False)
        _write(bundle / "python/Lib/site-packages/kivy/stale.pyc", MAGIC_313 + b"body")
        assert not any("3571" in p for p in _wcheck(bundle, stripped=False))

    def test_the_stdlib_is_not_judged_for_magic(self, tmp_path):
        """python/Lib outside site-packages is the shipped runtime's own business."""
        bundle = _windows_bundle(tmp_path)
        _write(
            bundle / "python/Lib/__pycache__/os.cpython-314.pyc", MAGIC_313 + b"body"
        )
        assert not any("3571" in p for p in _wcheck(bundle))


class TestWindowsPeArch:
    def test_a_foreign_arch_extension_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        _write(
            bundle / "python/Lib/site-packages/kivy/_speedup.pyd",
            _pe(IMAGE_FILE_MACHINE_ARM64),
        )
        problems = _wcheck(bundle)
        assert any("_speedup.pyd" in p and "arm64" in p for p in problems)

    def test_a_foreign_arch_launcher_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        (bundle / "Test.exe").write_bytes(_pe(IMAGE_FILE_MACHINE_ARM64))
        problems = _wcheck(bundle)
        assert any("Test.exe" in p and "arm64" in p for p in problems)

    def test_a_declared_native_binary_is_checked_too(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        _write(bundle / "bin/helper.dll", _pe(IMAGE_FILE_MACHINE_ARM64))
        problems = _wcheck(bundle)
        assert any("bin/helper.dll" in p for p in problems)

    def test_a_non_pe_file_is_not_mistaken_for_one(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        _write(bundle / "app/data.json", b'{"x": 1}')
        assert _wcheck(bundle) == []

    def test_distlibs_own_launcher_templates_are_not_a_fault(self, tmp_path):
        """Regression test found by a real build (dice-roller, 2026-09-17).

        pip vendors distlib, which ships six prebuilt launcher *templates*
        under ``distlib/`` — one per (bitness, console/windowed) combination —
        that get patched into a real launcher only when something installs a
        console-script entry point. Every pip install anywhere ships all six
        regardless of host or target arch, so the amd64 bundle correctly ships
        the arm64 and x86 variants too; that must never be reported as a
        leaked cross-arch binary.
        """
        bundle = _windows_bundle(tmp_path)
        stubs = bundle / "python/Lib/site-packages/pip/_vendor/distlib"
        for name, machine in [
            ("t32.exe", 0x014C),  # IMAGE_FILE_MACHINE_I386
            ("t64-arm.exe", IMAGE_FILE_MACHINE_ARM64),
            ("w32.exe", 0x014C),
            ("w64-arm.exe", IMAGE_FILE_MACHINE_ARM64),
        ]:
            _write(stubs / name, _pe(machine))
        assert _wcheck(bundle) == []


def _deep_file(bundle: Path, rel_len: int) -> str:
    """Add one file whose path relative to *bundle* is exactly *rel_len* long."""
    head = "python/Lib/site-packages/pkg/"
    name = "m" * (rel_len - len(head) - len(".py")) + ".py"
    _write(bundle / head / name, b"x = 1\n")
    return head + name


class TestWindowsPathDepth:
    """test-matrix §5.6: the bundle must leave room for its install folder."""

    def test_exactly_the_minimum_headroom_passes(self, tmp_path):
        bundle = _windows_bundle(tmp_path, stripped=False)
        _deep_file(bundle, 158)  # 259 - 1 - 158 = 100
        assert _wcheck(bundle, stripped=False) == []

    def test_one_character_less_headroom_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path, stripped=False)
        _deep_file(bundle, 159)
        [problem] = _wcheck(bundle, stripped=False)
        assert problem.startswith("deepest path is 159 characters (python")
        assert "leaving only 99 for the install folder" in problem


class TestWindowsRequiredEntries:
    def test_a_missing_exe_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        (bundle / "Test.exe").unlink()
        assert any("no <Name>.exe launcher" in p for p in _wcheck(bundle))

    def test_multiple_exes_are_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        _write(bundle / "Extra.exe", _pe(IMAGE_FILE_MACHINE_AMD64))
        assert any("2 .exe files" in p for p in _wcheck(bundle))

    def test_a_missing_bootstrap_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        (bundle / "_kivyforge_bootstrap.py").unlink()
        assert any("_kivyforge_bootstrap.py is missing" in p for p in _wcheck(bundle))

    def test_a_missing_app_dir_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        shutil.rmtree(bundle / "app")
        assert any("app/ (the app payload) is missing" in p for p in _wcheck(bundle))

    def test_a_missing_python_dir_is_reported(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        shutil.rmtree(bundle / "python")
        assert any(
            "python/ (the embedded runtime) is missing" in p for p in _wcheck(bundle)
        )

    def test_an_absent_bin_dir_is_not_a_fault(self, tmp_path):
        bundle = _windows_bundle(tmp_path)
        assert not (bundle / "bin").exists()
        assert _wcheck(bundle) == []
