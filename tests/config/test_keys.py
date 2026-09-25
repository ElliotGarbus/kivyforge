"""Unknown keys under [tool.kivy] are rejected, not silently dropped."""

from __future__ import annotations

import re
import textwrap
import tomllib
from pathlib import Path

import pytest

from kivyforge.config import ConfigError, load_config_from_text
from kivyforge.config.keys import find_unknown_keys

_BASE = """\
[project]
name = "app"
version = "1.0.0"

[tool.kivy]
app_dir = "src"
"""

_IOS = """\
[tool.kivy.ios]
schema_version = 1
bundle_id = "org.example.app"
python = { version = "3.15.0" }
"""

_ANDROID = """\
[tool.kivy.android]
schema_version = 1
package = "org.example.app"
python = { version = "3.14.6" }
"""


def load(*parts: str, **kw):
    text = "\n".join(textwrap.dedent(p) for p in parts)
    kw.setdefault("require_ios", False)
    return load_config_from_text(text, **kw)


def line_of(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not in text")


class TestRejected:
    def test_typo_in_overlay_suggests_the_real_key(self):
        text = _BASE + _IOS + 'deployment_targt = "15.0"\n'
        with pytest.raises(ConfigError) as exc:
            load(text)
        err = exc.value
        assert err.message == "unknown key 'deployment_targt' in [tool.kivy.ios]"
        assert err.key_path == "tool.kivy.ios.deployment_targt"
        assert err.line == line_of(text, "deployment_targt")
        assert err.hint is not None
        assert err.hint.startswith("did you mean 'deployment_target'?")

    def test_misspelt_required_key_reports_as_typo_not_missing(self):
        text = _BASE + '[tool.kivy.ios]\nschema_version = 1\nbundle_idd = "o.x.a"\n'
        with pytest.raises(ConfigError, match="unknown key 'bundle_idd'") as exc:
            load(text, require_ios=True)
        assert exc.value.hint is not None
        assert "did you mean 'bundle_id'" in exc.value.hint

    def test_unimplemented_subtable_points_at_its_header(self):
        # Specified in android/01 but never built: it used to ship a release
        # build with none of the keep rules the user asked for.
        text = (
            _BASE
            + _ANDROID
            + '[tool.kivy.android.proguard]\nkeep = ["-keep class org.x.** { *; }"]\n'
        )
        with pytest.raises(ConfigError) as exc:
            load(text)
        err = exc.value
        assert err.message == "unknown key 'proguard' in [tool.kivy.android]"
        assert err.line == line_of(text, "[tool.kivy.android.proguard]")
        assert err.hint is not None
        assert "Valid keys in [tool.kivy.android]: abis, activities," in err.hint

    def test_dotted_key_is_located(self):
        text = _BASE + _IOS + 'signing.team_idd = "ABCDE12345"\n'
        with pytest.raises(ConfigError) as exc:
            load(text)
        assert exc.value.key_path == "tool.kivy.ios.signing.team_idd"
        assert exc.value.line == line_of(text, "team_idd")

    def test_typo_inside_an_array_of_tables(self):
        text = (
            _BASE
            + _ANDROID
            + '[[tool.kivy.android.services]]\nname = "Worker"\nentrypoint = "w"\n'
        )
        with pytest.raises(ConfigError) as exc:
            load(text)
        err = exc.value
        assert (
            err.message == "unknown key 'entrypoint' in [tool.kivy.android.services[0]]"
        )
        assert err.line == line_of(text, "entrypoint")
        assert err.hint is not None
        assert "did you mean 'entry_point'" in err.hint

    def test_typo_inside_a_named_entry(self):
        text = (
            _BASE
            + _IOS
            + "[tool.kivy.ios.native.xcframeworks]\n"
            + 'Foo = { verison = "1.0", source = "vendor/Foo.xcframework" }\n'
        )
        with pytest.raises(ConfigError) as exc:
            load(text)
        assert exc.value.key_path == "tool.kivy.ios.native.xcframeworks.Foo.verison"

    def test_unknown_scalar_directly_under_tool_kivy(self):
        with pytest.raises(
            ConfigError, match=r"'display_nam' in \[tool\.kivy\]"
        ) as exc:
            load(_BASE + 'display_nam = "Demo"\n')
        assert exc.value.hint is not None
        assert exc.value.hint.startswith("did you mean 'display_name'?")

    def test_another_platforms_overlay_is_still_checked(self):
        # Consistent with every other rule: all overlays are validated, not just
        # the one the verb targets.
        text = _BASE + _IOS + _ANDROID + "min_skd = 26\n"
        with pytest.raises(ConfigError, match="unknown key 'min_skd'"):
            load(text, require_ios=True)

    def test_several_unknown_keys_are_reported_together(self):
        text = _BASE + 'app_dirr = "x"\n' + _IOS + 'bundle_idd = "y"\nzzz = 1\n'
        with pytest.raises(ConfigError) as exc:
            load(text)
        message = exc.value.message
        assert message.splitlines() == [
            "3 unknown keys under [tool.kivy]:",
            f"  'app_dirr' in [tool.kivy] (line {line_of(text, 'app_dirr')}); "
            "did you mean 'app_dir'?",
            f"  'bundle_idd' in [tool.kivy.ios] (line {line_of(text, 'bundle_idd')}); "
            "did you mean 'bundle_id'?",
            f"  'zzz' in [tool.kivy.ios] (line {line_of(text, 'zzz')})",
        ]


class TestAccepted:
    def test_passthrough_tables_take_any_key(self):
        cfg = load(
            _BASE,
            _IOS,
            "[tool.kivy.ios.info_plist]\nUIStatusBarHidden = true\n",
            "[tool.kivy.ios.entitlements]\n'aps-environment' = 'development'\n",
            "[tool.kivy.ios.xcode.build_settings]\nSWIFT_VERSION = '5.0'\n",
            _ANDROID,
            "[tool.kivy.android.manifest.application]\n'android:largeHeap' = 'true'\n",
            "[tool.kivy.android.manifest.placeholders]\nauthority = 'x'\n",
            "[tool.kivy.android.gradle_properties]\n'org.gradle.jvmargs' = '-Xmx4g'\n",
        )
        assert cfg.ios_required.info_plist == {"UIStatusBarHidden": True}
        assert cfg.android_required.gradle_properties == {
            "org.gradle.jvmargs": "-Xmx4g"
        }

    def test_overlay_for_an_unimplemented_platform_is_inert(self):
        # Spec 01: adding one must not break any current command.
        cfg = load(_BASE, _IOS, "[tool.kivy.web]\nschema_version = 1\nanything = 1\n")
        assert cfg.ios is not None

    def test_misspelt_overlay_is_named_when_its_platform_is_targeted(self):
        text = _BASE + _ANDROID.replace("[tool.kivy.android]", "[tool.kivy.andriod]")
        with pytest.raises(ConfigError, match=r"missing \[tool.kivy.android\]") as exc:
            load(text, require_android=True)
        assert exc.value.hint == (
            "found [tool.kivy.andriod]; rename it to [tool.kivy.android]."
        )

    def test_keys_outside_tool_kivy_are_not_ours(self):
        load(
            '[project]\nname = "app"\nversion = "1.0.0"\nlicense = "MIT"\n'
            '[project.scripts]\napp = "app:main"\n'
            "[tool.ruff]\nline-length = 88\n"
            '[tool.kivy]\napp_dir = "src"\n'
        )

    def test_no_kivy_table_is_left_to_the_parser(self):
        with pytest.raises(ConfigError, match=r"missing \[tool.kivy\] table"):
            load('[project]\nname = "app"\nversion = "1.0.0"\n')


_GUIDES = Path(__file__).resolve().parents[2] / "docs" / "guides"
_TOML_BLOCK = re.compile(r"```toml\n(.*?)```", re.S)


def _documented_blocks() -> list[tuple[str, str]]:
    blocks = []
    for page in sorted(_GUIDES.rglob("*.md")):
        for i, match in enumerate(_TOML_BLOCK.finditer(page.read_text("utf-8"))):
            if "tool.kivy" in match.group(1):
                rel = page.relative_to(_GUIDES).as_posix()
                blocks.append((f"{rel}#{i}", match.group(1)))
    return blocks


def test_published_docs_find_toml_examples():
    assert len(_documented_blocks()) > 20


@pytest.mark.parametrize(("where", "body"), _documented_blocks())
def test_published_docs_use_only_known_keys(where: str, body: str):
    """A key the docs show must be one the loader accepts."""
    kivy = tomllib.loads(body).get("tool", {}).get("kivy", {})
    assert [u.key_path for u in find_unknown_keys(kivy)] == []
