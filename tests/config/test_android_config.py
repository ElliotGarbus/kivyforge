"""[tool.kivy.android] loader tests — android/01 validation rules 1-22."""

from __future__ import annotations

import pytest

from kivyforge.config.errors import ConfigError
from kivyforge.config.loader import load_config_from_text
from kivyforge.config.model import AutoVersionCode
from kivyforge.config.version import android_version_code

BASE = """
[project]
name = "touchtracer"
version = "1.2.3"
dependencies = ["kivy==2.3.1", "pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.kivy.touchtracer"

[tool.kivy.android.python]
version = "3.14.6"
"""


def load(text: str):
    return load_config_from_text(text, require_ios=False, require_android=True)


def load_android(text: str):
    return load(text).android_required


def with_lines(*lines: str) -> str:
    """BASE with extra lines appended to [tool.kivy.android] (before .python)."""
    marker = "\n[tool.kivy.android.python]"
    return BASE.replace(marker, "\n" + "\n".join(lines) + marker)


class TestDefaults:
    def test_minimal_overlay_defaults(self):
        a = load_android(BASE)
        assert a.schema_version == 1
        assert a.package == "org.kivy.touchtracer"
        assert a.version_code == 1
        assert (a.min_sdk, a.target_sdk, a.compile_sdk) == (24, 35, 35)
        assert a.kivy_generation == 2
        assert a.abis == ("arm64_v8a", "x86_64")
        assert a.base_theme == "Theme.Material3.DayNight.NoActionBar"
        assert a.fullscreen is False
        assert a.python_required.version == "3.14.6"
        assert a.permissions.auto_features is True
        assert a.signing.configured is False
        assert a.signing.v1_signing is False  # min_sdk floor is 24
        assert a.build_settings.multidex is True
        assert a.build_settings.byte_compile == "release"
        assert a.build_settings.debug_symbols == "symbol_table"

    def test_fullscreen_true(self):
        assert load_android(with_lines("fullscreen = true")).fullscreen is True

    def test_absent_overlay_is_none_unless_required(self):
        text = BASE.split("[tool.kivy.android]")[0]
        cfg = load_config_from_text(text, require_ios=False)
        assert cfg.android is None
        with pytest.raises(ConfigError, match=r"missing \[tool.kivy.android\]"):
            load_config_from_text(text, require_ios=False, require_android=True)

    def test_compile_sdk_defaults_to_target(self):
        a = load_android(with_lines("target_sdk = 34"))
        assert a.compile_sdk == 34

    def test_allow_exported_defaults_empty_and_round_trips(self):
        assert load_android(BASE).manifest.allow_exported == ()
        a = load_android(
            BASE + "\n[tool.kivy.android.manifest]\n"
            'allow_exported = ["com.vendor.sdk.Trampoline"]\n'
        )
        assert a.manifest.allow_exported == ("com.vendor.sdk.Trampoline",)


class TestRuleRejections:
    """One test per android/01 validation rule this layer owns."""

    @pytest.mark.parametrize(
        ("label", "bad_package"),
        [("rule4-no-dots", "noDots"), ("rule4-bad-segment", "org.9bad.app")],
    )
    def test_rule4_package_rejected(self, label, bad_package):
        text = BASE.replace(
            'package = "org.kivy.touchtracer"', f'package = "{bad_package}"'
        )
        with pytest.raises(ConfigError, match="package"):
            load_android(text)

    @pytest.mark.parametrize(
        ("label", "lines", "match"),
        [
            # rule 3 handled by shared schema_version parser (see below)
            ("rule8-min-floor", ["min_sdk = 23"], "below the floor"),
            (
                "rule8-target-lt-min",
                ["min_sdk = 30", "target_sdk = 29"],
                "below min_sdk",
            ),
            (
                "rule8-compile-lt-target",
                ["target_sdk = 35", "compile_sdk = 34"],
                "below target_sdk",
            ),
            ("rule9-sdl", ["kivy_generation = 1"], "must be 2 or 3"),
            ("rule10-abis-empty", ["abis = []"], "must not be empty"),
            ("rule10-abis-32bit", ['abis = ["x86"]'], "unsupported Android ABI"),
            (
                "rule13-gradle-dynamic",
                ["[tool.kivy.android.gradle]", 'dependencies = ["a.b:c:+"]'],
                "fully-versioned",
            ),
            (
                "rule13-gradle-two-part",
                ["[tool.kivy.android.gradle]", 'dependencies = ["a.b:c"]'],
                "fully-versioned",
            ),
            (
                "rule13-gradle-bom-dynamic",
                [
                    "[tool.kivy.android.gradle]",
                    'platforms = ["a.b:bom:1.+"]',
                    'dependencies = ["a.b:c"]',
                ],
                "BOM coordinate",
            ),
            (
                "rule13-gradle-bom-two-part",
                ["[tool.kivy.android.gradle]", 'platforms = ["a.b:bom"]'],
                "BOM coordinate",
            ),
            (
                "rule13-gradle-plugins-not-table",
                ["[tool.kivy.android.gradle]", 'plugins = ["a.b:1.0"]'],
                "must be a table",
            ),
            (
                "rule13-gradle-plugin-bare-dotted-key",
                [
                    "[tool.kivy.android.gradle.plugins]",
                    'com.google.gms.google-services = "4.4.2"',
                ],
                "read as a table",
            ),
            (
                "rule13-gradle-plugin-bad-id",
                ["[tool.kivy.android.gradle.plugins]", 'nodots = "1.0"'],
                "not a\\s+Gradle plugin id",
            ),
            (
                "rule13-gradle-plugin-managed",
                [
                    "[tool.kivy.android.gradle.plugins]",
                    '"com.android.application" = "8.10.0"',
                ],
                "applied by kivyforge itself",
            ),
            (
                "rule13-gradle-plugin-dynamic",
                ["[tool.kivy.android.gradle.plugins]", '"a.b" = "1.+"'],
                "exact version",
            ),
            (
                "rule13-gradle-plugin-not-string",
                ["[tool.kivy.android.gradle.plugins]", '"a.b" = 4'],
                "exact version",
            ),
            (
                "rule15-managed-application",
                [
                    "[tool.kivy.android.manifest]",
                    'application = { "android:icon" = "@mipmap/x" }',
                ],
                "kivyforge-managed",
            ),
            (
                "rule15-merger-directive-in-attribute-table",
                [
                    "[tool.kivy.android.manifest]",
                    'activity = { "tools:node" = "remove" }',
                ],
                "'tools' namespace",
            ),
            (
                "rule15-reserved-gradle-prop",
                [
                    "[tool.kivy.android.gradle_properties]",
                    '"android.useAndroidX" = false',
                ],
                "kivyforge-reserved",
            ),
            (
                "rule17-malformed-xml",
                [
                    "[tool.kivy.android.manifest]",
                    'extra_manifest_xml = "<queries><intent></queries>"',
                ],
                "not well-formed",
            ),
            (
                "allow-exported-not-a-list",
                [
                    "[tool.kivy.android.manifest]",
                    'allow_exported = "com.vendor.sdk.Trampoline"',
                ],
                "list of\\s+non-empty component class names",
            ),
            (
                "allow-exported-empty-entry",
                ["[tool.kivy.android.manifest]", 'allow_exported = ["", "a.B"]'],
                "list of\\s+non-empty component class names",
            ),
            (
                "rule19-bad-tristate",
                ["[tool.kivy.android.build_settings]", 'byte_compile = "always"'],
                'bool or the\\s+string "release"',
            ),
            (
                "rule19-bad-symbols",
                ["[tool.kivy.android.build_settings]", 'debug_symbols = "dwarf"'],
                "debug_symbols",
            ),
            (
                "rule19-shrink-without-minify",
                ["[tool.kivy.android.build_settings]", "shrink_resources = true"],
                "requires\\s+minify",
            ),
            (
                "rule21-bad-theme",
                ['base_theme = ""'],
                "base_theme",
            ),
            (
                # bool("false") is True: a string must not silently enable it.
                "fullscreen-not-bool",
                ['fullscreen = "false"'],
                "fullscreen.*boolean",
            ),
            (
                "rule21-splash-color",
                ["[tool.kivy.android.splash]", 'background = "black"'],
                "#rrggbb",
            ),
            (
                "rule21-splash-duration",
                ["[tool.kivy.android.splash]", "animation_duration = 0"],
                "positive",
            ),
            (
                "rule21-splash-escape",
                ["[tool.kivy.android.splash]", 'source = "../../evil.png"'],
                "escapes the project",
            ),
        ],
    )
    def test_rejected(self, label, lines, match):
        with pytest.raises(ConfigError, match=match):
            load_android(with_lines(*lines))

    def test_rule3_schema_version_required_and_bounded(self):
        with pytest.raises(ConfigError):
            load_android(BASE.replace("schema_version = 1\n", ""))
        with pytest.raises(ConfigError):
            load_android(BASE.replace("schema_version = 1", "schema_version = 99"))

    def test_rule11_python_version_required(self):
        text = BASE.replace('version = "3.14.6"', 'other = "x"')
        with pytest.raises(ConfigError, match="python"):
            load_android(text)

    def test_rule12_find_links_absolute_rejected(self):
        # Deeper ../-escape scoping requires a project_root (validated on the
        # load_config path); absolute paths are rejected unconditionally.
        with pytest.raises(ConfigError, match="repo-relative"):
            load_android(with_lines('find_links = ["/abs/wheels"]'))

    def test_rule14_archive_absolute_source_rejected(self):
        with pytest.raises(ConfigError):
            load_android(
                with_lines(
                    "[tool.kivy.android.native.jars]",
                    'x = { version = "1.0", source = "/abs/x.jar" }',
                )
            )

    @pytest.mark.parametrize("key", ["java", "kotlin"])
    def test_rule14_src_root_must_exist(self, tmp_path, key):
        """Gradle compiles nothing from a missing srcDir and says nothing, so
        the loader is the last place a typo can fail loudly."""
        text = BASE + f'\n[tool.kivy.android.src]\n{key} = ["android/{key}"]\n'
        with pytest.raises(ConfigError, match="does not exist") as excinfo:
            load_config_from_text(
                text, require_ios=False, require_android=True, project_root=tmp_path
            )
        assert excinfo.value.key_path == f"tool.kivy.android.src.{key}"
        assert "relative to the project root" in (excinfo.value.hint or "")

    def test_rule14_src_root_must_be_a_directory(self, tmp_path):
        (tmp_path / "Main.java").write_text("class Main {}\n", encoding="utf-8")
        text = BASE + '\n[tool.kivy.android.src]\njava = ["Main.java"]\n'
        with pytest.raises(ConfigError, match="is not a directory"):
            load_config_from_text(
                text, require_ios=False, require_android=True, project_root=tmp_path
            )

    def test_rule14_existing_src_roots_load(self, tmp_path):
        (tmp_path / "android" / "java").mkdir(parents=True)
        (tmp_path / "android" / "kotlin").mkdir(parents=True)
        text = (
            BASE + "\n[tool.kivy.android.src]\n"
            'java = ["android/java"]\nkotlin = ["android/kotlin"]\n'
        )
        android = load_config_from_text(
            text, require_ios=False, require_android=True, project_root=tmp_path
        ).android_required
        assert android.src.java == ("android/java",)
        assert android.src.kotlin == ("android/kotlin",)

    def test_rule14_src_root_escape_rejected(self):
        with pytest.raises(ConfigError, match="escapes"):
            load_android(BASE + '\n[tool.kivy.android.src]\njava = ["../java"]\n')

    def test_rule18_include_files_escape_rejected(self):
        with pytest.raises(ConfigError, match="stay inside"):
            load_android(
                with_lines(
                    "[[tool.kivy.android.include_files]]",
                    'dest = "../outside"',
                    'sources = ["config/a.json"]',
                )
            )


class TestMainActivity:
    """Rule 22: [tool.kivy.android].main_activity names the launcher."""

    def test_absent_is_none(self):
        assert load_android(BASE).main_activity is None

    def test_a_fully_qualified_subclass_loads(self):
        a = load_android(with_lines('main_activity = "org.kivy.touchtracer.Main"'))
        assert a.main_activity == "org.kivy.touchtracer.Main"

    def test_a_class_outside_the_app_package_loads(self):
        """A shared library's activity lives in its own package; only the
        bootstrap's namespaces are reserved."""
        a = load_android(with_lines('main_activity = "com.vendor.ui.HostActivity"'))
        assert a.main_activity == "com.vendor.ui.HostActivity"

    def test_the_default_spelled_out_normalises_to_none(self):
        """Writing the default is not a customisation: no verifier, no change
        to anything generated."""
        a = load_android(
            with_lines('main_activity = "org.kivy.android.PythonActivity"')
        )
        assert a.main_activity is None

    @pytest.mark.parametrize(
        ("value", "match"),
        [
            ('""', "fully qualified"),
            ("3", "fully qualified"),
            ('"MainActivity"', "fully qualified"),
            ('"org.example.9Main"', "fully qualified"),
            ('"org.example.Main Activity"', "fully qualified"),
            ('"org.example."', "fully qualified"),
            ('"org.example.Outer$Inner"', "nested class"),
        ],
    )
    def test_a_name_that_is_not_a_java_class_is_rejected(self, value, match):
        with pytest.raises(ConfigError, match=match) as excinfo:
            load_android(with_lines(f"main_activity = {value}"))
        assert excinfo.value.key_path == "tool.kivy.android.main_activity"

    def test_the_manifest_shorthand_is_rejected_with_the_spelling(self):
        """`.MainActivity` is legal in a hand-written manifest, where it is
        resolved against the namespace; here it would be a typo kivyforge
        guessed at."""
        with pytest.raises(ConfigError) as excinfo:
            load_android(with_lines('main_activity = ".MainActivity"'))
        assert "org.kivy.touchtracer.MainActivity" in (excinfo.value.hint or "")

    @pytest.mark.parametrize(
        "value",
        [
            "org.kivy.android.MainActivity",
            "org.kivy.android.sub.MainActivity",
            "org.libsdl.app.SDLActivity",
            "org.jnius.NativeInvocationHandler",
            "org.renpy.android.Hardware",
        ],
    )
    def test_a_class_in_a_bootstrap_namespace_is_rejected(self, value):
        """kivyforge generates those packages; a class of the app's there would
        collide with, or be overwritten by, the bootstrap."""
        with pytest.raises(ConfigError, match="bootstrap") as excinfo:
            load_android(with_lines(f'main_activity = "{value}"'))
        assert "org.kivy.touchtracer.MainActivity" in (excinfo.value.hint or "")

    def test_a_namespace_prefix_that_is_not_a_segment_is_not_reserved(self):
        a = load_android(with_lines('main_activity = "org.kivy.androidx.Main"'))
        assert a.main_activity == "org.kivy.androidx.Main"

    def test_the_activity_name_override_points_at_main_activity(self):
        with pytest.raises(ConfigError, match="kivyforge-managed") as excinfo:
            load_android(
                with_lines(
                    "[tool.kivy.android.manifest]",
                    'activity = { "android:name" = "org.x.Main" }',
                )
            )
        assert "[tool.kivy.android].main_activity" in (excinfo.value.hint or "")


class TestVersionCode:
    """Rule 20: the auto-derivation table from android/01."""

    @pytest.mark.parametrize(
        ("version", "build", "expected"),
        [
            ("1.0.0", 0, 1_000_000),
            ("1.2.3", 0, 1_020_300),
            ("1.2.3", 4, 1_020_304),
            ("2.0.0", 0, 2_000_000),
            ("1.2", 0, 1_020_000),  # missing PATCH -> 0
            ("2099.99.99", 99, 2_099_999_999),  # just under the ceiling
        ],
    )
    def test_auto_table(self, version, build, expected):
        text = BASE.replace('version = "1.2.3"', f'version = "{version}"', 1)
        config = load(
            text.replace(
                "[tool.kivy.android.python]",
                f'version_code = "auto"\nbuild = {build}\n\n[tool.kivy.android.python]',
            )
        )
        assert isinstance(config.android_required.version_code, AutoVersionCode)
        assert android_version_code(config) == expected

    @pytest.mark.parametrize(
        ("version", "match"),
        [
            ("1.2.3rc1", "final"),
            ("1.2.3.dev1", "final"),
            ("1.2.3.post1", "final"),
            ("1.2.3+local", "final"),
            ("1!1.2.3", "final"),
            ("1.2.3.4", "4th numeric"),
            ("1.100.0", "<= 99"),
        ],
    )
    def test_auto_rejections(self, version, match):
        text = BASE.replace('version = "1.2.3"', f'version = "{version}"', 1)
        with pytest.raises(ConfigError, match=match):
            load_android(
                text.replace(
                    "[tool.kivy.android.python]",
                    'version_code = "auto"\n\n[tool.kivy.android.python]',
                )
            )

    def test_auto_overflow_rejected(self):
        # 2100.0.0 derives to exactly the 2,100,000,000 ceiling (allowed);
        # 2101.0.0 exceeds it.
        text = BASE.replace('version = "1.2.3"', 'version = "2101.0.0"', 1)
        with pytest.raises(ConfigError, match="ceiling"):
            load_android(
                text.replace(
                    "[tool.kivy.android.python]",
                    'version_code = "auto"\n\n[tool.kivy.android.python]',
                )
            )

    def test_explicit_integer_ignores_build(self):
        a = load_android(with_lines("version_code = 7", "build = 55"))
        assert a.version_code == 7

    def test_bad_types_rejected(self):
        for value in ('"latest"', "0", "-3", "true"):
            with pytest.raises(ConfigError):
                load_android(with_lines(f"version_code = {value}"))
        with pytest.raises(ConfigError):
            load_android(with_lines("build = 100"))


class TestServices:
    def test_foreground_requires_type_and_notification(self):
        base_service = [
            "[[tool.kivy.android.services]]",
            'name = "Downloader"',
            'entry_point = "svc"',
            "foreground = true",
        ]
        with pytest.raises(ConfigError, match="foreground_service_type"):
            load_android(with_lines(*base_service))
        with pytest.raises(ConfigError, match="notification"):
            load_android(
                with_lines(*base_service, 'foreground_service_type = "dataSync"')
            )
        a = load_android(
            with_lines(
                *base_service,
                'foreground_service_type = "dataSync"',
                'notification = { channel_id = "c", channel_name = "C", '
                'title = "t", text = "x" }',
            )
        )
        svc = a.services[0]
        assert svc.foreground_service_type == "dataSync"
        assert svc.notification is not None and svc.notification.channel_id == "c"

    def test_background_service_rejects_foreground_fields(self):
        with pytest.raises(ConfigError, match="only\\s+meaningful"):
            load_android(
                with_lines(
                    "[[tool.kivy.android.services]]",
                    'name = "Bg"',
                    'entry_point = "svc"',
                    'foreground_service_type = "dataSync"',
                )
            )

    def test_media_processing_accepted(self):
        a = load_android(
            with_lines(
                "[[tool.kivy.android.services]]",
                'name = "Enc"',
                'entry_point = "enc"',
                "foreground = true",
                'foreground_service_type = "mediaProcessing"',
                'notification = { channel_id = "c", channel_name = "C", '
                'title = "t", text = "x" }',
            )
        )
        assert a.services[0].foreground_service_type == "mediaProcessing"


class TestPassthroughs:
    def test_intent_filter_unknown_data_key_rejected(self):
        with pytest.raises(ConfigError, match="unknown attribute"):
            load_android(
                with_lines(
                    "[[tool.kivy.android.intent_filters]]",
                    'action = "android.intent.action.VIEW"',
                    'data = [{ scheme = "https", bogus = "x" }]',
                )
            )

    def test_valid_intent_filter(self):
        a = load_android(
            with_lines(
                "[[tool.kivy.android.intent_filters]]",
                'action = "android.intent.action.VIEW"',
                'categories = ["android.intent.category.BROWSABLE"]',
                'data = [{ scheme = "https", host = "example.org" }]',
            )
        )
        assert a.intent_filters[0].data[0]["host"] == "example.org"

    def test_well_formed_xml_fragments_accepted(self):
        a = load_android(
            with_lines(
                "[tool.kivy.android.manifest]",
                "extra_application_xml = '''",
                '<receiver android:name="org.example.R" android:exported="false"/>',
                "'''",
            )
        )
        assert "receiver" in a.manifest.extra_application_xml

    def test_archives_parsed_with_kind(self):
        a = load_android(
            with_lines(
                "[tool.kivy.android.native.aars]",
                'Sdk = { version = "3.1.0", source = "libs/Sdk-3.1.0.aar" }',
                "[tool.kivy.android.native.jars]",
                'util = { version = "1.4.0", source = "libs/util-1.4.0.jar" }',
            )
        )
        assert a.aars[0].kind == "aar" and a.jars[0].kind == "jar"

    def test_gradle_coordinates_accepted(self):
        a = load_android(
            with_lines(
                "[tool.kivy.android.gradle]",
                'dependencies = ["com.google.zxing:core:3.5.3"]',
                'repositories = ["https://maven.example.com/releases"]',
            )
        )
        assert a.gradle.dependencies == ("com.google.zxing:core:3.5.3",)

    def test_bom_allows_versionless_dependencies(self):
        a = load_android(
            with_lines(
                "[tool.kivy.android.gradle]",
                'platforms = ["com.google.firebase:firebase-bom:34.0.0"]',
                "dependencies = [",
                '    "com.google.firebase:firebase-analytics",',
                '    "com.google.zxing:core:3.5.3",',
                "]",
            )
        )
        assert a.gradle.platforms == ("com.google.firebase:firebase-bom:34.0.0",)
        assert a.gradle.dependencies == (
            "com.google.firebase:firebase-analytics",
            "com.google.zxing:core:3.5.3",
        )

    def test_bom_does_not_excuse_dynamic_versions(self):
        with pytest.raises(ConfigError, match="fully-versioned"):
            load_android(
                with_lines(
                    "[tool.kivy.android.gradle]",
                    'platforms = ["com.google.firebase:firebase-bom:34.0.0"]',
                    'dependencies = ["com.google.firebase:firebase-analytics:+"]',
                )
            )

    def test_versionless_without_bom_hint_names_platforms(self):
        with pytest.raises(ConfigError) as info:
            load_android(
                with_lines(
                    "[tool.kivy.android.gradle]",
                    'dependencies = ["com.google.firebase:firebase-analytics"]',
                )
            )
        assert "platforms" in (info.value.hint or "")

    def test_plugins_keep_declared_order(self):
        a = load_android(
            with_lines(
                "[tool.kivy.android.gradle.plugins]",
                '"com.google.gms.google-services" = "4.4.2"',
                '"com.google.firebase.crashlytics" = "3.0.2"',
            )
        )
        assert a.gradle.plugins == (
            ("com.google.gms.google-services", "4.4.2"),
            ("com.google.firebase.crashlytics", "3.0.2"),
        )
