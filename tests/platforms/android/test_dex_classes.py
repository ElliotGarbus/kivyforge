"""T3: assert the classes a build was meant to compile are in the APK's dex.

A ``[tool.kivy.android.src]`` root that Gradle cannot find compiles to nothing
and the build still succeeds, which is how that key shipped without ever
compiling a class. Only the dex can say whether a class reached the app.

Driven by ``--android-apk`` plus what to look for: one ``--android-dex-class``
per class, and/or ``--android-project``, whose
``[tool.kivy.android].main_activity`` (when set) must be in the dex. The CI job
builds ``hello-android`` with the marker roots under
``tests/fixtures/android-src/`` added (one Java class, one Kotlin class), so
both compile paths are proved, and builds ``android-activity-class`` with its
project. The check itself is hermetic and unit-tested in
``tests/test_artifact_checks.py``.

Skips without an APK, or with nothing to look for, so a local `pytest` run
stays green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kivyforge.config.loader import load_config
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


def _project_classes(given: str | None) -> list[str]:
    if not given:
        return []
    pyproject = Path(given) / "pyproject.toml"
    if not pyproject.is_file():
        pytest.fail(f"--android-project {given} has no pyproject.toml")
    config = load_config(pyproject, require_ios=False, require_android=True)
    launcher = config.android_required.main_activity
    return [launcher] if launcher else []


def test_the_expected_classes_were_compiled_in(apk, pytestconfig):
    classes = [
        *pytestconfig.getoption("--android-dex-class"),
        *_project_classes(pytestconfig.getoption("--android-project")),
    ]
    if not classes:
        pytest.skip(
            "nothing to look for: no --android-dex-class, and no "
            "--android-project with a main_activity"
        )
    problems = android_dex_problems(apk, classes=classes)
    assert not problems, (
        f"{apk.name} lacks classes the build was meant to compile:\n  "
        + "\n  ".join(problems)
    )
