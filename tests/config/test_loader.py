"""Phase 1 — config loader happy-path + all validation rules (spec 01)."""

from __future__ import annotations

import textwrap

import pytest

from kivyforge.config import ConfigError, load_config, load_config_from_text
from kivyforge.config.model import NativeBinaryDep, SwiftPackageDep, XcframeworkDep


def load(toml: str, **kw):
    return load_config_from_text(textwrap.dedent(toml).strip(), **kw)


class TestHappyPath:
    def test_parses_valid(self, valid_toml):
        cfg = load_config_from_text(valid_toml)
        assert cfg.project.name == "touchtracer"
        assert cfg.project.version == "1.0.0"
        assert cfg.project.dependencies == ("kivy>=3.0,<4",)
        assert cfg.kivy.app_dir == "src"
        assert cfg.kivy.entry_point == "main"
        assert cfg.kivy.orientation == ("portrait", "landscape-left")
        assert cfg.display_name == "Touchtracer"
        ios = cfg.ios_required
        assert ios.bundle_id == "org.kivy.touchtracer"
        assert ios.schema_version == 1
        assert ios.python_version == "3.15.0"
        assert ios.extra_index_urls == ("https://wheels.example.com/simple",)
        assert ios.icons.source == "assets/icon.png"
        assert ios.splash.background == "#000000"
        assert ios.signing.team_id == "ABCDE12345"

    def test_defaults(self):
        cfg = load(
            """
            [project]
            name = "app"
            version = "0.1.0"
            [tool.kivy]
            app_dir = "src"
            [tool.kivy.ios]
            schema_version = 1
            bundle_id = "org.example.app"
            python = { version = "3.15.0" }
            """
        )
        assert cfg.kivy.entry_point == "main"
        assert cfg.kivy.orientation == ("portrait",)
        ios = cfg.ios_required
        assert ios.build == 1
        assert ios.deployment_target == "13.0"
        assert ios.extra_index_urls == ()
        assert ios.signing.auto_signing is True
        assert ios.signing.upload_symbols is True
        assert cfg.display_name == "app"  # falls back to project.name

    def test_native_xcframeworks(self):
        cfg = load(
            """
            [project]
            name = "app"
            version = "0.1.0"
            [tool.kivy]
            app_dir = "src"
            [tool.kivy.ios]
            schema_version = 1
            bundle_id = "org.example.app"
            python = { version = "3.15.0" }
            [tool.kivy.ios.native.xcframeworks]
            Sentry = { version = "8.49.0", source = "https://example.com/Sentry.zip" }
            Local = { version = "0.3.0", source = "frameworks/Local.xcframework.zip", embed = false }
            """
        )
        ios = cfg.ios_required
        assert (
            XcframeworkDep("Sentry", "8.49.0", "https://example.com/Sentry.zip")
            in ios.xcframeworks
        )
        local = next(x for x in ios.xcframeworks if x.name == "Local")
        assert local.embed is False
        assert local.link is True


def load_swift(body: str):
    """Load a minimal valid pyproject with ``body`` appended to it.

    Header and body are dedented independently so callers can pass either
    indented blocks or flat ``"\\n"``-joined strings.
    """
    header = textwrap.dedent(
        """
        [project]
        name = "app"
        version = "0.1.0"
        [tool.kivy]
        app_dir = "src"
        [tool.kivy.ios]
        schema_version = 1
        bundle_id = "org.example.app"
        python = { version = "3.15.0" }
        """
    )
    return load_config_from_text((header + textwrap.dedent(body)).strip())


class TestSwiftPackages:
    def test_none_by_default(self):
        cfg = load_swift("")
        assert cfg.ios_required.swift_packages == ()

    def test_remote_and_local(self):
        cfg = load_swift(
            """
            [tool.kivy.ios.native.swift_packages]
            Lottie = { url = "https://github.com/airbnb/lottie-ios.git", requirement = { from = "4.4.0" }, products = ["Lottie"] }
            MyKit = { path = "vendor/MyKit", products = ["MyKit", "MyKitUI"], embed = false }
            """
        )
        pkgs = {p.name: p for p in cfg.ios_required.swift_packages}
        lottie = pkgs["Lottie"]
        assert lottie.url == "https://github.com/airbnb/lottie-ios.git"
        assert lottie.path is None
        assert lottie.requirement == {"from": "4.4.0"}
        assert lottie.products == ("Lottie",)
        assert lottie.link is True and lottie.embed is True

        mykit = pkgs["MyKit"]
        assert mykit.path == "vendor/MyKit"
        assert mykit.url is None
        assert mykit.requirement is None
        assert mykit.products == ("MyKit", "MyKitUI")
        assert mykit.embed is False

    def test_range_requirement(self):
        cfg = load_swift(
            """
            [tool.kivy.ios.native.swift_packages]
            Foo = { url = "https://example.com/foo.git", requirement = { range = ["1.0.0", "2.0.0"] }, products = ["Foo"] }
            """
        )
        (foo,) = cfg.ios_required.swift_packages
        assert foo == SwiftPackageDep(
            name="Foo",
            products=("Foo",),
            url="https://example.com/foo.git",
            requirement={"range": ["1.0.0", "2.0.0"]},
        )

    def test_table_must_be_table(self):
        with pytest.raises(ConfigError, match="must be a table"):
            load_swift("[tool.kivy.ios.native]\nswift_packages = 'nope'\n")

    def test_entry_must_be_inline_table(self):
        with pytest.raises(ConfigError, match="inline table"):
            load_swift("[tool.kivy.ios.native.swift_packages]\nFoo = 'nope'\n")

    def test_requires_url_or_path(self):
        with pytest.raises(ConfigError, match="exactly one of 'url' or 'path'"):
            load_swift(
                '[tool.kivy.ios.native.swift_packages]\nFoo = { products = ["Foo"] }\n'
            )

    def test_rejects_both_url_and_path(self):
        with pytest.raises(ConfigError, match="exactly one of 'url' or 'path'"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { url = "https://x/foo.git", path = "vendor/Foo", '
                'requirement = { from = "1.0.0" }, products = ["Foo"] }\n'
            )

    def test_remote_requires_requirement(self):
        with pytest.raises(ConfigError, match="requirement"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { url = "https://x/foo.git", products = ["Foo"] }\n'
            )

    def test_unknown_requirement_rule(self):
        with pytest.raises(ConfigError, match="unknown requirement rule"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { url = "https://x/foo.git", '
                'requirement = { latest = "yes" }, products = ["Foo"] }\n'
            )

    def test_requirement_must_have_one_rule(self):
        with pytest.raises(ConfigError, match="exactly one"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { url = "https://x/foo.git", '
                'requirement = { from = "1.0.0", exact = "1.0.0" }, '
                'products = ["Foo"] }\n'
            )

    def test_range_must_be_two_strings(self):
        with pytest.raises(ConfigError, match="two version strings"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { url = "https://x/foo.git", '
                'requirement = { range = ["1.0.0"] }, products = ["Foo"] }\n'
            )

    def test_string_requirement_must_be_nonempty(self):
        with pytest.raises(ConfigError, match="must be a non-empty string"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { url = "https://x/foo.git", '
                'requirement = { from = "" }, products = ["Foo"] }\n'
            )

    def test_local_path_must_be_relative(self):
        with pytest.raises(ConfigError, match="must be relative"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { path = "/abs/MyKit", products = ["Foo"] }\n'
            )

    def test_local_path_must_not_escape(self):
        with pytest.raises(ConfigError, match="must not escape"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { path = "../MyKit", products = ["Foo"] }\n'
            )

    def test_products_required(self):
        with pytest.raises(ConfigError, match="products"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { url = "https://x/foo.git", '
                'requirement = { from = "1.0.0" } }\n'
            )

    def test_products_must_be_nonempty(self):
        with pytest.raises(ConfigError, match="products"):
            load_swift(
                "[tool.kivy.ios.native.swift_packages]\n"
                'Foo = { path = "vendor/Foo", products = [] }\n'
            )


class TestRule1Project:
    def test_missing_project(self):
        with pytest.raises(ConfigError, match="missing \\[project\\]"):
            load("[tool.kivy]\napp_dir='src'")

    def test_missing_name(self):
        with pytest.raises(ConfigError, match="name"):
            load("[project]\nversion='1.0'\n[tool.kivy]\napp_dir='src'")

    def test_missing_version(self):
        with pytest.raises(ConfigError, match="version"):
            load("[project]\nname='a'\n[tool.kivy]\napp_dir='src'")


class TestRule2IosRequired:
    def test_missing_ios_when_required(self):
        with pytest.raises(ConfigError, match="missing \\[tool.kivy.ios\\]"):
            load(
                """
                [project]
                name='a'
                version='1.0'
                [tool.kivy]
                app_dir='src'
                """
            )

    def test_missing_ios_allowed_when_not_required(self):
        cfg = load(
            """
            [project]
            name='a'
            version='1.0'
            [tool.kivy]
            app_dir='src'
            """,
            require_ios=False,
        )
        assert cfg.ios is None


class TestRule3SchemaVersion:
    def test_missing(self):
        with pytest.raises(ConfigError, match="schema_version"):
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                "[tool.kivy.ios]\nbundle_id='org.x.a'"
            )

    def test_too_new(self):
        with pytest.raises(ConfigError, match="newer than this kivyforge") as exc:
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                "[tool.kivy.ios]\nschema_version=99\nbundle_id='org.x.a'"
            )
        assert "upgrade kivyforge" in exc.value.format()


class TestRule4BundleId:
    def test_missing(self):
        with pytest.raises(ConfigError, match="bundle_id"):
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                "[tool.kivy.ios]\nschema_version=1"
            )


class TestRule5EntryPoint:
    @pytest.mark.parametrize("ep", ["123bad", "a-b", "import", "a..b", ""])
    def test_invalid(self, ep):
        with pytest.raises(ConfigError, match="entry_point"):
            load(
                f"[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                f"entry_point='{ep}'\n[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'"
            )

    def test_dotted_ok(self):
        cfg = load(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "entry_point='pkg.start'\n[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "python = { version = '3.15.0' }"
        )
        assert cfg.kivy.entry_point == "pkg.start"


class TestRule6AppDir:
    @pytest.mark.parametrize("bad", [".", "", "/abs/path", "../escape"])
    def test_invalid(self, bad):
        with pytest.raises(ConfigError):
            load(
                f"[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='{bad}'\n"
                f"[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'"
            )

    def test_missing(self):
        with pytest.raises(ConfigError, match="app_dir"):
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\nentry_point='main'\n"
                "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'"
            )

    def test_nested_ok(self):
        cfg = load(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='app/src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "python = { version = '3.15.0' }"
        )
        assert cfg.kivy.app_dir == "app/src"


class TestRule7Orientation:
    def test_invalid_value(self):
        with pytest.raises(ConfigError, match="orientation"):
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                "orientation=['sideways']\n[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'"
            )


class TestRule8ReservedBuildSettings:
    def test_reserved_rejected(self):
        with pytest.raises(ConfigError, match="reserved"):
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
                "python = { version = '3.15.0' }\n"
                "[tool.kivy.ios.xcode.build_settings]\nPRODUCT_BUNDLE_IDENTIFIER='x'"
            )

    def test_free_setting_ok(self):
        cfg = load(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "python = { version = '3.15.0' }\n"
            "[tool.kivy.ios.xcode.build_settings]\nSWIFT_VERSION='5.0'"
        )
        assert cfg.ios_required.build_settings == {"SWIFT_VERSION": "5.0"}


class TestRule10RequiresPython:
    def test_incompatible(self):
        with pytest.raises(ConfigError, match="requires-python"):
            load(
                "[project]\nname='a'\nversion='1'\nrequires-python='>=3.16'\n"
                "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
                "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0'"
            )

    def test_compatible(self):
        cfg = load(
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.13'\n"
            "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
            "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        assert cfg.ios_required.python_version == "3.15.0"

    def test_prerelease_needs_explicit_floor(self):
        with pytest.raises(ConfigError, match="3.15.0b2") as exc:
            load(
                "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15'\n"
                "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
                "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0b2'"
            )
        assert "pre-release" in str(exc.value.hint)

    def test_prerelease_with_matching_floor(self):
        cfg = load(
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15.0b2'\n"
            "[tool.kivy]\napp_dir='src'\n[tool.kivy.ios]\nschema_version=1\n"
            "bundle_id='o.x.a'\n[tool.kivy.ios.python]\nversion='3.15.0b2'"
        )
        assert cfg.ios_required.python_version == "3.15.0b2"


class TestInfoPlistManagedKeys:
    def test_managed_key_rejected(self):
        with pytest.raises(ConfigError, match="managed"):
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
                "python = { version = '3.15.0' }\n"
                "[tool.kivy.ios.info_plist]\nCFBundleIdentifier='x'"
            )

    def test_free_key_ok(self):
        cfg = load(
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "python = { version = '3.15.0' }\n"
            "[tool.kivy.ios.info_plist]\nNSCameraUsageDescription='QR'"
        )
        assert cfg.ios_required.info_plist == {"NSCameraUsageDescription": "QR"}


class TestFindLinks:
    def test_sibling_directory_ok(self, tmp_path):
        app = tmp_path / "hello-kivy"
        shared = tmp_path / "wheels"
        app.mkdir()
        shared.mkdir()
        toml = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            'find_links = ["../wheels"]\n'
            "[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        (app / "pyproject.toml").write_text(toml)
        cfg = load_config(app / "pyproject.toml")
        assert cfg.ios_required.find_links == ("../wheels",)

    def test_escape_beyond_parent_rejected(self, tmp_path):
        app = tmp_path / "app"
        app.mkdir()
        toml = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            'find_links = ["../../outside"]\n'
            "[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        (app / "pyproject.toml").write_text(toml)
        with pytest.raises(ConfigError, match="sibling directory"):
            load_config(app / "pyproject.toml")

    def test_shared_wheelhouse_within_repo_ok(self, tmp_path):
        # examples/<group>/<app>/ reaching a shared examples/wheels/ios/
        (tmp_path / ".git").mkdir()
        app = tmp_path / "examples" / "mobile" / "hello-kivy"
        wheels = tmp_path / "examples" / "wheels" / "ios"
        app.mkdir(parents=True)
        wheels.mkdir(parents=True)
        toml = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            'find_links = ["../../wheels/ios"]\n'
            "[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        (app / "pyproject.toml").write_text(toml)
        cfg = load_config(app / "pyproject.toml")
        assert cfg.ios_required.find_links == ("../../wheels/ios",)

    def test_escape_beyond_repo_rejected(self, tmp_path):
        # Same two-levels-up shape, but no repo marker → falls back to strict rule.
        app = tmp_path / "examples" / "mobile" / "hello-kivy"
        app.mkdir(parents=True)
        toml = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            'find_links = ["../../wheels/ios"]\n'
            "[tool.kivy.ios.python]\nversion='3.15.0'"
        )
        (app / "pyproject.toml").write_text(toml)
        with pytest.raises(ConfigError, match="enclosing repository"):
            load_config(app / "pyproject.toml")


class TestSimulatorArchs:
    _BASE = (
        "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
        "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
        "python = { version = '3.15.0' }\n"
    )

    def test_default_is_both_archs(self):
        cfg = load(self._BASE)
        assert cfg.ios_required.simulator_archs == ("arm64", "x86_64")

    def test_arm64_only(self):
        cfg = load(self._BASE + "simulator_archs=['arm64']\n")
        assert cfg.ios_required.simulator_archs == ("arm64",)

    def test_explicit_both(self):
        cfg = load(self._BASE + "simulator_archs=['arm64','x86_64']\n")
        assert cfg.ios_required.simulator_archs == ("arm64", "x86_64")

    def test_dedupes_preserving_order(self):
        cfg = load(self._BASE + "simulator_archs=['x86_64','arm64','x86_64']\n")
        assert cfg.ios_required.simulator_archs == ("x86_64", "arm64")

    def test_unknown_arch_rejected(self):
        with pytest.raises(ConfigError, match="unknown simulator arch"):
            load(self._BASE + "simulator_archs=['arm64','ppc']\n")

    def test_empty_rejected(self):
        with pytest.raises(ConfigError, match="must not be empty"):
            load(self._BASE + "simulator_archs=[]\n")

    def test_non_list_rejected(self):
        with pytest.raises(ConfigError, match="must be a list of strings"):
            load(self._BASE + "simulator_archs='arm64'\n")

    def test_non_string_items_rejected(self):
        with pytest.raises(ConfigError, match="must be a list of strings"):
            load(self._BASE + "simulator_archs=[1,2]\n")


# A minimal valid project whose [tool.kivy.ios] body can be extended by tests.
# python is inline so appended bare keys still bind to [tool.kivy.ios].
_VALID_IOS = (
    "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
    "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
    "python = { version = '3.15.0' }\n"
)


class TestPythonVersionRequired:
    """[tool.kivy.ios.python].version is required (spec 01) — no hidden default."""

    def test_missing_python_table_rejected(self):
        with pytest.raises(ConfigError, match=r"required \[tool.kivy.ios.python\]"):
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            )

    def test_missing_version_rejected(self):
        with pytest.raises(ConfigError, match="required .*version"):
            load(
                "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
                "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
                "[tool.kivy.ios.python]\nother='x'"
            )

    def test_empty_version_rejected(self):
        with pytest.raises(ConfigError, match="non-empty string"):
            load(_VALID_IOS.replace("version = '3.15.0'", "version = ''"))

    def test_non_string_version_rejected(self):
        with pytest.raises(ConfigError, match="non-empty string"):
            load(_VALID_IOS.replace("version = '3.15.0'", "version = 315"))


class TestXcframeworkSource:
    def test_relative_path_ok(self):
        cfg = load(
            _VALID_IOS + "[tool.kivy.ios.native.xcframeworks]\n"
            'Local = { version = "1.0", source = "frameworks/Local.xcframework.zip" }'
        )
        (xc,) = cfg.ios_required.xcframeworks
        assert xc.source == "frameworks/Local.xcframework.zip"

    def test_absolute_path_rejected(self):
        with pytest.raises(ConfigError, match="absolute path"):
            load(
                _VALID_IOS + "[tool.kivy.ios.native.xcframeworks]\n"
                'Local = { version = "1.0", source = "/abs/Local.xcframework.zip" }'
            )

    def test_escaping_path_rejected(self):
        with pytest.raises(ConfigError, match="escape"):
            load(
                _VALID_IOS + "[tool.kivy.ios.native.xcframeworks]\n"
                'Local = { version = "1.0", source = "../../Local.xcframework.zip" }'
            )

    def test_url_source_ok(self):
        cfg = load(
            _VALID_IOS + "[tool.kivy.ios.native.xcframeworks]\n"
            'S = { version = "1.0", source = "https://example.com/S.zip" }'
        )
        (xc,) = cfg.ios_required.xcframeworks
        assert xc.source == "https://example.com/S.zip"

    def test_non_bool_link_rejected(self):
        with pytest.raises(ConfigError, match="must be a boolean"):
            load(
                _VALID_IOS + "[tool.kivy.ios.native.xcframeworks]\n"
                'S = { version = "1.0", source = "f/S.zip", link = "no" }'
            )


class TestSigningBooleans:
    def test_string_auto_signing_rejected(self):
        # bool("false") is True; a stray string must be rejected, not coerced.
        with pytest.raises(ConfigError, match="must be a boolean"):
            load(_VALID_IOS + "[tool.kivy.ios.signing]\nauto_signing = 'false'")

    def test_int_upload_symbols_rejected(self):
        with pytest.raises(ConfigError, match="must be a boolean"):
            load(_VALID_IOS + "[tool.kivy.ios.signing]\nupload_symbols = 0")

    def test_bool_values_ok(self):
        cfg = load(
            _VALID_IOS + "[tool.kivy.ios.signing]\n"
            "auto_signing = false\nupload_symbols = false"
        )
        assert cfg.ios_required.signing.auto_signing is False
        assert cfg.ios_required.signing.upload_symbols is False


class TestBuildSettingTypes:
    def test_non_string_value_rejected(self):
        with pytest.raises(ConfigError, match="must be a string"):
            load(
                _VALID_IOS + "[tool.kivy.ios.xcode.build_settings]\nENABLE_BITCODE = 0"
            )

    def test_string_values_ok(self):
        cfg = load(
            _VALID_IOS + "[tool.kivy.ios.xcode.build_settings]\n"
            'ENABLE_BITCODE = "NO"\nSWIFT_VERSION = "5.0"'
        )
        assert cfg.ios_required.build_settings == {
            "ENABLE_BITCODE": "NO",
            "SWIFT_VERSION": "5.0",
        }


class TestSyntaxError:
    def test_bad_toml_reports_line(self):
        with pytest.raises(ConfigError, match="invalid TOML"):
            load("[project]\nname = \nversion='1'")


class TestErrorFormatting:
    def test_format_includes_key_path_and_hint(self):
        try:
            load("[tool.kivy]\napp_dir='src'")
        except ConfigError as e:
            text = e.format()
            assert "project" in text


# Head opens [tool.kivy.macos]; extras append here; the python subtable comes
# last so extra keys stay under [tool.kivy.macos] (TOML table scoping).
_MACOS_HEAD = (
    "[project]\nname='hello'\nversion='1'\nrequires-python='>=3.15.0b2'\n"
    "dependencies=['kivy']\n"
    "[tool.kivy]\napp_dir='src'\ndisplay_name='Hello'\n"
    "[tool.kivy.macos]\nschema_version=1\nbundle_id='org.example.hello'\n"
)
_MACOS_PY = "[tool.kivy.macos.python]\nversion='3.15.0'\n"
_MACOS_BASE = _MACOS_HEAD + _MACOS_PY


def _macos(extra: str = ""):
    return load(_MACOS_HEAD + extra + _MACOS_PY, require_ios=False, require_macos=True)


class TestMacosOverlay:
    def test_missing_overlay_when_required(self):
        base = "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
        with pytest.raises(ConfigError, match=r"\[tool.kivy.macos\]"):
            load(base, require_ios=False, require_macos=True)

    def test_happy_path(self):
        cfg = _macos()
        assert cfg.macos is not None
        m = cfg.macos_required
        assert m.bundle_id == "org.example.hello"
        assert m.schema_version == 1
        assert m.build == 1
        assert m.minimum_system_version is None
        assert m.archs == ("arm64", "x86_64")
        assert m.python_version == "3.15.0"

    def test_ios_and_macos_coexist(self):
        base = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.15.0b2'\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
        )
        cfg = load(base, require_ios=True, require_macos=True)
        assert cfg.ios is not None
        assert cfg.macos is not None

    def test_missing_bundle_id(self):
        base = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.macos]\nschema_version=1\n"
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
        )
        with pytest.raises(ConfigError, match="bundle_id"):
            load(base, require_ios=False, require_macos=True)

    def test_bundle_id_rejects_underscore(self):
        with pytest.raises(ConfigError, match="invalid character"):
            _macos_bad = _MACOS_BASE.replace(
                "org.example.hello", "org.example.hi_there"
            )
            load(_macos_bad, require_ios=False, require_macos=True)

    def test_missing_python_version(self):
        base = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='o.x.a'\n"
        )
        with pytest.raises(ConfigError, match="python"):
            load(base, require_ios=False, require_macos=True)

    def test_schema_version_too_new(self):
        bad = _MACOS_BASE.replace("schema_version=1", "schema_version=99")
        with pytest.raises(ConfigError, match="newer than"):
            load(bad, require_ios=False, require_macos=True)

    def test_minimum_system_version(self):
        cfg = _macos('minimum_system_version="12.0"\n')
        assert cfg.macos_required.minimum_system_version == "12.0"


class TestMacosArchs:
    def test_default(self):
        assert _macos().macos_required.archs == ("arm64", "x86_64")

    def test_arm64_only(self):
        assert _macos("archs=['arm64']\n").macos_required.archs == ("arm64",)

    def test_dedup_preserves_order(self):
        assert _macos("archs=['x86_64','arm64','x86_64']\n").macos_required.archs == (
            "x86_64",
            "arm64",
        )

    def test_empty_rejected(self):
        with pytest.raises(ConfigError, match="must not be empty"):
            _macos("archs=[]\n")

    def test_unknown_rejected(self):
        with pytest.raises(ConfigError, match="unknown macOS arch"):
            _macos("archs=['ppc64']\n")


class TestMacosNativeBinaries:
    def test_default_empty(self):
        assert _macos().macos_required.binaries == ()

    def test_parses_url_and_relative(self):
        cfg = load(
            _MACOS_BASE + "[tool.kivy.macos.native.binaries]\n"
            'sdk = { version = "2.1.0", source = "https://vendor.example/sdk.zip" }\n'
            'ffmpeg = { version = "7.1", source = "binaries/macos/ffmpeg" }\n',
            require_ios=False,
            require_macos=True,
        )
        binaries = cfg.macos_required.binaries
        assert (
            NativeBinaryDep("sdk", "2.1.0", "https://vendor.example/sdk.zip")
            in binaries
        )
        assert NativeBinaryDep("ffmpeg", "7.1", "binaries/macos/ffmpeg") in binaries

    def test_absolute_path_rejected(self):
        with pytest.raises(ConfigError, match="absolute path"):
            load(
                _MACOS_BASE + "[tool.kivy.macos.native.binaries]\n"
                'sdk = { version = "1.0", source = "/abs/sdk.dylib" }\n',
                require_ios=False,
                require_macos=True,
            )

    def test_escaping_path_rejected(self):
        with pytest.raises(ConfigError, match="escape"):
            load(
                _MACOS_BASE + "[tool.kivy.macos.native.binaries]\n"
                'sdk = { version = "1.0", source = "../../sdk.dylib" }\n',
                require_ios=False,
                require_macos=True,
            )

    def test_missing_version_rejected(self):
        with pytest.raises(ConfigError, match="requires a string 'version'"):
            load(
                _MACOS_BASE + "[tool.kivy.macos.native.binaries]\n"
                'sdk = { source = "sdk.dylib" }\n',
                require_ios=False,
                require_macos=True,
            )

    def test_missing_source_rejected(self):
        with pytest.raises(ConfigError, match="requires an explicit 'source'"):
            load(
                _MACOS_BASE + "[tool.kivy.macos.native.binaries]\n"
                'sdk = { version = "1.0" }\n',
                require_ios=False,
                require_macos=True,
            )

    def test_non_table_entry_rejected(self):
        with pytest.raises(ConfigError, match="must be an inline table"):
            load(
                _MACOS_BASE + '[tool.kivy.macos.native.binaries]\nsdk = "sdk.dylib"\n',
                require_ios=False,
                require_macos=True,
            )


class TestMacosSigning:
    def test_default_unconfigured(self):
        signing = _macos().macos_required.signing
        assert signing.identity == ""
        assert signing.team_id == ""
        assert signing.notary_profile == ""
        assert not signing.configured

    def test_full_table(self):
        cfg = _macos(
            "[tool.kivy.macos.signing]\n"
            "identity='Developer ID Application: Jane Doe (ABC123)'\n"
            "team_id='ABC123'\n"
            "notary_profile='kivyforge-notary'\n"
        )
        signing = cfg.macos_required.signing
        assert signing.identity == "Developer ID Application: Jane Doe (ABC123)"
        assert signing.team_id == "ABC123"
        assert signing.notary_profile == "kivyforge-notary"
        assert signing.configured

    def test_non_table_rejected(self):
        with pytest.raises(ConfigError, match=r"signing.*must be a table"):
            _macos("signing='Developer ID'\n")

    def test_non_string_field_rejected(self):
        with pytest.raises(ConfigError, match="identity must be a string"):
            _macos("[tool.kivy.macos.signing]\nidentity=1\n")


class TestMacosEntitlements:
    def test_default_empty(self):
        assert _macos().macos_required.entitlements == {}

    def test_table_passthrough(self):
        cfg = _macos(
            '[tool.kivy.macos.entitlements]\n"com.apple.security.device.camera"=true\n'
        )
        assert cfg.macos_required.entitlements == {
            "com.apple.security.device.camera": True
        }

    def test_non_table_rejected(self):
        with pytest.raises(ConfigError, match=r"entitlements.*must be a table"):
            _macos("entitlements='camera'\n")


class TestMacosEntitlementsNotarizable:
    def test_get_task_allow_rejected_when_signing_configured(self):
        with pytest.raises(ConfigError, match="get-task-allow.*to true"):
            _macos(
                '[tool.kivy.macos.entitlements]\n"com.apple.security.get-task-allow"=true\n'
                "[tool.kivy.macos.signing]\n"
                "identity='Developer ID Application: Jane Doe (ABC123)'\n"
            )

    def test_get_task_allow_allowed_without_signing(self):
        cfg = _macos(
            '[tool.kivy.macos.entitlements]\n"com.apple.security.get-task-allow"=true\n'
        )
        assert (
            cfg.macos_required.entitlements["com.apple.security.get-task-allow"] is True
        )

    def test_get_task_allow_false_allowed_with_signing(self):
        cfg = _macos(
            '[tool.kivy.macos.entitlements]\n"com.apple.security.get-task-allow"=false\n'
            "[tool.kivy.macos.signing]\n"
            "identity='Developer ID Application: Jane Doe (ABC123)'\n"
        )
        assert (
            cfg.macos_required.entitlements["com.apple.security.get-task-allow"]
            is False
        )


class TestMacosRequiresPython:
    def test_excluding_version_rejected(self):
        base = (
            "[project]\nname='a'\nversion='1'\nrequires-python='>=3.16'\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
        )
        with pytest.raises(ConfigError, match="excludes the selected"):
            load(base, require_ios=False, require_macos=True)


# Head opens [tool.kivy.linux]; extras append here; the python subtable comes
# last so extra keys stay under [tool.kivy.linux] (TOML table scoping).
_LINUX_HEAD = (
    "[project]\nname='hello'\nversion='1'\nrequires-python='>=3.15.0b2'\n"
    "dependencies=['kivy']\n"
    "[tool.kivy]\napp_dir='src'\ndisplay_name='Hello'\n"
    "[tool.kivy.linux]\nschema_version=1\napp_id='org.example.hello'\n"
)
_LINUX_PY = "[tool.kivy.linux.python]\nversion='3.15.0'\n"


def _linux(extra: str = ""):
    return load(_LINUX_HEAD + extra + _LINUX_PY, require_ios=False, require_linux=True)


class TestLinuxOverlay:
    def test_missing_overlay_when_required(self):
        base = "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
        with pytest.raises(ConfigError, match=r"\[tool.kivy.linux\]"):
            load(base, require_ios=False, require_linux=True)

    def test_happy_path(self):
        cfg = _linux()
        assert cfg.linux is not None
        lx = cfg.linux_required
        assert lx.app_id == "org.example.hello"
        assert lx.schema_version == 1
        assert lx.glibc_floor is None
        assert lx.archs == ("x86_64",)
        assert lx.python_version == "3.15.0"
        assert lx.desktop.categories == ("Utility",)

    def test_glibc_floor(self):
        assert _linux('glibc_floor="2.28"\n').linux_required.glibc_floor == "2.28"

    def test_missing_app_id(self):
        base = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.linux]\nschema_version=1\n"
            "[tool.kivy.linux.python]\nversion='3.15.0'\n"
        )
        with pytest.raises(ConfigError, match="app_id"):
            load(base, require_ios=False, require_linux=True)

    def test_invalid_app_id_char(self):
        with pytest.raises(ConfigError, match="invalid character"):
            _linux_bad = _LINUX_HEAD.replace(
                "org.example.hello", "org.example.hello_app"
            )
            load(_linux_bad + _LINUX_PY, require_ios=False, require_linux=True)

    def test_missing_python_version(self):
        base = (
            "[project]\nname='a'\nversion='1'\n[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.linux]\nschema_version=1\napp_id='o.x.a'\n"
        )
        with pytest.raises(ConfigError, match="python"):
            load(base, require_ios=False, require_linux=True)


class TestLinuxArchs:
    def test_default(self):
        assert _linux().linux_required.archs == ("x86_64",)

    def test_explicit_x86_64(self):
        assert _linux("archs=['x86_64']\n").linux_required.archs == ("x86_64",)

    def test_empty_rejected(self):
        with pytest.raises(ConfigError, match="must not be empty"):
            _linux("archs=[]\n")

    def test_aarch64_rejected_this_phase(self):
        with pytest.raises(ConfigError, match="unsupported Linux arch"):
            _linux("archs=['aarch64']\n")


class TestLinuxDesktop:
    def test_default_categories(self):
        assert _linux().linux_required.desktop.categories == ("Utility",)

    def test_custom_categories(self):
        cfg = _linux("[tool.kivy.linux.desktop]\ncategories=['Game','Education']\n")
        assert cfg.linux_required.desktop.categories == ("Game", "Education")

    def test_bad_categories(self):
        with pytest.raises(ConfigError, match="categories"):
            _linux("[tool.kivy.linux.desktop]\ncategories='Utility'\n")

    def test_non_main_category_rejected(self):
        # A typo / non-main freedesktop category is rejected at config time.
        with pytest.raises(ConfigError, match="invalid.*categories"):
            _linux("[tool.kivy.linux.desktop]\ncategories=['Utillity']\n")

    def test_additional_category_rejected(self):
        # "Building" is a freedesktop *additional* (not main) category.
        with pytest.raises(ConfigError, match="invalid.*categories") as exc:
            _linux("[tool.kivy.linux.desktop]\ncategories=['Building']\n")
        assert "freedesktop main categories" in (exc.value.hint or "")


class TestLinuxIcons:
    def test_default_none(self):
        assert _linux().linux_required.icons.source is None

    def test_source(self):
        cfg = _linux("[tool.kivy.linux.icons]\nsource='assets/icon.png'\n")
        assert cfg.linux_required.icons.source == "assets/icon.png"


class TestLinuxNativeBinaries:
    def test_default_empty(self):
        assert _linux().linux_required.binaries == ()

    def test_parses_url_and_relative(self):
        cfg = _linux(
            "[tool.kivy.linux.native.binaries]\n"
            'sdk = { version = "2.1.0", source = "https://vendor.example/sdk.tar.gz" }\n'
            'roll = { version = "0.1.0", source = "binaries/linux/roll" }\n'
        )
        binaries = cfg.linux_required.binaries
        assert (
            NativeBinaryDep("sdk", "2.1.0", "https://vendor.example/sdk.tar.gz")
            in binaries
        )
        assert NativeBinaryDep("roll", "0.1.0", "binaries/linux/roll") in binaries

    def test_absolute_path_rejected(self):
        with pytest.raises(ConfigError, match="absolute path"):
            _linux(
                "[tool.kivy.linux.native.binaries]\n"
                'sdk = { version = "1.0", source = "/abs/libgreet.so" }\n'
            )

    def test_escaping_path_rejected(self):
        with pytest.raises(ConfigError, match="escape"):
            _linux(
                "[tool.kivy.linux.native.binaries]\n"
                'sdk = { version = "1.0", source = "../../libgreet.so" }\n'
            )

    def test_missing_version_rejected(self):
        with pytest.raises(ConfigError, match="requires a string 'version'"):
            _linux(
                "[tool.kivy.linux.native.binaries]\n"
                'sdk = { source = "libgreet.so" }\n'
            )

    def test_missing_source_rejected(self):
        with pytest.raises(ConfigError, match="requires an explicit 'source'"):
            _linux(
                "[tool.kivy.linux.native.binaries]\nsdk = { version = \"1.0\" }\n"
            )

    def test_non_table_entry_rejected(self):
        with pytest.raises(ConfigError, match="must be an inline table"):
            _linux(
                '[tool.kivy.linux.native.binaries]\nsdk = "libgreet.so"\n'
            )


class TestIosAndLinuxCoexist:
    def test_all_three_platforms(self):
        base = (
            "[project]\nname='hello'\nversion='1'\ndependencies=['kivy']\n"
            "[tool.kivy]\napp_dir='src'\n"
            "[tool.kivy.ios]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.ios.python]\nversion='3.15.0'\n"
            "[tool.kivy.macos]\nschema_version=1\nbundle_id='o.x.a'\n"
            "[tool.kivy.macos.python]\nversion='3.15.0'\n"
            "[tool.kivy.linux]\nschema_version=1\napp_id='o.x.a'\n"
            "[tool.kivy.linux.python]\nversion='3.15.0'\n"
        )
        cfg = load(base, require_ios=True, require_macos=True, require_linux=True)
        assert cfg.ios is not None
        assert cfg.macos is not None
        assert cfg.linux is not None
