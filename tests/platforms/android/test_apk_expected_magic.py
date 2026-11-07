"""Which ``.pyc`` magic the APK T3 driver demands, decided without a real APK.

The driver (``test_apk_artifact.py``) is integration-only, so the anchoring it
relies on is pinned here: the magic comes from a final CPython of the minor the
APK *ships*, found on the host when the runner is a different minor.
"""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

from tests.platforms.android import test_apk_artifact as driver


def _apk(tmp_path: Path, minor: str) -> Path:
    path = tmp_path / "app.apk"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"lib/arm64-v8a/libpython{minor}.so", b"")
    return path


def test_a_runner_of_the_shipped_minor_answers_itself(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        driver, "find_interpreter", lambda minor: seen.append(minor) or ()
    )
    assert driver._expected_magic(_apk(tmp_path, "3.14")) == importlib.util.MAGIC_NUMBER
    assert seen == ["3.14"]


def test_another_minor_asks_the_interpreter_found_for_the_shipped_one(
    tmp_path, monkeypatch
):
    seen = []

    def find(minor):
        seen.append(minor)
        return (sys.executable,)

    monkeypatch.setattr(driver, "find_interpreter", find)
    magic = driver._expected_magic(_apk(tmp_path, "3.99"))
    assert seen == ["3.99"]
    # The probe really ran the interpreter it was handed.
    assert magic == importlib.util.MAGIC_NUMBER


def test_no_interpreter_of_the_shipped_minor_fails_naming_the_runner(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(driver, "find_interpreter", lambda minor: None)
    with pytest.raises(pytest.fail.Exception, match="no final CPython 3.99"):
        driver._expected_magic(_apk(tmp_path, "3.99"))


def test_an_interpreter_that_will_not_run_is_not_an_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(
        driver, "find_interpreter", lambda minor: (str(tmp_path / "missing"),)
    )
    with pytest.raises(pytest.fail.Exception, match="unknowable"):
        driver._expected_magic(_apk(tmp_path, "3.99"))
