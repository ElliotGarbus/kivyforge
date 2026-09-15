"""T3: assert a *built* ``.app`` is the artifact the build promised.

Driven by ``--macos-app`` — until now the repo had never inspected a built
``.app`` at all: ``macos_integration`` proves two ``clang`` tests, and
``kivyforge build -p macos`` had never run anywhere, in CI or by hand, so
``codesign``, ``lipo``, and ``hdiutil`` were exercised only through mocks
(test-matrix.md §3.2). Mirrors ``tests/platforms/android/test_apk_artifact.py``
exactly: the checks themselves are hermetic and unit-tested in
``tests/test_artifact_checks.py``; this module is only the wiring that points
them at a real bundle.

Skips without ``--macos-app`` so a local `pytest` run stays green.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from kivyforge.platforms.macos.machotools import codesign_verify
from tests.artifact_checks import macos_app_problems

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def app(pytestconfig) -> Path:
    given = pytestconfig.getoption("--macos-app")
    if not given:
        pytest.skip("no --macos-app given; T3 needs an artifact to inspect")
    path = Path(given)
    if not path.is_dir():
        pytest.fail(f"--macos-app {path} does not exist or is not a directory")
    return path


def _expected_magic(app: Path) -> bytes:
    """The ``.pyc`` header the bundle's *own* embedded runtime will accept.

    Run the bundle's ``python3`` directly rather than comparing against the
    test runner's own interpreter: macOS builds are native-only (no
    cross-arch), so the embedded interpreter is always executable on the host
    that produced it, and asking it directly is strictly more correct than
    guessing the minor from a file name. This is exactly the manual check
    from the 2026-09-14 validation run, turned into an assertion.
    """
    python3 = app / "Contents" / "Resources" / "python" / "bin" / "python3"
    if not python3.is_file():
        pytest.fail(f"{python3} is missing; cannot determine the shipped .pyc magic")
    proc = subprocess.run(
        [str(python3), "-c", "import importlib.util; print(importlib.util.MAGIC_NUMBER.hex())"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"running the bundle's own python3 failed ({proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return bytes.fromhex(proc.stdout.strip())


def test_the_app_is_internally_consistent(app, pytestconfig):
    arch = pytestconfig.getoption("--macos-arch")
    stripped = pytestconfig.getoption("--macos-stripped")

    # Only ask the bundle's own interpreter for its magic when there is
    # bytecode to judge — mirrors test_apk_artifact.py's same guard.
    expected_magic = _expected_magic(app) if stripped else b""

    problems = macos_app_problems(
        app,
        arch=arch,
        stripped=stripped,
        expected_magic=expected_magic,
    )
    assert not problems, (
        f"{app.name} is not the artifact the build promised "
        f"(arch={arch}, strip_source={'on' if stripped else 'off'}):\n  "
        + "\n  ".join(problems)
    )


def test_the_app_is_codesigned(app):
    """``codesign --verify`` against a *built* app, not the vendored launcher.

    test-matrix.md §5.1 lists "signatures verify" as open for every platform;
    this is the macOS half of that item using the wrapper the bundler itself
    calls (``platforms/macos/machotools.codesign_verify``), so it cannot drift
    from what a real build actually signs with.
    """
    if sys.platform != "darwin":
        pytest.skip("codesign is macOS-only")
    assert codesign_verify(app), f"{app.name} does not have a valid code signature"
