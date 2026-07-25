"""Generator unit tests: manifest emission + project files (android/04)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.android.generate.manifest import (
    generate_manifest,
    implied_features,
    qualified_permissions,
    screen_orientation,
)
from kivyforge.platforms.android.generate.project import (
    write_app_build_gradle,
    write_gradle_pins,
    write_gradle_properties,
    write_resources,
)
from kivyforge.platforms.android.lock.model import (
    AndroidLockfile,
    GradleArtifact,
    GradlePins,
    GradleResolvedModule,
    PythonAndroidRuntime,
)

BASE = """
[project]
name = "genapp"
version = "1.0.0"
dependencies = ["pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.example.genapp"

[tool.kivy.android.python]
version = "3.14.6"
"""


def _android(extra: str = ""):
    text = BASE.replace(
        "[tool.kivy.android.python]", extra + "\n[tool.kivy.android.python]"
    )
    config = load_config_from_text(text, require_ios=False, require_android=True)
    return config, config.android_required


NS = "{http://schemas.android.com/apk/res/android}"


def _manifest_tree(android, orientation=("portrait",)):
    text = generate_manifest(android, orientation=orientation)
    return text, ET.fromstring(text)


class TestManifest:
    def test_bare_permission_prefixed(self):
        _, android = _android(
            '[tool.kivy.android.permissions]\nuses = ["INTERNET"]\n'
        )
        _, tree = _manifest_tree(android)
        names = [
            e.get(f"{NS}name") for e in tree.findall("uses-permission")
        ]
        assert names == ["android.permission.INTERNET"]

    def test_implied_features_non_required(self):
        _, android = _android(
            '[tool.kivy.android.permissions]\nuses = ["CAMERA"]\n'
        )
        _, tree = _manifest_tree(android)
        features = {
            e.get(f"{NS}name"): e.get(f"{NS}required")
            for e in tree.findall("uses-feature")
        }
        assert features["android.hardware.camera"] == "false"
        assert features["android.hardware.camera.autofocus"] == "false"

    def test_explicit_feature_overrides_synthesized(self):
        _, android = _android(
            "[tool.kivy.android.permissions]\n"
            'uses = ["CAMERA"]\n'
            'features = [{ name = "android.hardware.camera", required = true }]\n'
        )
        _, tree = _manifest_tree(android)
        features = {
            e.get(f"{NS}name"): e.get(f"{NS}required")
            for e in tree.findall("uses-feature")
        }
        assert features["android.hardware.camera"] == "true"

    def test_auto_features_off(self):
        _, android = _android(
            "[tool.kivy.android.permissions]\n"
            'uses = ["CAMERA"]\nauto_features = false\n'
        )
        _, tree = _manifest_tree(android)
        assert tree.findall("uses-feature") == []

    def test_foreground_service_adds_typed_permissions_and_element(self):
        _, android = _android(
            "[[tool.kivy.android.services]]\n"
            'name = "Downloader"\n'
            'entry_point = "svc"\n'
            "foreground = true\n"
            'foreground_service_type = "dataSync"\n'
            'notification = { channel_id = "c", channel_name = "C", '
            'title = "t", text = "x" }\n'
        )
        text, tree = _manifest_tree(android)
        permissions = [
            e.get(f"{NS}name") for e in tree.findall("uses-permission")
        ]
        assert "android.permission.FOREGROUND_SERVICE" in permissions
        assert "android.permission.FOREGROUND_SERVICE_DATA_SYNC" in permissions
        service = tree.find("application/service")
        assert service.get(f"{NS}name") == "org.kivy.android.ServiceDownloader"
        assert service.get(f"{NS}foregroundServiceType") == "dataSync"

    def test_intent_filter_and_raw_xml_substitution(self):
        _, android = _android(
            "[[tool.kivy.android.intent_filters]]\n"
            'action = "android.intent.action.VIEW"\n'
            'data = [{ scheme = "https", host = "example.org" }]\n'
            "\n[tool.kivy.android.manifest]\n"
            "extra_application_xml = '''\n"
            '<provider android:name="x.P" '
            'android:authorities="${applicationId}.fp" '
            'android:exported="false"/>\n'
            "'''\n"
        )
        text, tree = _manifest_tree(android)
        assert "org.example.genapp.fp" in text
        activity = tree.find("application/activity")
        actions = [
            a.get(f"{NS}name")
            for a in activity.findall("intent-filter/action")
        ]
        assert "android.intent.action.MAIN" in actions
        assert "android.intent.action.VIEW" in actions

    def test_passthrough_attr_lands_on_application(self):
        _, android = _android(
            "[tool.kivy.android.manifest]\n"
            'application = { "android:largeHeap" = true }\n'
        )
        _, tree = _manifest_tree(android)
        app = tree.find("application")
        assert app.get(f"{NS}largeHeap") == "true"

    def test_orientation_mapping(self):
        assert screen_orientation(("portrait",)) == "portrait"
        assert (
            screen_orientation(("landscape-left", "landscape-right"))
            == "sensorLandscape"
        )
        assert (
            screen_orientation(
                ("portrait", "landscape-left", "landscape-right")
            )
            == "fullSensor"
        )

    def test_helpers(self):
        assert qualified_permissions(("INTERNET", "android.permission.CAMERA")) == [
            "android.permission.INTERNET",
            "android.permission.CAMERA",
        ]
        assert "android.hardware.nfc" in implied_features(
            ["android.permission.NFC"]
        )


class TestProjectFiles:
    def _lock(self, gradle=GradlePins()):
        return AndroidLockfile(
            requires_python=">=3.14",
            packages=(),
            python_android=(
                PythonAndroidRuntime(
                    version="3.14.6",
                    abi="x86_64",
                    url="https://x/py.tgz",
                    sha256="a" * 64,
                    min_api=24,
                ),
            ),
            kivyforge_version="0",
            generated_at="t",
            pyproject_sha256="b" * 64,
            tool_kivy_android_schema_version=1,
            sdl=2,
            gradle=gradle,
        )

    def test_app_build_gradle_content(self, tmp_path):
        config, android = _android(
            "[tool.kivy.android.gradle]\n"
            'dependencies = ["com.google.zxing:core:3.5.3"]\n'
        )
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "python-runtime",
            staged_libs=["Sdk-3.1.0.aar"],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "applicationId 'org.example.genapp'" in text
        assert "minSdk 24" in text
        assert "abiFilters 'arm64-v8a', 'x86_64'" in text
        assert "{{triplet}}/prefix" in text
        assert "ANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON" in text
        assert "implementation files('libs/Sdk-3.1.0.aar')" in text
        assert "implementation 'com.google.zxing:core:3.5.3'" in text
        assert "useLegacyPackaging = true" in text
        assert "kivyforge-dont-ignore-anything" in text

    def test_determinism(self, tmp_path):
        config, android = _android()
        kwargs = dict(
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        write_app_build_gradle(tmp_path / "a", config, android, **kwargs)
        write_app_build_gradle(tmp_path / "b", config, android, **kwargs)
        assert (tmp_path / "a" / "app" / "build.gradle").read_bytes() == (
            tmp_path / "b" / "app" / "build.gradle"
        ).read_bytes()

    def test_gradle_properties_reserved_managed(self, tmp_path):
        _, android = _android(
            '[tool.kivy.android.gradle_properties]\n"org.gradle.parallel" = true\n'
        )
        write_gradle_properties(tmp_path, android)
        text = (tmp_path / "gradle.properties").read_text()
        assert "android.useAndroidX=true" in text
        assert "org.gradle.parallel=true" in text

    def test_default_icon_emitted_without_config(self, tmp_path):
        config, android = _android()
        write_resources(tmp_path, config, android)
        icon = (
            tmp_path / "app" / "src" / "main" / "res" / "mipmap-mdpi"
            / "ic_launcher.png"
        )
        assert icon.is_file()
        assert icon.read_bytes().startswith(b"\x89PNG")

    def test_gradle_pins_materialization(self, tmp_path):
        pins = GradlePins(
            dependencies=("com.google.zxing:core:3.5.3",),
            resolved=(
                GradleResolvedModule(
                    coordinate="com.google.zxing:core:3.5.3",
                    artifacts=(
                        GradleArtifact(name="core-3.5.3.jar", sha256="c" * 64),
                    ),
                ),
            ),
        )
        write_gradle_pins(tmp_path, self._lock(gradle=pins))
        lockfile = (tmp_path / "app" / "gradle.lockfile").read_text()
        assert "com.google.zxing:core:3.5.3" in lockfile
        # The audit record carries the per-artifact SHA-256 from the lock.
        assert "core-3.5.3.jar" in lockfile
        assert ("c" * 64) in lockfile
        # v1 does not emit a strict verification-metadata.xml (see docstring).
        assert not (tmp_path / "gradle" / "verification-metadata.xml").exists()

    def test_no_pins_no_files(self, tmp_path):
        write_gradle_pins(tmp_path, self._lock())
        assert not (tmp_path / "app" / "gradle.lockfile").exists()
