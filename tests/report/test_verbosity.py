"""The ``-v`` level and the rerun-it-yourself command line (issue #64)."""

from __future__ import annotations

import pytest

from kivyforge.report.verbosity import (
    MAX_VERBOSITY,
    command_line,
    current_verbosity,
    verbosity_to,
)


class TestLevel:
    def test_the_default_is_level_0(self):
        """Outside any verb nothing is verbose: a forgotten verbosity_to is quiet."""
        assert current_verbosity() == 0

    def test_set_for_the_context_and_reset_after(self):
        with verbosity_to(1):
            assert current_verbosity() == 1
            with verbosity_to(2):
                assert current_verbosity() == 2
            assert current_verbosity() == 1
        assert current_verbosity() == 0

    @pytest.mark.parametrize(("given", "level"), [(7, MAX_VERBOSITY), (-3, 0)])
    def test_clamped(self, given, level):
        with verbosity_to(given):
            assert current_verbosity() == level


class TestCommandLine:
    def test_posix_uses_shell_quoting(self):
        argv = ["./gradlew", "--console=plain", "a b", "it's"]
        assert command_line(argv, windows=False) == (
            "./gradlew --console=plain 'a b' 'it'\"'\"'s'"
        )

    def test_windows_leaves_plain_arguments_bare(self):
        argv = [".\\gradlew.bat", "--console=plain", "--stacktrace", "assembleDebug"]
        assert command_line(argv, windows=True) == (
            ".\\gradlew.bat --console=plain --stacktrace assembleDebug"
        )

    def test_windows_quotes_a_space(self):
        argv = ["C:\\Program Files\\sdk\\sdkmanager.bat", "--sdk_root=C:\\my sdk"]
        assert command_line(argv, windows=True) == (
            '"C:\\Program Files\\sdk\\sdkmanager.bat" "--sdk_root=C:\\my sdk"'
        )

    @pytest.mark.parametrize(
        ("arg", "quoted"),
        [
            # PowerShell ends a statement at ';': sdkmanager's package ids.
            ("ndk;27.2.12479018", '"ndk;27.2.12479018"'),
            ("a,b", '"a,b"'),
            ("a&b", '"a&b"'),
            ('say"hi', '"say\\"hi"'),
            # A backslash before the added closing quote must be doubled.
            ("x;y\\", '"x;y\\\\"'),
            ("", '""'),
        ],
    )
    def test_windows_quotes_shell_metacharacters(self, arg, quoted):
        assert command_line([arg], windows=True) == quoted
