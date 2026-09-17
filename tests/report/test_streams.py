"""``stderr_for_child``: a child's output reaches our stderr, byte for byte."""

from __future__ import annotations

import io
import subprocess
import sys

from kivyforge.report.streams import stderr_for_child

# Box-drawing and an em dash: exactly what a cp1252 text pump would mangle.
_TEXT = "BUILD ─ ok — done"
_CHILD = [
    sys.executable,
    "-c",
    "import sys; "
    f"sys.stdout.buffer.write({_TEXT.encode('utf-8')!r} + b'\\n'); "
    "sys.stdout.flush(); "
    "sys.stderr.buffer.write(b'to stderr\\n')",
]


def _run_child() -> None:
    with stderr_for_child() as err:
        subprocess.run(_CHILD, stdout=err, stderr=err, check=True)


def test_real_descriptor_is_passed_through(capfd):
    _run_child()
    out, err = capfd.readouterr()
    assert out == ""
    assert _TEXT in err
    assert "to stderr" in err


def test_pump_fallback_when_stderr_has_no_descriptor(monkeypatch):
    raw = io.BytesIO()
    fake = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stderr", fake)

    _run_child()

    fake.flush()
    # Bytes, not re-encoded text: the UTF-8 survives a cp1252 wrapper intact.
    assert _TEXT.encode("utf-8") in raw.getvalue()
    assert b"to stderr" in raw.getvalue()


def test_pump_fallback_for_a_text_only_stream(monkeypatch):
    fake = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake)

    _run_child()

    assert _TEXT in fake.getvalue()
    assert "to stderr" in fake.getvalue()
