"""Phase 2 — kivyforge init: update path and invariants (spec 05)."""

from __future__ import annotations

import textwrap
import tomllib

import pytest
from click.testing import CliRunner

from kivyforge.cli import init as init_mod
from kivyforge.cli.init import init
from kivyforge.cli.init_writer import (
    bundle_id_segment,
    has_kivy_dep,
    has_platform_overlay,
    has_shared_table,
    normalize_package_name,
    render_kivy_tables,
    render_linux_tables,
    render_macos_tables,
    strip_kivy_tables,
    strip_platform_tables,
)
from kivyforge.config.model import SigningConfig


@pytest.fixture
def runner():
    return CliRunner()


class TestWriterUnits:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("My App", "my_app"),
            ("kivy-ios", "kivy_ios"),
            ("123abc", "app_123abc"),
            ("Touch.Tracer", "touch_tracer"),
            ("   ", "app"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_package_name(raw) == expected

    @pytest.mark.parametrize(
        "slug,expected",
        [
            ("hello_world", "hello-world"),
            ("myapp", "myapp"),
            ("app_123abc", "app-123abc"),
            ("touch_tracer", "touch-tracer"),
        ],
    )
    def test_bundle_id_segment(self, slug, expected):
        assert bundle_id_segment(slug) == expected

    def test_render_kivy_tables_bundle_id_has_no_underscore(self):
        block = render_kivy_tables("hello_world")
        assert 'bundle_id = "org.example.hello-world"' in block
        assert "hello_world" not in block.split("bundle_id", 1)[1].split("\n", 1)[0]

    def test_render_kivy_tables_template(self):
        block = render_kivy_tables("myapp")
        assert "[tool.kivy.ios]" in block
        assert 'bundle_id = "org.example.myapp"' in block
        assert "auto_signing = true" in block
        # template (no signing) must invite team_id, not hardcode it
        assert "TODO: set your Apple Developer Team ID" in block
        # without has_kivy there must be no exclude block
        assert "exclude" not in block

    def test_render_kivy_tables_seeds_icons_and_splash(self):
        block = render_kivy_tables("myapp")
        assert "[tool.kivy.ios.icons]" in block
        assert "[tool.kivy.ios.splash]" in block
        # icon is required for App Store submission; surface it as a TODO
        assert '# source = "assets/icon.png"' in block
        assert "App Store" in block
        assert '# source = "assets/splash.png"' in block
        assert "# background = " in block

    def test_render_kivy_tables_seeds_commented_simulator_archs(self):
        block = render_kivy_tables("myapp")
        # commented so the default (both arches) stays in effect until edited
        assert '# simulator_archs = ["arm64"]' in block

    def test_render_kivy_tables_seeds_commented_swift_packages(self):
        block = render_kivy_tables("myapp")
        # commented so a vanilla app needs no Swift toolchain until edited
        assert "# [tool.kivy.ios.native.swift_packages]" in block
        assert "sentry-cocoa" in block
        # the stub must stay inert: no active swift_packages table parsed
        from kivyforge.config import load_config_from_text

        cfg = load_config_from_text(
            '[project]\nname = "myapp"\nversion = "1.0.0"\n\n' + block
        )
        assert cfg.ios_required.swift_packages == ()

    @pytest.mark.parametrize("has_kivy", [False, True])
    def test_render_kivy_tables_roundtrips_through_loader(self, has_kivy):
        from kivyforge.config import load_config_from_text

        project = (
            "[project]\n"
            'name = "myapp"\n'
            'version = "1.0.0"\n'
            'dependencies = ["kivy>=3.0"]\n\n'
        )
        block = render_kivy_tables("myapp", has_kivy=has_kivy)
        cfg = load_config_from_text(project + block)
        ios = cfg.ios_required
        # commented entries leave defaults in place
        assert ios.simulator_archs == ("arm64", "x86_64")
        assert ios.icons.source is None
        assert ios.splash.source is None

    def test_render_kivy_tables_with_kivy_exclude(self):
        block = render_kivy_tables("myapp", has_kivy=True)
        assert "exclude = [" in block
        assert '"kivy-garden"' in block
        assert '"requests"' in block
        assert '"docutils"' in block
        assert '"pygments"' in block
        # each entry is annotated with its Kivy feature
        assert "RSTDocument" in block
        assert "CodeInput" in block
        assert "UrlRequest" in block
        # block is valid TOML
        import tomllib

        data = tomllib.loads(block)
        assert "kivy-garden" in data["tool"]["kivy"]["ios"]["exclude"]
        assert "docutils" in data["tool"]["kivy"]["ios"]["exclude"]

    @pytest.mark.parametrize(
        "dep,expected",
        [
            ("kivy>=3.0", True),
            ("Kivy==3.0.0", True),
            ("kivy[base]>=3.0", True),
            ("numpy>=2", False),
            ("kivy-garden>=0.1", False),  # kivy-garden is not kivy
        ],
    )
    def test_has_kivy_dep(self, dep, expected):
        assert has_kivy_dep([dep]) is expected

    def test_render_kivy_tables_preserves_signing(self):
        signing = SigningConfig(team_id="ABCDE12345", auto_signing=False)
        block = render_kivy_tables("myapp", signing=signing)
        assert 'team_id = "ABCDE12345"' in block
        assert "auto_signing = false" in block

    def test_strip_kivy_tables_keeps_project(self):
        text = textwrap.dedent(
            """
            [project]
            name = "x"  # keep this comment
            version = "1.0"

            [tool.poetry]
            foo = 1

            [tool.kivy]
            app_dir = "src"

            [tool.kivy.ios]
            schema_version = 1
            """
        ).strip()
        out = strip_kivy_tables(text)
        assert "[project]" in out
        assert "keep this comment" in out
        assert "[tool.poetry]" in out
        assert "[tool.kivy]" not in out
        assert "[tool.kivy.ios]" not in out

    def test_render_macos_tables_template(self):
        block = render_macos_tables("myapp")
        assert "[tool.kivy]" in block  # include_shared defaults to True
        assert "[tool.kivy.macos]" in block
        assert 'bundle_id = "org.example.myapp"' in block
        assert "[tool.kivy.macos.python]" in block
        assert "[tool.kivy.macos.signing]" in block
        assert "exclude" not in block
        # valid, loadable TOML
        from kivyforge.config import load_config_from_text

        cfg = load_config_from_text(
            '[project]\nname = "myapp"\nversion = "1.0.0"\n\n' + block,
            require_ios=False,
            require_macos=True,
        )
        assert cfg.macos_required.bundle_id == "org.example.myapp"

    def test_render_macos_tables_omits_shared_when_requested(self):
        block = render_macos_tables("myapp", include_shared=False)
        assert "[tool.kivy]" not in block
        assert "[tool.kivy.macos]" in block

    def test_render_macos_tables_preserves_signing(self):
        from kivyforge.config.model import MacosSigningConfig

        signing = MacosSigningConfig(
            identity="Developer ID Application: Jane Doe (TEAM123456)",
            team_id="TEAM123456",
            notary_profile="my-profile",
        )
        block = render_macos_tables("myapp", signing=signing)
        assert 'identity = "Developer ID Application: Jane Doe (TEAM123456)"' in block
        assert 'team_id = "TEAM123456"' in block
        assert 'notary_profile = "my-profile"' in block

    def test_render_macos_tables_with_kivy_exclude(self):
        block = render_macos_tables("myapp", has_kivy=True)
        assert "exclude = [" in block
        assert '"kivy-garden"' in block

    def test_render_linux_tables_template(self):
        block = render_linux_tables("myapp")
        assert "[tool.kivy]" in block
        assert "[tool.kivy.linux]" in block
        assert 'app_id = "org.example.myapp"' in block
        assert "[tool.kivy.linux.python]" in block
        assert "[tool.kivy.linux.desktop]" in block
        assert 'categories = ["Utility"]' in block
        from kivyforge.config import load_config_from_text

        cfg = load_config_from_text(
            '[project]\nname = "myapp"\nversion = "1.0.0"\n\n' + block,
            require_ios=False,
            require_linux=True,
        )
        assert cfg.linux_required.app_id == "org.example.myapp"

    def test_render_linux_tables_omits_shared_when_requested(self):
        block = render_linux_tables("myapp", include_shared=False)
        assert "[tool.kivy]" not in block
        assert "[tool.kivy.linux]" in block

    def test_has_shared_table(self):
        assert has_shared_table("[tool.kivy]\napp_dir = 'src'\n")
        assert not has_shared_table("[tool.kivy.ios]\nschema_version = 1\n")

    def test_has_platform_overlay(self):
        text = "[tool.kivy]\napp_dir = 'src'\n\n[tool.kivy.macos]\nschema_version = 1\n"
        assert has_platform_overlay(text, "macos")
        assert not has_platform_overlay(text, "ios")
        assert not has_platform_overlay(text, "linux")

    def test_has_platform_overlay_matches_subtables(self):
        text = "[tool.kivy.ios.signing]\nteam_id = 'ABCDE12345'\n"
        assert has_platform_overlay(text, "ios")

    def test_strip_platform_tables_preserves_other_platforms(self):
        text = textwrap.dedent(
            """
            [project]
            name = "x"

            [tool.kivy]
            app_dir = "src"

            [tool.kivy.macos]
            schema_version = 1

            [tool.kivy.macos.python]
            version = "3.13.14"

            [tool.kivy.ios]
            schema_version = 1
            """
        ).strip()
        out = strip_platform_tables(text, "macos")
        assert "[tool.kivy]" in out
        assert "[tool.kivy.macos]" not in out
        assert "[tool.kivy.macos.python]" not in out
        assert "[tool.kivy.ios]" in out


class TestNoManifest:
    def test_no_pyproject_no_requirements_errors(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init, [])
        assert result.exit_code != 0
        assert "no pyproject.toml" in result.output
        assert "packaging.python.org" in result.output

    def test_requirements_only_shows_migration_message(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (init_mod.Path(fs) / "requirements.txt").write_text("kivy\nnumpy>=2\n")
            result = runner.invoke(init, [])
        assert result.exit_code != 0
        assert "requirements.txt found" in result.output
        assert "pyproject.toml" in result.output


class TestUpdatePath:
    PYPROJECT = textwrap.dedent(
        """
        [project]
        name = "existing-app"  # keep me
        version = "2.5.0"
        dependencies = ["kivy>=3.0"]

        [tool.black]
        line-length = 100
        """
    ).strip()

    def test_update_appends_kivy_tables(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT + "\n")
            result = runner.invoke(init, [])
            assert result.exit_code == 0, result.output
            text = pp.read_text()
            data = tomllib.loads(text)
        # [project] untouched, comment preserved
        assert data["project"]["version"] == "2.5.0"
        assert "keep me" in text
        assert data["tool"]["black"]["line-length"] == 100
        # kivy tables added, bundle_id derived from project name (underscores
        # in the slug become hyphens — bundle IDs disallow underscores)
        assert data["tool"]["kivy"]["ios"]["bundle_id"] == "org.example.existing-app"

    def test_update_with_kivy_generates_exclude_block(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT + "\n")
            result = runner.invoke(init, [])
            assert result.exit_code == 0, result.output
            text = pp.read_text()
        assert "exclude = [" in text
        assert '"pygments"' in text
        assert "CodeInput" in text

    def test_update_refuses_without_force(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT + "\n")
            runner.invoke(init, [])  # first add
            result = runner.invoke(init, [])  # second without force
        assert result.exit_code != 0
        assert "--force" in result.output

    def test_force_preserves_signing(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT + "\n")
            runner.invoke(init, [])
            # user fills in signing
            text = pp.read_text().replace(
                "auto_signing = true", 'team_id = "TEAM123456"\nauto_signing = true'
            )
            pp.write_text(text)
            result = runner.invoke(init, ["--force"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert data["tool"]["kivy"]["ios"]["signing"]["team_id"] == "TEAM123456"

    def test_force_preserves_python_version(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT + "\n")
            runner.invoke(init, [])
            text = pp.read_text().replace(
                'version = "3.15.0b2"', 'version = "3.15.0b1"'
            )
            pp.write_text(text)
            result = runner.invoke(init, ["--force"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert data["tool"]["kivy"]["ios"]["python"]["version"] == "3.15.0b1"

    def test_force_preserves_icon_splash_and_simulator_archs(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT + "\n")
            runner.invoke(init, [])
            # User fills in the commented stubs with real values.
            text = pp.read_text()
            text = text.replace(
                '# simulator_archs = ["arm64"]  '
                '# drop "x86_64" once you no longer run the simulator on Intel Macs '
                "(default pins both)",
                'simulator_archs = ["arm64"]',
            )
            text = text.replace(
                '# source = "assets/icon.png"  '
                "# TODO: 1024x1024 PNG app icon — required for App Store submission",
                'source = "assets/icon.png"',
            )
            text = text.replace(
                '# source = "assets/splash.png"  # TODO: optional launch image',
                'source = "assets/splash.png"',
            )
            text = text.replace(
                '# background = "#000000"        '
                "# TODO: optional launch-screen background color",
                'background = "#112233"',
            )
            pp.write_text(text)
            result = runner.invoke(init, ["--force"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        ios = data["tool"]["kivy"]["ios"]
        assert ios["simulator_archs"] == ["arm64"]
        assert ios["icons"]["source"] == "assets/icon.png"
        assert ios["splash"]["source"] == "assets/splash.png"
        assert ios["splash"]["background"] == "#112233"

    def test_force_keeps_stubs_when_user_set_nothing(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT + "\n")
            runner.invoke(init, [])
            result = runner.invoke(init, ["--force"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
            text = pp.read_text()
        ios = data["tool"]["kivy"]["ios"]
        # Untouched stubs stay commented → defaults remain in effect.
        assert "simulator_archs" not in ios
        assert ios.get("icons", {}).get("source") is None
        assert ios.get("splash", {}).get("source") is None
        assert '# simulator_archs = ["arm64"]' in text

    def test_update_refuses_without_project(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text("[tool.black]\nline-length = 100\n")
            result = runner.invoke(init, [])
        assert result.exit_code != 0
        assert "no [project] table" in result.output


class TestPlatformAware:
    """Regression coverage for the ``init`` corruption bug + platform dispatch.

    ``init`` used to always render the iOS overlay regardless of platform or
    host, unconditionally appending a *second* ``[tool.kivy]`` table onto any
    project that already had one — producing invalid TOML for any
    macOS/Linux-only project. These tests cover the fix: platform resolution
    (``-p`` / ``KIVYFORGE_PLATFORM`` / host default / already-configured), and
    that adding or regenerating one platform's overlay never touches another's.
    """

    PYPROJECT_MACOS = textwrap.dedent(
        """
        [project]
        name = "dice-roller"
        version = "1.0.0"
        dependencies = ["kivy>=3.0"]

        [tool.kivy]
        display_name = "Dice Roller"
        app_dir = "src"
        entry_point = "main"
        orientation = ["portrait"]

        [tool.kivy.macos]
        schema_version = 1
        bundle_id = "org.example.dice-roller"
        build = 1
        archs = ["arm64", "x86_64"]

        [tool.kivy.macos.python]
        version = "3.13.14"
        """
    ).strip()

    def test_macos_fresh_project_seeds_shared_and_macos_tables(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text('[project]\nname = "myapp"\nversion = "1.0.0"\n')
            result = runner.invoke(init, ["-p", "macos"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert data["tool"]["kivy"]["app_dir"] == "src"
        assert data["tool"]["kivy"]["macos"]["bundle_id"] == "org.example.myapp"

    def test_linux_fresh_project_seeds_shared_and_linux_tables(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text('[project]\nname = "myapp"\nversion = "1.0.0"\n')
            result = runner.invoke(init, ["-p", "linux"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert data["tool"]["kivy"]["app_dir"] == "src"
        assert data["tool"]["kivy"]["linux"]["app_id"] == "org.example.myapp"

    def test_adding_second_platform_does_not_duplicate_shared_table(
        self, runner, tmp_path
    ):
        """The corruption bug: init used to blindly append a 2nd [tool.kivy]."""
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT_MACOS + "\n")
            result = runner.invoke(init, ["-p", "ios"])
            assert result.exit_code == 0, result.output
            text = pp.read_text()
            data = tomllib.loads(text)  # raises if [tool.kivy] was duplicated
        assert text.count("[tool.kivy]") == 1
        assert data["tool"]["kivy"]["macos"]["bundle_id"] == "org.example.dice-roller"
        assert data["tool"]["kivy"]["ios"]["bundle_id"] == "org.example.dice-roller"

    def test_force_regenerate_preserves_other_platforms_overlay(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT_MACOS + "\n")
            runner.invoke(init, ["-p", "ios"])  # add a second platform first
            result = runner.invoke(init, ["-p", "macos", "--force"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert "ios" in data["tool"]["kivy"]
        assert "macos" in data["tool"]["kivy"]

    def test_force_regenerate_preserves_macos_signing(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text('[project]\nname = "myapp"\nversion = "1.0.0"\n')
            runner.invoke(init, ["-p", "macos"])
            text = pp.read_text().replace(
                '# identity = "Developer ID Application: Your Name (TEAMID1234)"  '
                "# TODO: set for Gatekeeper-trusted distribution (ad-hoc signing is "
                "the default without it)",
                'identity = "Developer ID Application: Jane Doe (TEAM123456)"',
            )
            pp.write_text(text)
            result = runner.invoke(init, ["-p", "macos", "--force"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert (
            data["tool"]["kivy"]["macos"]["signing"]["identity"]
            == "Developer ID Application: Jane Doe (TEAM123456)"
        )

    def test_refuses_existing_macos_overlay_without_force(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT_MACOS + "\n")
            result = runner.invoke(init, ["-p", "macos"])
        assert result.exit_code != 0
        assert "--force" in result.output

    def test_ambiguous_multiple_configured_platforms_requires_explicit_flag(
        self, runner, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT_MACOS + "\n")
            runner.invoke(init, ["-p", "ios"])  # now both ios + macos configured
            result = runner.invoke(init, [])  # no -p, no env
        assert result.exit_code != 0
        assert "multiple platforms configured" in result.output

    def test_single_configured_platform_resolved_without_flag(
        self, runner, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text(self.PYPROJECT_MACOS + "\n")
            # No -p / no env, but exactly one platform (macos) already configured.
            result = runner.invoke(init, ["--force"])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert "macos" in data["tool"]["kivy"]
        assert "ios" not in data["tool"]["kivy"]

    def test_unknown_env_platform_is_actionable(self, runner, tmp_path, monkeypatch):
        monkeypatch.setenv("KIVYFORGE_PLATFORM", "windows")
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text('[project]\nname = "myapp"\nversion = "1.0.0"\n')
            result = runner.invoke(init, [])
        assert result.exit_code != 0
        assert "unknown platform" in result.output

    def test_host_default_used_when_nothing_configured_or_specified(
        self, runner, tmp_path, monkeypatch
    ):
        """On a fresh project with no flag/env/existing overlay, init falls
        back to the host OS's own platform (this test runs on macOS)."""
        monkeypatch.delenv("KIVYFORGE_PLATFORM", raising=False)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            pp = init_mod.Path(fs) / "pyproject.toml"
            pp.write_text('[project]\nname = "myapp"\nversion = "1.0.0"\n')
            result = runner.invoke(init, [])
            assert result.exit_code == 0, result.output
            data = tomllib.loads(pp.read_text())
        assert "macos" in data["tool"]["kivy"]
