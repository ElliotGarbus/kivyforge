"""Generator unit tests: manifest emission + project files (android/04)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.android.generate import project as project_mod
from kivyforge.platforms.android.generate.manifest import (
    ManifestError,
    generate_manifest,
    implied_features,
    qualified_permissions,
    screen_orientation,
)
from kivyforge.platforms.android.generate.project import (
    ProjectGenError,
    android_abi,
    stage_gradle_wrapper,
    write_app_build_gradle,
    write_gradle_pins,
    write_gradle_properties,
    write_resources,
    write_root_build_gradle,
    write_settings_gradle,
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


class TestReservedApplicationAttrs:
    """<application android:name> is the bootstrap's, not the app author's."""

    def test_android_name_rejected(self):
        _, android = _android(
            '[tool.kivy.android.manifest.application]\n'
            '"android:name" = ".MyApplication"\n'
        )
        with pytest.raises(ManifestError) as exc:
            generate_manifest(android, orientation=("portrait",))
        assert "android:name" in str(exc.value)
        assert "singleton slot" in str(exc.value)

    def test_other_application_attrs_still_pass_through(self):
        _, android = _android(
            '[tool.kivy.android.manifest.application]\n'
            '"android:allowBackup" = false\n'
        )
        _, tree = _manifest_tree(android)
        app = tree.find("application")
        assert app.get(NS + "allowBackup") == "false"
        # The bootstrap keeps the name slot unset rather than ceding it.
        assert app.get(NS + "name") is None


class TestManifest:
    def test_bare_permission_prefixed(self):
        _, android = _android('[tool.kivy.android.permissions]\nuses = ["INTERNET"]\n')
        _, tree = _manifest_tree(android)
        names = [e.get(f"{NS}name") for e in tree.findall("uses-permission")]
        assert names == ["android.permission.INTERNET"]

    def test_implied_features_non_required(self):
        _, android = _android('[tool.kivy.android.permissions]\nuses = ["CAMERA"]\n')
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
        permissions = [e.get(f"{NS}name") for e in tree.findall("uses-permission")]
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
        actions = [a.get(f"{NS}name") for a in activity.findall("intent-filter/action")]
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
            screen_orientation(("portrait", "landscape-left", "landscape-right"))
            == "fullSensor"
        )

    def test_helpers(self):
        assert qualified_permissions(("INTERNET", "android.permission.CAMERA")) == [
            "android.permission.INTERNET",
            "android.permission.CAMERA",
        ]
        assert "android.hardware.nfc" in implied_features(["android.permission.NFC"])


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
            kivy_generation=2,
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
        write_resources(tmp_path, config, android, project_root=tmp_path)
        icon = (
            tmp_path
            / "app"
            / "src"
            / "main"
            / "res"
            / "mipmap-mdpi"
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
                    artifacts=(GradleArtifact(name="core-3.5.3.jar", sha256="c" * 64),),
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
        # And the file says so, at the path a real Gradle lock would live: docs
        # claiming enforcement here is exactly the drift this wording prevents.
        assert "INFORMATIONAL" in lockfile
        assert "dependency locking is not enabled" in lockfile

    def test_no_pins_no_files(self, tmp_path):
        write_gradle_pins(tmp_path, self._lock())
        assert not (tmp_path / "app" / "gradle.lockfile").exists()

    def test_stale_verification_metadata_swept(self, tmp_path):
        stale = tmp_path / "gradle" / "verification-metadata.xml"
        stale.parent.mkdir(parents=True)
        stale.write_text("stale", encoding="utf-8")
        write_gradle_pins(tmp_path, self._lock())
        assert not stale.exists()


class TestAndroidAbi:
    def test_known_abis(self):
        assert android_abi("arm64_v8a") == "arm64-v8a"
        assert android_abi("x86_64") == "x86_64"


class TestWriteSettingsGradle:
    def test_content(self, tmp_path):
        write_settings_gradle(tmp_path)
        text = (tmp_path / "settings.gradle").read_text()
        assert 'rootProject.name = "kivyforge-app"' in text
        assert 'include ":app"' in text
        assert "google()" in text

    def test_declared_repositories_are_emitted(self, tmp_path):
        """A private repo that the lock resolved from must also be declared in
        the generated build, or the coordinate it supplied cannot resolve."""
        _, android = _android(
            "[tool.kivy.android.gradle]\n"
            "dependencies = ['com.example:widget:1.0']\n"
            "repositories = ['https://maven.example.com/releases']\n"
        )
        write_settings_gradle(tmp_path, android)
        text = (tmp_path / "settings.gradle").read_text()
        assert "maven { url = uri('https://maven.example.com/releases') }" in text
        # The defaults stay, and the extra repo comes after them.
        assert text.index("mavenCentral()") < text.index("maven.example.com")

    def test_no_declared_repositories_keeps_the_defaults_only(self, tmp_path):
        _, android = _android()
        write_settings_gradle(tmp_path, android)
        text = (tmp_path / "settings.gradle").read_text()
        assert "maven {" not in text


class TestWriteRootBuildGradle:
    def test_without_kotlin(self, tmp_path):
        _, android = _android()
        write_root_build_gradle(tmp_path, android)
        text = (tmp_path / "build.gradle").read_text()
        assert "com.android.application" in text
        assert "kotlin.android" not in text

    def test_with_kotlin(self, tmp_path):
        _, android = _android("[tool.kivy.android.src]\nkotlin = ['extra/kotlin']\n")
        write_root_build_gradle(tmp_path, android)
        text = (tmp_path / "build.gradle").read_text()
        assert "org.jetbrains.kotlin.android" in text


class TestStageGradleWrapper:
    def test_stages_wrapper_files(self, tmp_path):
        stage_gradle_wrapper(tmp_path)
        assert (tmp_path / "gradle" / "wrapper" / "gradle-wrapper.jar").is_file()
        assert (tmp_path / "gradle" / "wrapper" / "gradle-wrapper.properties").is_file()
        assert (tmp_path / "gradlew").is_file()
        assert (tmp_path / "gradlew.bat").is_file()

    def test_missing_vendored_jar_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            project_mod, "_WRAPPER_DIR", tmp_path / "no-such-wrapper-dir"
        )
        with pytest.raises(ProjectGenError, match="gradle-wrapper.jar missing"):
            stage_gradle_wrapper(tmp_path / "dest")


class TestWriteAppBuildGradleVariants:
    def test_restricted_abi_filter(self, tmp_path):
        config, android = _android()
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
            abis=("x86_64",),
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "abiFilters 'x86_64'" in text
        assert "arm64-v8a" not in text

    def test_kotlin_source_dirs_and_plugin(self, tmp_path):
        config, android = _android(
            "[tool.kivy.android.src]\n"
            "java = ['extra/java']\n"
            "kotlin = ['extra/kotlin']\n"
        )
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "id 'org.jetbrains.kotlin.android'" in text
        assert "java.srcDirs += 'extra/java'" in text
        assert "java.srcDirs += 'extra/kotlin'" in text

    def test_splash_adds_no_dependency(self, tmp_path):
        """The splash is theme attributes and generated drawables, so it must
        not drag a Maven coordinate into an otherwise hermetic build."""
        config, android = _android(
            "[tool.kivy.android.splash]\nsource = 'splash.png'\n"
        )
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "splashscreen" not in text

    @pytest.mark.parametrize(
        "setting,expected",
        [("", "multiDexEnabled true"), ("multidex = false", "multiDexEnabled false")],
    )
    def test_multidex_reaches_gradle(self, tmp_path, setting, expected):
        extra = f"[tool.kivy.android.build_settings]\n{setting}\n" if setting else ""
        config, android = _android(extra)
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        assert expected in (tmp_path / "app" / "build.gradle").read_text()

    def test_lint_runs_only_the_curated_subset_as_fatal(self, tmp_path):
        """checkOnly narrows the run and `fatal` promotes exactly those, so a
        future Lint's new checks can never block someone's release."""
        from kivyforge.platforms.android.policy import LINT_CHECKS

        config, android = _android("")
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        listing = ", ".join(f"'{c}'" for c in LINT_CHECKS)
        assert f"checkOnly.addAll([{listing}])" in text
        assert f"fatal.addAll([{listing}])" in text
        assert "abortOnError = true" in text
        # Not warningsAsErrors: that would make an unknown issue id (a stale
        # pin against a newer Lint) fail every release build.
        assert "warningsAsErrors" not in text

    def test_merged_manifest_export_task_is_emitted(self, tmp_path):
        """The release policy lints the merged manifest, and AGP's intermediates
        layout is not a contract — so export it through the Artifacts API."""
        from kivyforge.platforms.android.generate.project import (
            MERGED_MANIFEST_RELPATH,
            MERGED_MANIFEST_TASK,
        )

        config, android = _android("")
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "import com.android.build.api.artifact.SingleArtifact" in text
        assert f"tasks.register('{MERGED_MANIFEST_TASK}', Copy)" in text
        assert "SingleArtifact.MERGED_MANIFEST.INSTANCE" in text
        assert f"rename {{ '{MERGED_MANIFEST_RELPATH.name}' }}" in text
        # The Copy destination and the path the CLI reads must agree.
        assert "layout.buildDirectory.dir('kivyforge')" in text
        assert MERGED_MANIFEST_RELPATH.parts[:3] == ("app", "build", "kivyforge")

    def test_the_import_precedes_the_plugins_block(self, tmp_path):
        """Groovy requires imports at the top of the script."""
        config, android = _android("")
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert text.startswith("import com.android.build.api.artifact.SingleArtifact")
        assert text.index("import ") < text.index("plugins {")

    def test_strip_native_libs_false_keeps_symbols(self, tmp_path):
        config, android = _android(
            "[tool.kivy.android.build_settings]\nstrip_native_libs = false\n"
        )
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "keepDebugSymbols += ['**/*.so']" in text

    def test_strip_native_libs_default_release_only_omits_keep_symbols(self, tmp_path):
        # Default build_settings.strip_native_libs is the "release" tri-state,
        # which _release_flag treats as stripped (matches ANDROID_RELEASE_ONLY).
        config, android = _android()
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "keepDebugSymbols" not in text

    def test_minify_and_shrink_resources_enabled(self, tmp_path):
        config, android = _android(
            "[tool.kivy.android.build_settings]\n"
            "minify = true\n"
            "shrink_resources = true\n"
        )
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "minifyEnabled true" in text
        assert "shrinkResources true" in text

    def test_debug_symbols_full_and_none(self, tmp_path):
        for level, expected in (("full", "FULL"), ("none", "NONE")):
            config, android = _android(
                f"[tool.kivy.android.build_settings]\ndebug_symbols = '{level}'\n"
            )
            write_app_build_gradle(
                tmp_path / level,
                config,
                android,
                python_version="3.14.6",
                runtime_root=tmp_path / "rt",
                staged_libs=[],
            )
            text = (tmp_path / level / "app" / "build.gradle").read_text()
            assert f"debugSymbolLevel '{expected}'" in text

    def test_signing_config_block_injected(self, tmp_path):
        config, android = _android()
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
            signing_config_block="    signingConfigs {\n        release { }\n    }\n",
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "signingConfig signingConfigs.release" in text
        assert "signingConfigs {" in text

    def test_release_test_variant_for_the_smoke_probe(self, tmp_path):
        """The release smoke test needs testBuildType (AGP generates
        connected<Variant>AndroidTest only for it) and a release signing config
        it can share with the test APK — here the debug keystore."""
        config, android = _android()
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
            release_signing_config="debug",
            test_build_type="release",
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "testBuildType 'release'" in text
        assert "signingConfig signingConfigs.debug" in text
        # No signingConfigs {} block is needed: debug is AGP's built-in config.
        assert "signingConfigs {" not in text

    def test_no_test_build_type_by_default(self, tmp_path):
        config, android = _android()
        write_app_build_gradle(
            tmp_path,
            config,
            android,
            python_version="3.14.6",
            runtime_root=tmp_path / "rt",
            staged_libs=[],
        )
        text = (tmp_path / "app" / "build.gradle").read_text()
        assert "testBuildType" not in text
        assert "signingConfig " not in text


class TestWriteResources:
    def test_base_theme_in_styles_xml(self, tmp_path):
        config, android = _android()
        write_resources(tmp_path, config, android, project_root=tmp_path)
        styles = (
            tmp_path / "app" / "src" / "main" / "res" / "values" / "styles.xml"
        ).read_text()
        assert android.base_theme in styles

    def test_display_name_escaped_in_strings_xml(self, tmp_path):
        text = BASE.replace(
            '[tool.kivy]\napp_dir = "src"',
            '[tool.kivy]\napp_dir = "src"\ndisplay_name = "R&D <App>"',
        )
        config = load_config_from_text(text, require_ios=False, require_android=True)
        android = config.android_required
        write_resources(tmp_path, config, android, project_root=tmp_path)
        strings = (
            tmp_path / "app" / "src" / "main" / "res" / "values" / "strings.xml"
        ).read_text()
        assert "R&amp;D &lt;App&gt;" in strings


class TestPropStr:
    def test_non_bool_value_stringified(self, tmp_path):
        _, android = _android(
            '[tool.kivy.android.gradle_properties]\n"org.gradle.workers.max" = 4\n'
        )
        write_gradle_properties(tmp_path, android)
        text = (tmp_path / "gradle.properties").read_text()
        assert "org.gradle.workers.max=4" in text


class TestGradlePath:
    def test_backslashes_converted_to_forward_slashes(self):
        assert project_mod._gradle_path(Path("a") / "b" / "c") == "a/b/c"
