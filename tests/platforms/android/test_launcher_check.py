"""T3: javac decides every property of a main_activity launcher.

``KivyforgeLauncherCheck.java`` (``generate/launcher.py``) claims that one
expression, ``PythonActivity x = new <configured>()``, compiles exactly when
the class is a usable launcher. This compiles the check kivyforge renders
against a matrix of candidates in a real generated project: two valid ones
(Java and Kotlin, since javac sees Kotlin classes in a mixed module) and one
per way a class can fail, each asserting the javac line a user would read.

Driven by ``--android-gradle-project``: a generated ``<slug>-android`` built
once, with ``[tool.kivy.android.src].kotlin`` set so the Kotlin plugin is
applied. The candidates and the check are written into it and removed after,
so the project builds as before. Skips without the option, so a local
`pytest` run stays green.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from kivyforge.config.model import AndroidConfig
from kivyforge.platforms.android.generate.launcher import (
    LAUNCHER_CHECK_RELPATH,
    render_launcher_check,
)

pytestmark = pytest.mark.integration

PACKAGE = "org.kivyforge.t3.launcher"

#: Candidate sources, by file name. Each one is a class kivyforge could be
#: pointed at; the matrix below says what javac must make of it.
CANDIDATES = {
    "ValidJava.java": "public class ValidJava extends PythonActivity {}\n",
    "ValidKotlin.kt": "class ValidKotlin : org.kivy.android.PythonActivity()\n",
    "WrongBase.java": "public class WrongBase extends android.app.Activity {}\n",
    "AbstractAct.java": "public abstract class AbstractAct extends PythonActivity {}\n",
    "NoDefaultCtor.java": (
        "public class NoDefaultCtor extends PythonActivity {\n"
        "    public NoDefaultCtor(int x) {}\n"
        "}\n"
    ),
    "PrivateCtor.java": (
        "public class PrivateCtor extends PythonActivity {\n"
        "    private PrivateCtor() {}\n"
        "}\n"
    ),
    "NotPublic.java": "class NotPublic extends PythonActivity {}\n",
}

MATRIX = [
    ("ValidJava", None),
    ("ValidKotlin", None),
    ("DoesNotExist", "cannot find symbol"),
    ("org.nowhere.Nothing", "package org.nowhere does not exist"),
    ("WrongBase", "incompatible types"),
    ("AbstractAct", "is abstract; cannot be instantiated"),
    ("NoDefaultCtor", "cannot be applied to given types"),
    ("PrivateCtor", "has private access"),
    ("NotPublic", "is not public in"),
]


def _source(name: str, body: str) -> str:
    if name.endswith(".kt"):
        return f"package {PACKAGE}\n\n{body}"
    return f"package {PACKAGE};\n\nimport org.kivy.android.PythonActivity;\n\n{body}"


@pytest.fixture(scope="module")
def gradle_project(pytestconfig):
    given = pytestconfig.getoption("--android-gradle-project")
    if not given:
        pytest.skip("no --android-gradle-project given; the matrix needs Gradle")
    root = Path(given)
    if not (root / "app" / "build.gradle").is_file():
        pytest.fail(f"--android-gradle-project {root} is not a generated project")
    if "org.jetbrains.kotlin.android" not in (root / "app" / "build.gradle").read_text(
        encoding="utf-8"
    ):
        pytest.fail(
            f"{root} does not apply the Kotlin plugin; generate it with "
            "[tool.kivy.android.src].kotlin set"
        )

    main = root / "app" / "src" / "main"
    candidates = main / "java" / Path(*PACKAGE.split("."))
    check = main / LAUNCHER_CHECK_RELPATH
    original = check.read_bytes() if check.is_file() else None
    candidates.mkdir(parents=True, exist_ok=False)
    try:
        for name, body in CANDIDATES.items():
            (candidates / name).write_text(_source(name, body), encoding="utf-8")
        yield root, check
    finally:
        for path in candidates.iterdir():
            path.unlink()
        candidates.rmdir()
        if original is None:
            check.unlink(missing_ok=True)
        else:
            check.write_bytes(original)


def _compile(root: Path) -> subprocess.CompletedProcess:
    gradlew = root / ("gradlew.bat" if os.name == "nt" else "gradlew")
    return subprocess.run(
        [str(gradlew), ":app:compileDebugJavaWithJavac", "--offline", "-q"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )


@pytest.mark.parametrize(("candidate", "javac_says"), MATRIX)
def test_the_check_compiles_exactly_for_a_usable_launcher(
    gradle_project, candidate, javac_says
):
    root, check = gradle_project
    name = candidate if "." in candidate else f"{PACKAGE}.{candidate}"
    android = AndroidConfig(
        schema_version=1, package="org.kivyforge.t3", main_activity=name
    )
    rendered = render_launcher_check(android)
    assert rendered is not None
    check.parent.mkdir(parents=True, exist_ok=True)
    check.write_text(rendered.content, encoding="utf-8", newline="\n")

    result = _compile(root)
    output = result.stdout + result.stderr
    if javac_says is None:
        assert result.returncode == 0, f"{name} should compile:\n{output}"
    else:
        assert result.returncode != 0, f"{name} compiled but is not a launcher"
        assert javac_says in output, output
        assert "KivyforgeLauncherCheck.java" in output, output
