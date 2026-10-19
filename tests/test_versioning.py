"""Resolving the version a build uses (kivyforge.versioning).

pip is faked: these pin kivyforge's side of the contract -- which command it
runs, how it reads the report, how failures are classified. What pip and the
backends actually do is pinned by the opt-in ``tests/test_pip_metadata_live.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kivyforge.config.errors import ConfigError
from kivyforge.config.model import (
    DeclaredVersion,
    DynamicVersion,
    ResolvedVersion,
    StaticVersion,
)
from kivyforge.report import diagnostics, exit_codes
from kivyforge.versioning import (
    AppleVersionRejected,
    VersionUnresolved,
    announcement,
    apple_conforms,
    check_apple_version,
    check_version_file,
    pip_command,
    resolve_version,
)

DYNAMIC = DynamicVersion("setuptools.build_meta")
ROOT = Path("/project")


class FakePip:
    def __init__(
        self, *, version="1.2.4.dev1+gabc", returncode=0, stdout=None, stderr=""
    ):
        self.calls: list[tuple[list[str], dict]] = []
        report = {"install": [{"metadata": {"name": "demo", "version": version}}]}
        self.stdout = json.dumps(report) if stdout is None else stdout
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd, self.returncode, self.stdout, self.stderr
        )


def resolve(
    declared: DeclaredVersion = DYNAMIC,
    *,
    flag=None,
    env=None,
    isolated=True,
    runner=None,
):
    return resolve_version(
        declared,
        ROOT,
        flag=flag,
        env=env or {},
        isolated=isolated,
        runner=runner or FakePip(),
    )


class TestPrecedence:
    def test_flag_beats_environment(self):
        version = resolve(flag="2.0", env={"KIVYFORGE_APP_VERSION": "3.0"})
        assert version == ResolvedVersion("2.0", source="override")

    def test_environment_alone(self):
        version = resolve(env={"KIVYFORGE_APP_VERSION": " 3.0 "})
        assert version == ResolvedVersion("3.0", source="override")

    def test_override_skips_the_backend(self):
        pip = FakePip()
        resolve(flag="2.0", runner=pip)
        assert pip.calls == []

    def test_override_is_normalized(self):
        assert resolve(flag="v1.2.3").value == "1.2.3"

    @pytest.mark.parametrize(
        ("flag", "env", "named"),
        [
            ("1.0.0-SNAPSHOT", {}, "--app-version"),
            (None, {"KIVYFORGE_APP_VERSION": "latest"}, "KIVYFORGE_APP_VERSION"),
        ],
    )
    def test_invalid_override_names_its_origin(self, flag, env, named):
        with pytest.raises(ConfigError, match=named) as exc:
            resolve(flag=flag, env=env)
        assert exc.value.line is None

    def test_static_is_used_without_pip(self):
        pip = FakePip()
        version = resolve(StaticVersion("1.0"), runner=pip)
        assert version == ResolvedVersion("1.0", source="static")
        assert pip.calls == []

    def test_dynamic_comes_from_pip(self):
        assert resolve() == ResolvedVersion("1.2.4.dev1+gabc", source="backend")


class TestPipInvocation:
    def test_isolated_by_default(self):
        cmd = pip_command(ROOT, isolated=True)
        assert cmd[:3] == [sys.executable, "-m", "pip"]
        assert "--no-build-isolation" not in cmd
        for flag in ("--dry-run", "--ignore-installed", "--no-deps", "--report"):
            assert flag in cmd
        assert cmd[-1] == str(ROOT)

    def test_no_build_isolation_on_request(self):
        assert "--no-build-isolation" in pip_command(ROOT, isolated=False)

    def test_ignores_requires_python(self):
        # An Android app declaring >=3.14 must resolve from a 3.13 host (#118).
        for isolated in (True, False):
            assert "--ignore-requires-python" in pip_command(ROOT, isolated=isolated)

    def test_never_waits_for_input_and_captures_both_streams(self):
        pip = FakePip()
        resolve(runner=pip)
        _cmd, kwargs = pip.calls[0]
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["capture_output"] is True

    def test_decodes_pip_as_utf8_not_the_locale(self):
        # pip writes UTF-8 to a pipe on a cp1252 Windows host too; the locale
        # default garbled the backend error #118 quoted ("café" came out "cafÃ©").
        pip = FakePip()
        resolve(runner=pip)
        _cmd, kwargs = pip.calls[0]
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"

    def test_inherits_the_environment(self):
        # PIP_INDEX_URL and SETUPTOOLS_SCM_PRETEND_VERSION depend on it.
        pip = FakePip()
        resolve(runner=pip)
        assert "env" not in pip.calls[0][1]

    def test_backend_version_is_normalized(self):
        assert resolve(runner=FakePip(version="1.0-beta")).value == "1.0b0"


class TestFailures:
    def test_pip_exit_is_unresolved_exit_1_with_the_tail(self):
        stderr = "\n".join(f"line {i}" for i in range(40))
        with pytest.raises(VersionUnresolved) as exc:
            resolve(runner=FakePip(returncode=1, stderr=stderr))
        assert exc.value.code == diagnostics.VERSION_UNRESOLVED
        assert exc.value.exit_code == exit_codes.CONFIG_ERROR
        assert "line 39" in str(exc.value) and "line 10" not in str(exc.value)
        assert "Fix:" in str(exc.value)
        assert exc.value.context == {
            "backend": "setuptools.build_meta",
            "isolated": "true",
        }

    def test_missing_pip_is_an_environment_error(self):
        def missing(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        with pytest.raises(VersionUnresolved) as exc:
            resolve(runner=missing)
        assert exc.value.code == diagnostics.TOOLCHAIN_MISSING
        assert exc.value.exit_code == exit_codes.ENVIRONMENT_ERROR

    @pytest.mark.parametrize(
        "stdout",
        ["not json", "{}", '{"install": []}', '{"install": [{"metadata": {}}]}'],
    )
    def test_a_report_without_a_version_is_unresolved(self, stdout):
        with pytest.raises(VersionUnresolved, match="no version"):
            resolve(runner=FakePip(stdout=stdout))


class TestAnnouncement:
    def test_backend(self):
        line = announcement(
            ResolvedVersion("1.2", source="backend"), DYNAMIC, flag=None
        )
        assert line == "Version 1.2 (from setuptools.build_meta, via pip)"

    def test_override_names_flag_or_variable(self):
        version = ResolvedVersion("2.0", source="override")
        assert (
            announcement(version, DYNAMIC, flag="2.0")
            == "Version 2.0 (from --app-version)"
        )
        assert (
            announcement(version, DYNAMIC, flag=None)
            == "Version 2.0 (from KIVYFORGE_APP_VERSION)"
        )

    def test_static_says_nothing(self):
        # Keeps every existing project's output unchanged.
        version = ResolvedVersion("1.0", source="static")
        assert announcement(version, StaticVersion("1.0"), flag=None) is None


class TestApple:
    @pytest.mark.parametrize("value", ["1", "1.0", "1.2.3"])
    def test_one_to_three_integers_conform(self, value):
        assert apple_conforms(value)

    @pytest.mark.parametrize("value", ["1.0rc1", "1.2.4.dev3+gabc", "1.2.3.4", "1!2.0"])
    def test_anything_else_does_not(self, value):
        assert not apple_conforms(value)

    def check(self, value, **kwargs):
        return check_apple_version(ResolvedVersion(value, source="backend"), **kwargs)

    def test_debug_builds_say_nothing(self):
        assert (
            self.check(
                "1.0rc1", platform="ios", exports=False, export_method="app-store"
            )
            is None
        )

    def test_app_store_export_fails(self):
        with pytest.raises(AppleVersionRejected, match="ITMS-90060") as exc:
            self.check(
                "1.0rc1", platform="ios", exports=True, export_method="app-store"
            )
        assert exc.value.code == diagnostics.VERSION_APPLE_FORMAT
        assert exc.value.exit_code == exit_codes.CONFIG_ERROR
        assert "Fix:" in str(exc.value)

    @pytest.mark.parametrize(
        ("platform", "method"),
        [("ios", "ad-hoc"), ("ios", "development"), ("macos", None)],
    )
    def test_other_exports_warn(self, platform, method):
        found = self.check(
            "1.0rc1", platform=platform, exports=True, export_method=method
        )
        assert found is not None
        assert (found.code, found.severity) == (
            diagnostics.VERSION_APPLE_FORMAT,
            diagnostics.WARNING,
        )

    def test_conforming_exports_pass(self):
        assert (
            self.check("1.2.3", platform="ios", exports=True, export_method="app-store")
            is None
        )

    def test_other_platforms_are_not_checked(self):
        assert (
            self.check("1.0rc1", platform="android", exports=True, export_method=None)
            is None
        )


class TestVersionFile:
    @pytest.mark.parametrize("source", ["override", "static"])
    def test_warns_when_the_backend_did_not_run(self, source):
        found = check_version_file(
            ResolvedVersion("1.0", source=source), "src/_version.py"
        )
        assert found is not None
        assert found.code == diagnostics.VERSION_FILE_NOT_REFRESHED
        assert found.context == {"path": "src/_version.py"}
        assert "SETUPTOOLS_SCM_PRETEND_VERSION" in found.remediation

    def test_silent_when_the_backend_rewrote_it(self):
        assert (
            check_version_file(ResolvedVersion("1.0", source="backend"), "v.py") is None
        )

    def test_silent_without_a_version_file(self):
        assert (
            check_version_file(ResolvedVersion("1.0", source="override"), None) is None
        )


FIXTURES = Path(__file__).parent / "fixtures" / "pip_stderr"


class TestFailureSummary:
    """Real pip 26.2.1 stderr (tests/fixtures/pip_stderr), paths replaced."""

    @pytest.mark.parametrize(
        ("sample", "expected"),
        [
            (
                "no_backend",  # --no-build-isolation, backend not installed
                [
                    "pip._vendor.pyproject_hooks._impl.BackendUnavailable: "
                    "Cannot import 'setuptools.build_meta'"
                ],
            ),
            (
                "no_git",  # setuptools-scm outside a git checkout
                [
                    "LookupError: setuptools-scm was unable to detect version for /project.",
                    "ERROR: Failed to build 'file:///project' when getting requirements "
                    "to build wheel",
                ],
            ),
            (
                "no_index",  # isolated, package index unreachable
                [
                    "ERROR: Could not find a version that satisfies the requirement "
                    "setuptools>=64 (from versions: none)",
                    "ERROR: No matching distribution found for setuptools>=64",
                    "ERROR: Failed to build 'file:///project' when installing build "
                    "dependencies",
                ],
            ),
        ],
    )
    def test_keeps_what_went_wrong_and_drops_the_traceback(self, sample, expected):
        stderr = (FIXTURES / f"{sample}.txt").read_text(encoding="utf-8")
        assert len(stderr.splitlines()) > len(expected)
        from kivyforge.versioning import pip_failure_summary

        assert pip_failure_summary(stderr) == expected

    def test_falls_back_to_the_tail(self):
        from kivyforge.versioning import pip_failure_summary

        stderr = "\n".join(f"plain {i}" for i in range(30))
        assert pip_failure_summary(stderr) == [f"plain {i}" for i in range(15, 30)]

    def test_non_isolated_failure_says_to_install_the_backend(self):
        with pytest.raises(VersionUnresolved) as exc:
            resolve(isolated=False, runner=FakePip(returncode=2, stderr="x"))
        assert "uv tool install kivyforge --with setuptools-scm" in str(exc.value)
        assert exc.value.context["isolated"] == "false"
