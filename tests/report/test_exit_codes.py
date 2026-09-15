"""The exit-code taxonomy is a contract, so the numbers themselves are pinned.

Asserting on the literal integers looks tautological, and is the point: every
other test refers to these by name, so renumbering one would silently pass the
whole suite while breaking any caller that had learned the number. This file is
the one place that would go red.
"""

from __future__ import annotations

import click
import pytest

from kivyforge.report import exit_codes


class TestReservedNumbers:
    def test_the_numbers_are_what_callers_have_been_told(self):
        assert exit_codes.SUCCESS == 0
        assert exit_codes.CONFIG_ERROR == 1
        assert exit_codes.USAGE_ERROR == 2
        assert exit_codes.ENVIRONMENT_ERROR == 3
        assert exit_codes.LOCK_DRIFT == 4
        assert exit_codes.BUILD_FAILURE == 5

    def test_two_is_clicks_and_we_only_mirror_it(self):
        """The measurement that reordered the taxonomy.

        ``2`` is ``click.UsageError.exit_code`` (and argparse's), so
        ``kivyforge doctor --bogus-flag`` already exited ``2`` before any of this
        existed. The first draft of the taxonomy gave ``2`` to "environment
        missing", which would have made "you typed the command wrong"
        indistinguishable from "this machine lacks a toolchain".
        """
        assert exit_codes.USAGE_ERROR == click.UsageError.exit_code

    def test_success_is_the_only_zero(self):
        assert list(exit_codes.RESERVED).count(0) == 1

    def test_every_code_is_described_exactly_once(self):
        """A number handed to two meanings is the failure this table prevents."""
        codes = [
            exit_codes.SUCCESS,
            exit_codes.CONFIG_ERROR,
            exit_codes.USAGE_ERROR,
            exit_codes.ENVIRONMENT_ERROR,
            exit_codes.LOCK_DRIFT,
            exit_codes.BUILD_FAILURE,
        ]
        assert sorted(exit_codes.RESERVED) == sorted(codes)
        assert len(set(codes)) == len(codes)

    @pytest.mark.parametrize("code", [1, 2, 3, 4, 5])
    def test_no_failure_code_is_zero(self, code):
        assert code != exit_codes.SUCCESS
