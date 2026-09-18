"""T3: assert a *built* Windows onedir bundle is the artifact the build promised.

Driven by ``--windows-onedir``, pointed at the **dist** copy
(``dist/windows/<bundle>-<version>-<arch>/``) rather than the ``build/`` tree —
the same distinction the Linux driver makes between an AppImage/AppDir and the
staged tree, since the dist copy is the actual distributable. Mirrors
``tests/platforms/macos/test_app_artifact.py`` structure exactly: the checks
themselves are hermetic and unit-tested in ``tests/test_artifact_checks.py``;
this module is only the wiring that points them at a real bundle.

Skips without ``--windows-onedir`` so a local `pytest` run stays green.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.artifact_checks import windows_onedir_problems

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def bundle(pytestconfig) -> Path:
    given = pytestconfig.getoption("--windows-onedir")
    if not given:
        pytest.skip("no --windows-onedir given; T3 needs an artifact to inspect")
    path = Path(given)
    if not path.is_dir():
        pytest.fail(f"--windows-onedir {path} does not exist or is not a directory")
    return path


def _expected_magic(bundle: Path) -> bytes:
    """The ``.pyc`` header the bundle's *own* embedded runtime will accept.

    Run the bundle's own ``python\\python.exe`` directly rather than comparing
    against the test runner's own interpreter — same reasoning as the macOS
    driver's ``_expected_magic()``, just a different relative path to the
    interpreter.
    """
    python_exe = bundle / "python" / "python.exe"
    if not python_exe.is_file():
        pytest.fail(f"{python_exe} is missing; cannot determine the shipped .pyc magic")
    proc = subprocess.run(
        [
            str(python_exe),
            "-c",
            "import importlib.util; print(importlib.util.MAGIC_NUMBER.hex())",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"running the bundle's own python.exe failed ({proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return bytes.fromhex(proc.stdout.strip())


def test_the_bundle_is_internally_consistent(bundle, pytestconfig):
    arch = pytestconfig.getoption("--windows-arch")
    stripped = pytestconfig.getoption("--windows-stripped")

    # Only ask the bundle's own interpreter for its magic when there is
    # bytecode to judge — mirrors test_app_artifact.py's same guard.
    expected_magic = _expected_magic(bundle) if stripped else b""

    problems = windows_onedir_problems(
        bundle,
        arch=arch,
        stripped=stripped,
        expected_magic=expected_magic,
    )
    assert not problems, (
        f"{bundle.name} is not the artifact the build promised "
        f"(arch={arch}, strip_source={'on' if stripped else 'off'}):\n  "
        + "\n  ".join(problems)
    )
