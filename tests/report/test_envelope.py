"""The ``--json`` envelope's shape is a contract, so it is pinned here.

The point of these tests is not that ``json.dumps`` works. It is that the two
promises the envelope makes to a consumer -- *this shape is versioned* and *these
keys are always here* -- cannot be broken without a test going red. Both are the
kind of promise that is easy to erode one convenient omission at a time.
"""

from __future__ import annotations

import json

from kivyforge.report import Diagnostic, Envelope, diagnostics
from kivyforge.report.envelope import SCHEMA_VERSION


def _envelope(**kwargs) -> Envelope:
    base = {"command": "doctor", "kivyforge": "3.0.0.dev0", "ok": True}
    return Envelope(**{**base, **kwargs})


class TestShape:
    def test_top_level_keys_are_exactly_the_documented_seven(self):
        assert set(_envelope().as_dict()) == {
            "schema",
            "kivyforge",
            "command",
            "platform",
            "ok",
            "data",
            "diagnostics",
        }

    def test_data_and_diagnostics_are_present_even_when_empty(self):
        """Absent containers force every consumer to write the same defensive
        ``get(..., [])``, and whoever forgets is bitten on the rare path."""
        payload = _envelope().as_dict()
        assert payload["data"] == {}
        assert payload["diagnostics"] == []

    def test_platform_key_is_present_even_when_there_is_no_platform(self):
        payload = _envelope(platform=None).as_dict()
        assert "platform" in payload
        assert payload["platform"] is None

    def test_schema_is_an_int_and_comes_first(self):
        """First for the human reading a dump; an int so a consumer can compare
        it with ``<`` rather than parsing a version string."""
        payload = _envelope().as_dict()
        assert isinstance(payload["schema"], int)
        assert next(iter(payload)) == "schema"
        assert payload["schema"] == SCHEMA_VERSION

    def test_data_is_copied_not_aliased(self):
        """A caller mutating its own dict afterwards must not retroactively
        change what was reported."""
        source: dict[str, object] = {"mode": "project"}
        payload = _envelope(data=source).as_dict()
        source["mode"] = "environment"
        assert payload["data"] == {"mode": "project"}


class TestSerialisation:
    def test_round_trips(self):
        text = _envelope(platform="linux", data={"mode": "project"}).to_json()
        assert json.loads(text)["data"] == {"mode": "project"}

    def test_ends_with_exactly_one_newline(self):
        """So the document concatenates cleanly and looks right in a terminal."""
        text = _envelope().to_json()
        assert text.endswith("}\n")
        assert not text.endswith("\n\n")

    def test_non_ascii_is_escaped_so_output_survives_any_stream_encoding(self):
        """The machine path must not be able to raise ``UnicodeEncodeError``.

        A right arrow is not representable in cp1252, which is what a redirected
        Windows stdout falls back to. Escaping it means ``--json > out.json``
        cannot fail there, and does not depend on the message-content guard in
        ``tests/test_message_encoding.py`` holding forever.
        """
        text = _envelope(data={"note": "a \u2192 b"}).to_json()
        assert "\\u2192" in text
        assert text.encode("cp1252")  # the real assertion: this does not raise
        assert json.loads(text)["data"]["note"] == "a \u2192 b"


class TestDiagnosticSerialisation:
    def test_required_fields_always_present(self):
        payload = Diagnostic(
            code=diagnostics.HOST_INCAPABLE,
            severity=diagnostics.ERROR,
            message="cannot build iOS from Windows",
        ).as_dict()
        assert payload == {
            "code": "KF-HOST-INCAPABLE",
            "severity": "error",
            "message": "cannot build iOS from Windows",
        }

    def test_empty_remediation_and_context_are_omitted_not_blank(self):
        """An absent key reads as 'nothing to say'; ``""`` invites a consumer to
        print a blank remediation line."""
        payload = Diagnostic(
            code=diagnostics.DOCTOR_CHECK, severity=diagnostics.WARNING, message="m"
        ).as_dict()
        assert "remediation" not in payload
        assert "context" not in payload

    def test_remediation_and_context_survive_when_set(self):
        payload = Diagnostic(
            code=diagnostics.LOCK_DRIFT,
            severity=diagnostics.ERROR,
            message="out of date",
            remediation="run kivyforge lock -p linux",
            context={"check": "Lock freshness"},
        ).as_dict()
        assert payload["remediation"] == "run kivyforge lock -p linux"
        assert payload["context"] == {"check": "Lock freshness"}
