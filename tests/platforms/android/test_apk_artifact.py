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
import sys
from pathlib import Path

import pytest

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


def _expected_magic(apk: Path) -> bytes:
    """The ``.pyc`` header the runtime *this APK ships* will accept.

    Taken from the running interpreter rather than a hard-coded table, which
    would need editing every CPython release and would go stale in exactly the
    silent way item 1 did. That makes the runner's Python part of the test
    definition, so the job must run under the minor the APK ships — and when it
    does not, this fails naming the *runner*, rather than downstream where the
    same mismatch reads as "the artifact is broken".
    """
    tags = shipped_python_tags(apk)
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if len(tags) != 1:
        pytest.fail(
            f"expected exactly one CPython runtime in {apk.name}, found {tags}; "
            "cannot tell which .pyc magic to require"
        )
    if tags[0] != running:
        pytest.fail(
            f"{apk.name} ships CPython {tags[0]}, but this test is running under "
            f"{running}, so it cannot know which .pyc magic that runtime accepts. "
            f"Pin the CI job's setup-python to {tags[0]}."
        )
    return importlib.util.MAGIC_NUMBER


def test_the_apk_is_internally_consistent(apk, pytestconfig):
    abi = pytestconfig.getoption("--android-abi")
    stripped = pytestconfig.getoption("--android-stripped")

    # The runner's Python only has to match when there is bytecode to judge; an
    # unstripped payload ships source, so any interpreter can check its shape.
    expected_magic = _expected_magic(apk) if stripped else b""

    problems = android_apk_problems(
        apk,
        abi=abi,
        stripped=stripped,
        expected_magic=expected_magic,
    )
    assert not problems, (
        f"{apk.name} is not the artifact the build promised "
        f"(abi={abi}, strip_source={'on' if stripped else 'off'}):\n  "
        + "\n  ".join(problems)
    )
