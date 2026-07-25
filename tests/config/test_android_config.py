"""[tool.kivy.android] loader tests — android/01 validation rules 1-21."""

from __future__ import annotations

import pytest

from kivyforge.config.errors import ConfigError
from kivyforge.config.loader import load_config_from_text

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
        assert a.version_code == 1 and a.version_code_auto is False
        assert (a.min_sdk, a.target_sdk, a.compile_sdk) == (24, 35, 35)
        assert a.sdl == 2
        assert a.abis == ("arm64_v8a", "x86_64")
        assert a.base_theme == "Theme.Material3.DayNight.NoActionBar"
        assert a.python_required.version == "3.14.6"
        assert a.permissions.auto_features is True
        assert a.signing.configured is False
        assert a.signing.v1_signing is False  # min_sdk floor is 24
        assert a.build_settings.multidex is True
        assert a.build_settings.byte_compile == "release"
        assert a.build_settings.debug_symbols == "symbol_table"

    def test_absent_overlay_is_none_unless_required(self):
        text = BASE.split("[tool.kivy.android]")[0]
        cfg = load_config_from_text(text, require_ios=False)
        assert cfg.android is None
        with pytest.raises(ConfigError, match=r"missing \[tool.kivy.android\]"):
            load_config_from_text(text, require_ios=False, require_android=True)

    def test_compile_sdk_defaults_to_target(self):
        a = load_android(with_lines("target_sdk = 34"))
        assert a.compile_sdk == 34


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
            ("rule8-target-lt-min", ["min_sdk = 30", "target_sdk = 29"], "below min_sdk"),
            (
                "rule8-compile-lt-target",
                ["target_sdk = 35", "compile_sdk = 34"],
                "below target_sdk",
            ),
            ("rule9-sdl", ["sdl = 1"], "must be 2 or 3"),
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
                "rule15-managed-application",
                [
                    "[tool.kivy.android.manifest]",
                    'application = { "android:icon" = "@mipmap/x" }',
                ],
                "kivyforge-managed",
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

    def test_rule18_include_files_escape_rejected(self):
        with pytest.raises(ConfigError, match="stay inside"):
            load_android(
                with_lines(
                    "[[tool.kivy.android.include_files]]",
                    'dest = "../outside"',
                    'sources = ["config/a.json"]',
                )
            )


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
        a = load_android(
            text.replace(
                "[tool.kivy.android.python]",
                f'version_code = "auto"\nbuild = {build}\n\n'
                "[tool.kivy.android.python]",
            )
        )
        assert a.version_code == expected
        assert a.version_code_auto is True

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
        assert a.version_code == 7 and a.version_code_auto is False

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
