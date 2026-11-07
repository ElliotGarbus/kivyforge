"""T3: assert a *built* APK is the artifact the build promised.

Driven by ``--android-apk`` from the ``android_gradle`` CI job, which already
builds exactly the artifact this inspects and until now threw it away after three
``unzip -l | grep`` presence checks. The checks themselves are hermetic and
unit-tested in ``tests/test_artifact_checks.py``; this module is only the wiring
that points them at a real file.

Skips without ``--android-apk`` so a local `pytest` run stays green.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from kivyforge.bundle.pycompile import find_interpreter
from tests.artifact_checks import android_apk_problems, shipped_python_tags

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def apk(pytestconfig) -> Path:
    given = pytestconfig.getoption("--android-apk")
    if not given:
        pytest.skip("no --android-apk given; T3 needs an artifact to inspect")
    path = Path(given)
    if not path.is_file():
        pytest.fail(f"--android-apk {path} does not exist")
    return path


def _probe_magic(argv: list[str]) -> bytes | None:
    """First four bytes of ``importlib.util.MAGIC_NUMBER`` from *argv*, or None."""
    try:
        probe = subprocess.run(
            [
                *argv,
                "-c",
                "import importlib.util,sys;"
                "sys.stdout.buffer.write(importlib.util.MAGIC_NUMBER)",
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if probe.returncode == 0 and len(probe.stdout) == 4:
        return probe.stdout
    return None


def _expected_magic(apk: Path) -> bytes:
    """The ``.pyc`` header the runtime *this APK ships* will accept.

    Asked of an interpreter rather than taken from a hard-coded table, which
    would need editing every CPython release and would go stale in exactly the
    silent way item 1 did. The APK's own ``libpython`` never runs on the host,
    but magic is keyed to CPython minor, not arch, so any *final* CPython of the
    shipped minor is an exact answer: this one when it matches, else the one
    :func:`find_interpreter` finds. Only if the host has none does this fail,
    naming the runner, rather than downstream where the same mismatch reads as
    "the artifact is broken".
    """
    tags = shipped_python_tags(apk)
    if len(tags) != 1:
        pytest.fail(
            f"expected exactly one CPython runtime in {apk.name}, found {tags}; "
            "cannot tell which .pyc magic to require"
        )

    found = find_interpreter(tags[0])
    if found == ():
        return importlib.util.MAGIC_NUMBER
    if found is not None:
        magic = _probe_magic(list(found))
        if magic is not None:
            return magic

    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    pytest.fail(
        f"{apk.name} ships CPython {tags[0]}, but this test runs under {running} "
        f"and no final CPython {tags[0]} is on this host, so the .pyc magic that "
        f"runtime accepts is unknowable. Install CPython {tags[0]}, or run the "
        "test under it."
    )


def test_the_apk_is_internally_consistent(apk, pytestconfig):
    # Comma-separated for a package built without --abi, which carries every
    # ABI in [tool.kivy.android].abis.
    abi = pytestconfig.getoption("--android-abi")
    abis = tuple(a.strip() for a in abi.split(",") if a.strip())
    stripped = pytestconfig.getoption("--android-stripped")

    # The runner's Python only has to match when there is bytecode to judge; an
    # unstripped payload ships source, so any interpreter can check its shape.
    expected_magic = _expected_magic(apk) if stripped else b""

    problems = android_apk_problems(
        apk,
        abis=abis,
        stripped=stripped,
        expected_magic=expected_magic,
    )
    assert not problems, (
        f"{apk.name} is not the artifact the build promised "
        f"(abi={abi}, strip_source={'on' if stripped else 'off'}):\n  "
        + "\n  ".join(problems)
    )
