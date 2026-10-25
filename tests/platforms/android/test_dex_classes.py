"""T3: assert the classes a build was meant to compile are in the APK's dex.

A ``[tool.kivy.android.src]`` root that Gradle cannot find compiles to nothing
and the build still succeeds, which is how that key shipped without ever
compiling a class. Only the dex can say whether a class reached the app.

Driven by ``--android-apk`` plus one ``--android-dex-class`` per class. The
CI job builds ``hello-android`` with the marker roots under
``tests/fixtures/android-src/`` added (one Java class, one Kotlin class), so
both compile paths are proved. The check itself is hermetic and unit-tested in
``tests/test_artifact_checks.py``.

Skips without both options so a local `pytest` run stays green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.artifact_checks import android_dex_problems

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


def test_the_expected_classes_were_compiled_in(apk, pytestconfig):
    classes = pytestconfig.getoption("--android-dex-class")
    if not classes:
        pytest.skip("no --android-dex-class given; nothing to look for")
    problems = android_dex_problems(apk, classes=classes)
    assert not problems, (
        f"{apk.name} lacks classes the build was meant to compile:\n  "
        + "\n  ".join(problems)
    )
