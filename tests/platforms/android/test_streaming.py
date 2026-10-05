"""run_streaming: live output from slow tools, and a sign of life (#74, #84)."""

from __future__ import annotations

import sys

from kivyforge.platforms.android.streaming import elapsed, run_streaming


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_segments_split_on_carriage_returns_and_newlines():
    """sdkmanager redraws its bar with \\r; each redraw is its own segment."""
    seen: list[str] = []
    code = (
        "import sys; sys.stdout.write('a 1%\\ra 50%\\ra 100%\\nnext\\n');"
        " sys.stderr.write('warn\\n'); sys.exit(3)"
    )
    returncode, transcript = run_streaming(
        _python(code), on_segment=lambda s: bool(seen.append(s))
    )
    assert returncode == 3
    # stdout's segments keep their order; merged stderr may land anywhere.
    assert [s for s in seen if s != "warn"] == ["a 1%", "a 50%", "a 100%", "next"]
    assert "warn" in seen
    assert transcript.splitlines() == seen


def test_quiet_callback_fires_when_nothing_is_shown():
    quiet: list[float] = []
    run_streaming(
        _python("import time; print('hidden'); time.sleep(1.6)"),
        on_segment=lambda s: False,
        on_quiet=quiet.append,
        quiet_sec=0.5,
    )
    assert quiet, "a long silence should be reported"


def test_a_shown_segment_resets_the_quiet_clock():
    quiet: list[float] = []
    code = "import time\nfor i in range(4):\n    print(i, flush=True); time.sleep(0.3)"
    run_streaming(
        _python(code), on_segment=lambda s: True, on_quiet=quiet.append, quiet_sec=1.0
    )
    assert quiet == []


def test_undecodable_bytes_do_not_crash():
    seen: list[str] = []
    run_streaming(
        _python("import sys; sys.stdout.buffer.write(b'ok \\xff\\n')"),
        on_segment=lambda s: bool(seen.append(s)),
    )
    assert seen and seen[0].startswith("ok ")


def test_elapsed():
    assert elapsed(40) == "40s"
    assert elapsed(95) == "1m 35s"
