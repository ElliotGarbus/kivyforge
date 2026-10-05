"""Run Android Lint's NewApi check over a generated kivyforge Android project.

NewApi flags a call to an API newer than ``min_sdk``. On a device below that
API the call is a NoSuchMethodError, and nothing earlier says so: kivyforge's
bootstrap read its unpack stamp through ``java.nio.file`` (API 26) for two
releases, and every app crashed on its second launch on Android 7.

The check runs here, in kivyforge's CI, rather than in the release lint gate
``kivyforge package`` runs. All Java in a generated project is kivyforge's own
or vendored, so a finding is something only kivyforge can fix; failing a user's
release over it would block them without giving them anything to change.

The generated ``app/build.gradle`` limits lint to the release gate's checks.
This narrows it to NewApi instead, includes the instrumented-test sources (they
run on the same devices), and points lint at a config that ignores SDL's Java
glue: it is vendored unchanged, and keeps its newer calls in ``*_API26``
classes it only creates on API 26+, which lint cannot see.

The edit is to the generated project's copy and is undone by the next
``kivyforge build``. Run that first.

Usage: python scripts/lint_newapi.py <generated-project-dir>
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

LINT_CONFIG_NAME = "kivyforge-newapi-lint.xml"

LINT_CONFIG = """\
<?xml version="1.0" encoding="UTF-8"?>
<lint>
    <issue id="NewApi">
        <ignore path="src/main/java/org/libsdl/**" />
    </issue>
</lint>
"""

_CHECK_ONLY = re.compile(r"checkOnly\.addAll\(\[[^\]]*\]\)")
_FATAL = re.compile(r"fatal\.addAll\(\[[^\]]*\]\)")
_ABORT = "abortOnError = true"


class LintSetupError(Exception):
    pass


def newapi_build_gradle(text: str) -> str:
    """The generated app/build.gradle with its lint block narrowed to NewApi."""
    for pattern, what in ((_CHECK_ONLY, "checkOnly"), (_FATAL, "fatal")):
        if len(pattern.findall(text)) != 1:
            raise LintSetupError(
                f"app/build.gradle: expected one lint {what}.addAll([...]) line; "
                "the generated lint block changed shape."
            )
    if text.count(_ABORT) != 1:
        raise LintSetupError(f"app/build.gradle: expected one '{_ABORT}' line.")
    text = _CHECK_ONLY.sub("checkOnly.addAll(['NewApi'])", text)
    text = _FATAL.sub("fatal.addAll(['NewApi'])", text)
    return text.replace(
        _ABORT,
        f"{_ABORT}\n        checkTestSources = true\n"
        f"        lintConfig = file('{LINT_CONFIG_NAME}')",
    )


def findings(report: Path) -> list[str]:
    """``path:line: message`` for each issue in lint's XML report."""
    root = ET.parse(report).getroot()
    out = []
    for issue in root.iter("issue"):
        location = issue.find("location")
        where = "?"
        if location is not None:
            where = f"{location.get('file', '?')}:{location.get('line', '?')}"
        out.append(f"{where}: {issue.get('message', '')}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    project = Path(argv[0]).resolve()
    app = project / "app"
    gradle_file = app / "build.gradle"
    if not gradle_file.is_file():
        print(
            f"no generated project at {project} (missing {gradle_file})",
            file=sys.stderr,
        )
        return 1
    try:
        narrowed = newapi_build_gradle(gradle_file.read_text(encoding="utf-8"))
    except LintSetupError as exc:
        print(exc, file=sys.stderr)
        return 1
    gradle_file.write_text(narrowed, encoding="utf-8")
    (app / LINT_CONFIG_NAME).write_text(LINT_CONFIG, encoding="utf-8")

    from kivyforge.platforms.android.gradlew import GradleError, run_gradle

    report = app / "build" / "reports" / "lint-results-debug.xml"
    report.unlink(missing_ok=True)
    try:
        run_gradle(project, ["lintDebug"])
    except GradleError as exc:
        if not report.is_file():
            print(f"lintDebug failed before reporting: {exc}", file=sys.stderr)
            return 1
        print("NewApi: calls above min_sdk (each is a crash on older devices):")
        for line in findings(report):
            print(f"  {line}")
        return 1
    print("NewApi: no call above min_sdk.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
