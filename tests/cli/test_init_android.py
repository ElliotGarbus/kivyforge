"""`kivyforge init -p android` — the android/06 §init seeding contract."""

from __future__ import annotations

import tomllib

import pytest
from click.testing import CliRunner

from kivyforge.cli import init as init_mod
from kivyforge.cli.init import init
from kivyforge.config.loader import load_config_from_text


@pytest.fixture
def runner():
    return CliRunner()


PYPROJECT = """[project]
name = "my-app"
version = "1.0.0"
dependencies = ["kivy==2.3.1", "pyjnius"]
"""


def _init_android(runner, tmp_path, text=PYPROJECT, args=()):
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        pp = init_mod.Path(fs) / "pyproject.toml"
        pp.write_text(text)
        result = runner.invoke(init, ["--platform", "android", *args])
        content = pp.read_text()
    return result, content


class TestSeeding:
    def test_seeds_valid_loadable_overlay(self, runner, tmp_path):
        result, content = _init_android(runner, tmp_path)
        assert result.exit_code == 0, result.output
        data = tomllib.loads(content)
        android = data["tool"]["kivy"]["android"]
        assert android["schema_version"] == 1
        assert android["package"] == "org.example.my_app"
        assert android["min_sdk"] == 24
        assert android["kivy_generation"] == 2
        assert android["abis"] == ["arm64_v8a", "x86_64"]
        assert android["python"]["version"] == "3.14.6"
        assert android["permissions"]["uses"] == ["INTERNET"]
        # kivy is a direct dep -> the documented exclude block is seeded
        assert "kivy-garden" in str(android.get("exclude", ""))
        # The seeded file must round-trip through the real loader.
        cfg = load_config_from_text(content, require_ios=False, require_android=True)
        assert cfg.android_required.package == "org.example.my_app"

    def test_seeded_signing_is_commented_stub(self, runner, tmp_path):
        result, content = _init_android(runner, tmp_path)
        assert result.exit_code == 0
        assert '# keystore = "release.keystore"' in content
        assert "KIVYFORGE_KEYSTORE_PASSWORD" in content

    def test_second_init_requires_force(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(PYPROJECT)
            first = runner.invoke(init, ["--platform", "android"])
            assert first.exit_code == 0
            second = runner.invoke(init, ["--platform", "android"])
            assert second.exit_code != 0
            assert "--force" in second.output

    def test_force_preserves_user_values(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(PYPROJECT)
            assert runner.invoke(init, ["--platform", "android"]).exit_code == 0
            text = pp.read_text()
            # User customizes the preserve-set fields (android/06 --force).
            text = text.replace(
                'package = "org.example.my_app"  '
                "# TODO: your applicationId (reverse-DNS)",
                'package = "com.real.app"',
            )
            text = text.replace('version = "3.14.6"', 'version = "3.14.9"')
            text = text.replace(
                '# keystore = "release.keystore"  '
                "# TODO: release keystore (debug builds need none)",
                'keystore = "release.keystore"',
            )
            text = text.replace('# key_alias = "upload"', 'key_alias = "upload"')
            pp.write_text(text)
            result = runner.invoke(init, ["--platform", "android", "--force"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        android = data["tool"]["kivy"]["android"]
        assert android["package"] == "com.real.app"
        assert android["python"]["version"] == "3.14.9"
        assert android["signing"]["keystore"] == "release.keystore"
        assert android["signing"]["key_alias"] == "upload"
