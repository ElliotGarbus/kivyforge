"""``[project].version`` as declared: static, normalized, or dynamic.

docs/design/dev/dynamic-version-proposal.md section 3.1. Resolving a dynamic
version is ``tests/test_versioning.py``; this file is only what the loader
accepts and rejects, which every verb sees.
"""

from __future__ import annotations

import pytest

from kivyforge.config.errors import ConfigError
from kivyforge.config.loader import load_config_from_text, load_declared_version
from kivyforge.config.model import (
    AutoVersionCode,
    DynamicVersion,
    ResolvedVersion,
    StaticVersion,
)
from kivyforge.config.version import android_version_code, with_version

PROJECT = """\
[project]
name = "demo"
{version_lines}

[tool.kivy]
app_dir = "src"
"""

ANDROID = """
[tool.kivy.android]
schema_version = 1
package = "org.example.demo"
version_code = "auto"
build = 2

[tool.kivy.android.python]
version = "3.14.6"
"""


def load(version_lines: str, extra: str = ""):
    text = PROJECT.format(version_lines=version_lines) + extra
    return load_config_from_text(text, require_ios=False)


class TestStatic:
    @pytest.mark.parametrize(
        ("written", "normalized"),
        [
            ("1.2.3", "1.2.3"),
            ("v1.2", "1.2"),  # the spec: a leading v is omitted from normal forms
            ("V2.0", "2.0"),
            ("1.0-beta", "1.0b0"),
            ("1.0.0-rc.1", "1.0.0rc1"),
            ("1.0+Build-5", "1.0+build.5"),
        ],
    )
    def test_is_held_normalized(self, written, normalized):
        config = load(f'version = "{written}"')
        assert config.project.version == StaticVersion(normalized)
        assert config.version_required == ResolvedVersion(normalized, source="static")

    @pytest.mark.parametrize("written", ["1.0.0-SNAPSHOT", "latest", "2024-10-12"])
    def test_not_pep440_is_an_error_at_its_line(self, written):
        with pytest.raises(ConfigError, match="not a valid version") as exc:
            load(f'version = "{written}"')
        assert exc.value.line == 3
        assert "PEP 440" in (exc.value.hint or "")

    def test_missing_names_dynamic_in_the_hint(self):
        with pytest.raises(ConfigError, match="missing or empty") as exc:
            load("")
        assert "dynamic" in (exc.value.hint or "")


class TestDynamic:
    def test_records_the_backend(self):
        config = load(
            'dynamic = ["version"]',
            '\n[build-system]\nbuild-backend = "hatchling.build"\n',
        )
        assert config.project.version == DynamicVersion("hatchling.build")

    def test_defaults_to_pep517s_backend(self):
        config = load('dynamic = ["version"]')
        assert config.project.version == DynamicVersion(
            "setuptools.build_meta:__legacy__"
        )

    def test_has_no_value_until_resolved(self):
        config = load('dynamic = ["version"]')
        with pytest.raises(RuntimeError, match="dynamic"):
            config.version_required
        resolved = ResolvedVersion("1.2.4.dev1", source="backend")
        assert with_version(config, resolved).version_required is resolved

    def test_set_and_dynamic_is_an_error(self):
        with pytest.raises(ConfigError, match="also listed in dynamic"):
            load('version = "1.0"\ndynamic = ["version"]')

    @pytest.mark.parametrize(
        "field", ["name", "dependencies", "authors", "description", "requires-python"]
    )
    def test_fields_kivyforge_reads_cannot_be_dynamic(self, field):
        # Each would parse as absent: an empty lock, a desktop file with no
        # Comment, Windows resources with no company.
        with pytest.raises(ConfigError, match=f"{field}.* dynamic"):
            load(f'version = "1.0"\ndynamic = ["{field}"]')

    def test_fields_kivyforge_does_not_read_may_be_dynamic(self):
        config = load('version = "1.0"\ndynamic = ["readme", "classifiers"]')
        assert config.project.version == StaticVersion("1.0")

    @pytest.mark.parametrize("value", ['"version"', "[1]"])
    def test_dynamic_must_be_a_list_of_strings(self, value):
        with pytest.raises(ConfigError, match="list of field names"):
            load(f'version = "1.0"\ndynamic = {value}')


class TestAndroidAuto:
    def test_static_prerelease_still_fails_at_load(self):
        # doctor and lock load config; they keep reporting this, as before.
        with pytest.raises(ConfigError, match="final MAJOR.MINOR.PATCH") as exc:
            load('version = "1.0rc1"', ANDROID)
        assert exc.value.line is not None

    def test_dynamic_loads_and_defers_the_code(self):
        config = load('dynamic = ["version"]', ANDROID)
        declared = config.android_required.version_code
        assert isinstance(declared, AutoVersionCode)
        assert declared.build == 2 and declared.line is not None

    def test_code_comes_from_the_resolved_version(self):
        config = load('dynamic = ["version"]', ANDROID)
        built = with_version(config, ResolvedVersion("1.2.3", source="backend"))
        assert android_version_code(built) == 1_020_302

    def test_a_dev_version_fails_at_resolution_with_the_file_line(self):
        config = load('dynamic = ["version"]', ANDROID)
        built = with_version(config, ResolvedVersion("1.2.4.dev1", source="backend"))
        with pytest.raises(ConfigError, match="final MAJOR.MINOR.PATCH") as exc:
            android_version_code(built)
        assert exc.value.line == config.android_required.version_code.line  # type: ignore[union-attr]

    def test_an_override_recomputes_a_static_auto_code(self):
        config = load('version = "1.0.0"', ANDROID)
        built = with_version(config, ResolvedVersion("2.1.0", source="override"))
        assert android_version_code(built) == 2_010_002


class TestDeclarationOnly:
    def test_reads_version_and_scm_file(self, tmp_path):
        path = tmp_path / "pyproject.toml"
        path.write_text(
            '[project]\nname = "d"\ndynamic = ["version"]\n'
            '[tool.setuptools_scm]\nversion_file = "src/_version.py"\n',
            encoding="utf-8",
        )
        declared, scm_file = load_declared_version(path)
        assert declared == DynamicVersion("setuptools.build_meta:__legacy__")
        assert scm_file == "src/_version.py"

    def test_reads_the_older_write_to(self, tmp_path):
        path = tmp_path / "pyproject.toml"
        path.write_text(
            '[project]\nname = "d"\nversion = "1"\n'
            '[tool.setuptools_scm]\nwrite_to = "v.py"\n',
            encoding="utf-8",
        )
        assert load_declared_version(path) == (StaticVersion("1"), "v.py")

    def test_ignores_the_rest_of_the_file(self, tmp_path):
        # The backend validates [tool.kivy]; the verb needs only [project].
        path = tmp_path / "pyproject.toml"
        path.write_text('[project]\nname = "d"\nversion = "1"\n', encoding="utf-8")
        assert load_declared_version(path) == (StaticVersion("1"), None)
