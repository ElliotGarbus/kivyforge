"""``[[tool.kivy.index]]`` and the ``sources`` tables (#86)."""

from __future__ import annotations

import textwrap

import pytest

from kivyforge.config import ConfigError, load_config_from_text
from kivyforge.config.model import PackageIndex
from kivyforge.lock.inputs import lock_inputs_sha256

BASE = """\
[project]
name = "app"
version = "1.0.0"
requires-python = ">=3.13"
dependencies = ["kivy"]

[tool.kivy]
app_dir = "src"
"""

IOS = """\
[tool.kivy.ios]
schema_version = 1
bundle_id = "org.example.app"
python = { version = "3.15.0" }
"""

ANDROID = """\
[tool.kivy.android]
schema_version = 1
package = "org.example.app"
python = { version = "3.14.6" }
"""

MOBILE = """\
[[tool.kivy.index]]
name = "mobile"
url = "https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"
explicit = true

[[tool.kivy.index]]
name = "corp"
url = "https://pypi.example.com/simple"
"""


def load(*parts: str):
    text = "\n".join(textwrap.dedent(p) for p in parts)
    return load_config_from_text(text, require_ios=False)


def error(*parts: str) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load(*parts)
    return caught.value


class TestIndexes:
    def test_parsed_in_order(self):
        config = load(BASE, MOBILE)
        assert config.kivy.indexes == (
            PackageIndex(
                "mobile",
                "https://elliotgarbus.github.io/kivy-mobile-wheels/simple/",
                explicit=True,
            ),
            PackageIndex("corp", "https://pypi.example.com/simple"),
        )

    @pytest.mark.parametrize(
        ("entry", "message"),
        [
            ('name = "a b"\nurl = "https://x/simple/"', "needs a name"),
            ('name = "PyPI"\nurl = "https://x/simple/"', "reserved"),
            ('name = "a"', "needs a url"),
            ('name = "a"\nurl = "file:///wheels"', "http:// or https://"),
            ('name = "a"\nurl = "https://u:p@x/simple/"', "username or password"),
            (
                'name = "a"\nurl = "https://x/simple/"\nexplicit = "yes"',
                "true or false",
            ),
        ],
    )
    def test_invalid_entry(self, entry, message):
        exc = error(BASE, f"[[tool.kivy.index]]\n{entry}\n")
        assert message in exc.message
        assert exc.key_path is not None and exc.key_path.startswith(
            "tool.kivy.index[0]"
        )

    def test_duplicate_name(self):
        exc = error(
            BASE,
            '[[tool.kivy.index]]\nname = "a"\nurl = "https://x/simple/"\n'
            '[[tool.kivy.index]]\nname = "a"\nurl = "https://y/simple/"\n',
        )
        assert "two [[tool.kivy.index]] entries are named 'a'" in exc.message

    def test_unknown_key_in_an_entry_is_reported(self):
        exc = error(
            BASE,
            '[[tool.kivy.index]]\nname = "a"\nurl = "https://x/"\ndefault = true\n',
        )
        assert "default" in exc.format()


class TestSources:
    def test_shared_pins_reach_every_overlay(self):
        config = load(
            BASE,
            MOBILE,
            '[tool.kivy.sources]\nKivy = { index = "mobile" }\n',
            IOS,
            ANDROID,
        )
        assert config.kivy.sources == (("kivy", "mobile"),)
        assert config.ios is not None and config.android is not None
        assert config.ios.sources == (("kivy", "mobile"),)
        assert config.android.sources == (("kivy", "mobile"),)

    def test_an_overlay_entry_replaces_the_shared_one_and_adds(self):
        config = load(
            BASE,
            MOBILE,
            '[tool.kivy.sources]\nkivy = { index = "corp" }\n',
            ANDROID,
            '[tool.kivy.android.sources]\nKIVY = { index = "mobile" }\npyjnius = { index = "pypi" }\n',
            IOS,
        )
        assert config.ios is not None and config.android is not None
        assert config.android.sources == (("kivy", "mobile"), ("pyjnius", "pypi"))
        assert config.ios.sources == (("kivy", "corp"),)

    def test_effective_indexes_are_non_explicit_plus_the_explicit_pinned(self):
        config = load(
            BASE,
            MOBILE,
            ANDROID,
            '[tool.kivy.android.sources]\nkivy = { index = "mobile" }\n',
            IOS,
        )
        assert config.ios is not None and config.android is not None
        assert [i.name for i in config.android.indexes] == ["mobile", "corp"]
        assert [i.name for i in config.ios.indexes] == ["corp"]

    def test_unknown_index_suggests_the_closest(self):
        exc = error(BASE, MOBILE, '[tool.kivy.sources]\nkivy = { index = "mobil" }\n')
        assert "not declared in [[tool.kivy.index]]" in exc.message
        assert exc.hint == "did you mean 'mobile'?"
        assert exc.key_path == "tool.kivy.sources.kivy"

    @pytest.mark.parametrize("key", ["git", "url", "path", "marker"])
    def test_uv_only_keys_say_why(self, key):
        exc = error(
            BASE, f'[tool.kivy.sources]\nkivy = {{ index = "pypi", {key} = "x" }}\n'
        )
        assert f"uses {key!r}" in exc.message
        assert "prebuilt wheels" in exc.message

    def test_a_bare_string_is_rejected(self):
        exc = error(BASE, '[tool.kivy.sources]\nkivy = "pypi"\n')
        assert 'must be { index = "NAME" }' in exc.message

    def test_overlay_sources_are_checked_too(self):
        exc = error(
            BASE, ANDROID, '[tool.kivy.android.sources]\nkivy = { index = "nope" }\n'
        )
        assert exc.key_path == "tool.kivy.android.sources.kivy"


class TestLockInputs:
    def test_a_pin_for_android_does_not_stale_ios(self):
        plain = load(BASE, MOBILE, IOS, ANDROID)
        pinned = load(
            BASE,
            MOBILE,
            IOS,
            ANDROID,
            '[tool.kivy.android.sources]\nkivy = { index = "mobile" }\n',
        )
        assert lock_inputs_sha256(plain, "ios") == lock_inputs_sha256(pinned, "ios")
        assert lock_inputs_sha256(plain, "android") != lock_inputs_sha256(
            pinned, "android"
        )

    def test_an_unused_explicit_index_is_not_an_input(self):
        without = load(BASE, IOS)
        with_explicit = load(
            BASE,
            '[[tool.kivy.index]]\nname = "m"\nurl = "https://m/simple/"\nexplicit = true\n',
            IOS,
        )
        assert lock_inputs_sha256(without, "ios") == lock_inputs_sha256(
            with_explicit, "ios"
        )

    def test_reordering_extra_index_urls_changes_the_hash(self):
        a = load(
            BASE,
            ANDROID.replace(
                "\n", '\nextra_index_urls = ["https://a/", "https://b/"]\n', 1
            ),
        )
        b = load(
            BASE,
            ANDROID.replace(
                "\n", '\nextra_index_urls = ["https://b/", "https://a/"]\n', 1
            ),
        )
        assert lock_inputs_sha256(a, "android") != lock_inputs_sha256(b, "android")
