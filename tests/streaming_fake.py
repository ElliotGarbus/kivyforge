"""Fake ``kivyforge.streaming.run_streaming`` from a ``subprocess.run``-shaped fake.

The pip lock resolvers stream pip through ``run_streaming``; tests that build a
command and return a canned result keep writing ``fake_run(cmd, **kw)`` returning
an object with ``returncode`` (and optionally ``stdout``/``stderr``), and patch
the resolver module's ``run_streaming`` with ``streaming(fake_run)``.
"""

from __future__ import annotations

import subprocess


def streaming(fake_run):
    """Adapt a ``subprocess.run``-shaped fake to the resolvers' streaming seam."""

    def run_streaming(cmd, *, on_segment, env=None, cwd=None, on_quiet=None, **_kw):
        result = fake_run(
            cmd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
        parts = (getattr(result, "stdout", None), getattr(result, "stderr", None))
        text = "\n".join(p for p in parts if isinstance(p, str))
        for line in text.splitlines():
            if line.strip():
                on_segment(line)
        return result.returncode, text

    return run_streaming
