"""Windows-safe artifact naming (windows-spec)."""

from __future__ import annotations

import pytest

from kivyforge.platforms.windows.naming import windows_safe_name


class TestWindowsSafeName:
    def test_plain_name_unchanged(self):
        assert windows_safe_name("MyApp") == "MyApp"

    def test_interior_space_kept(self):
        assert windows_safe_name("My App") == "My App"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("My:App", "My App"),
            ("a/b", "a b"),
            ("a\\b", "a b"),
            ('quote"here', "quote here"),
            ("pipe|name", "pipe name"),
            ("q?mark", "q mark"),
            ("star*name", "star name"),
            ("lt<gt>", "lt gt"),
        ],
    )
    def test_illegal_chars_replaced_and_collapsed(self, raw, expected):
        assert windows_safe_name(raw) == expected

    def test_control_chars_stripped(self):
        assert windows_safe_name("a\x00\x1fb") == "a b"

    def test_trailing_dot_stripped(self):
        assert windows_safe_name("MyApp.") == "MyApp"

    def test_trailing_dots_and_spaces_stripped(self):
        assert windows_safe_name("MyApp. . ") == "MyApp"

    def test_leading_and_trailing_space_stripped(self):
        assert windows_safe_name("  MyApp  ") == "MyApp"

    def test_collapses_whitespace_runs(self):
        assert windows_safe_name("My    App") == "My App"

    def test_empty_falls_back(self):
        assert windows_safe_name("") == "App"

    def test_all_illegal_falls_back(self):
        assert windows_safe_name("///") == "App"

    def test_custom_fallback(self):
        assert windows_safe_name("", fallback="Kivy") == "Kivy"

    @pytest.mark.parametrize("reserved", ["CON", "con", "PRN", "NUL", "COM1", "LPT9"])
    def test_reserved_device_names_suffixed(self, reserved):
        result = windows_safe_name(reserved)
        assert result == f"{reserved}_"

    def test_reserved_stem_with_extension_suffixed(self):
        # "NUL.txt" is still a reserved-device collision on Windows.
        assert windows_safe_name("NUL.txt") == "NUL.txt_"

    def test_non_reserved_lookalike_kept(self):
        assert windows_safe_name("CONSOLE") == "CONSOLE"

    def test_unicode_kept(self):
        assert windows_safe_name("Café App") == "Café App"
