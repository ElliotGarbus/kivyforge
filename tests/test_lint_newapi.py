"""scripts/lint_newapi.py: narrowing a generated project's lint to NewApi.

Hermetic: the build.gradle is the one kivyforge generates, rendered into
tmp_path; Gradle and Lint run only in CI (the android_gradle job).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config_from_text
from kivyforge.platforms.android import policy
from kivyforge.platforms.android.generate.project import write_app_build_gradle

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "lint_newapi", REPO / "scripts" / "lint_newapi.py"
)
assert _spec and _spec.loader
ln = importlib.util.module_from_spec(_spec)
sys.modules["lint_newapi"] = ln
_spec.loader.exec_module(ln)

PYPROJECT = """
[project]
name = "lintapp"
version = "1.0.0"
dependencies = ["pyjnius"]

[tool.kivy]
app_dir = "src"

[tool.kivy.android]
schema_version = 1
package = "org.example.lintapp"

[tool.kivy.android.python]
version = "3.14.6"
"""


@pytest.fixture
def generated_gradle(tmp_path) -> str:
    config = load_config_from_text(PYPROJECT, require_ios=False, require_android=True)
    write_app_build_gradle(
        tmp_path,
        config,
        config.android_required,
        python_version="3.14.6",
        runtime_root=tmp_path / "python-runtime",
        staged_libs=[],
    )
    return (tmp_path / "app" / "build.gradle").read_text(encoding="utf-8")


class TestNarrowBuildGradle:
    def test_lint_runs_newapi_alone(self, generated_gradle):
        narrowed = ln.newapi_build_gradle(generated_gradle)
        assert "checkOnly.addAll(['NewApi'])" in narrowed
        assert "fatal.addAll(['NewApi'])" in narrowed
        for check in policy.LINT_CHECKS:
            assert f"'{check}'" not in narrowed

    def test_test_sources_and_config_are_added(self, generated_gradle):
        """androidTest code runs on the same old devices as the app."""
        narrowed = ln.newapi_build_gradle(generated_gradle)
        assert "checkTestSources = true" in narrowed
        assert f"lintConfig = file('{ln.LINT_CONFIG_NAME}')" in narrowed

    def test_the_rest_of_the_file_is_untouched(self, generated_gradle):
        narrowed = ln.newapi_build_gradle(generated_gradle)
        assert narrowed.count("\n") == generated_gradle.count("\n") + 2
        assert "minSdk 24" in narrowed

    def test_a_changed_lint_block_is_refused(self, generated_gradle):
        """A silent no-op would leave the release checks running and NewApi
        unchecked, while the step still passed."""
        broken = generated_gradle.replace("checkOnly.addAll(", "checkOnly.add(")
        with pytest.raises(ln.LintSetupError, match="checkOnly"):
            ln.newapi_build_gradle(broken)


class TestLintConfig:
    def test_only_sdl_glue_is_ignored(self):
        assert ln.LINT_CONFIG.count("<ignore ") == 1
        assert 'path="src/main/java/org/libsdl/**"' in ln.LINT_CONFIG


class TestFindings:
    def test_report_issues_are_listed(self, tmp_path):
        report = tmp_path / "lint-results-debug.xml"
        report.write_text(
            '<issues format="6">'
            '<issue id="NewApi" message="Call requires API level 26: `java.io.File#toPath`">'
            '<location file="app/src/main/java/org/kivy/android/PythonBundle.java" line="52"/>'
            "</issue></issues>",
            encoding="utf-8",
        )
        assert ln.findings(report) == [
            "app/src/main/java/org/kivy/android/PythonBundle.java:52: "
            "Call requires API level 26: `java.io.File#toPath`"
        ]
