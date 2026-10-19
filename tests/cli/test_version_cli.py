"""``build``/``package``/``run`` resolve the version before dispatching.

A fake backend records what it was handed; pip is faked through
``kivyforge.versioning._run``. docs/design/dev/dynamic-version-proposal.md
sections 3.2-3.8.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from click.testing import CliRunner

import kivyforge.cli.build as build_mod
import kivyforge.cli.package as package_mod
import kivyforge.cli.run as run_mod
from kivyforge import versioning
from kivyforge.build_outcome import BuildOutcome
from kivyforge.cli.lock import lock as lock_cmd
from kivyforge.config.model import ResolvedVersion

DYNAMIC = '[project]\nname = "demo"\ndynamic = ["version"]\n'
STATIC = '[project]\nname = "demo"\nversion = "1.0.0"\n'
SCM = '\n[tool.setuptools_scm]\nversion_file = "src/_version.py"\n'


class FakeBackend:
    package_formats = ("folder",)
    default_package_format = "folder"

    def __init__(self, name: str, fail: Exception | None = None):
        self.name = name
        self.fail = fail
        self.calls: list[dict] = []

    def _call(self, kwargs):
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail
        return BuildOutcome(())

    def build(self, project_root, **kwargs):
        return self._call(kwargs)

    def package(self, project_root, **kwargs):
        return self._call(kwargs)

    def run(self, project_root, **kwargs):
        self.calls.append(kwargs)


class Pip:
    def __init__(self, version="1.2.4.dev1+gabc", returncode=0):
        self.version = version
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        report = {"install": [{"metadata": {"version": self.version}}]}
        return subprocess.CompletedProcess(
            cmd, self.returncode, json.dumps(report), "ERROR: pip said no"
        )


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv("KIVYFORGE_APP_VERSION", raising=False)

    def make(pyproject: str, platform: str = "macos", fail: Exception | None = None):
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        backend = FakeBackend(platform, fail)
        pip = Pip()

        def resolve_target(cli_platform, verb, report=None):
            if report is not None:
                report.platform = backend.name
            return backend, tmp_path

        for module in (build_mod, package_mod, run_mod):
            monkeypatch.setattr(module, "resolve_target", resolve_target)
        monkeypatch.setattr(versioning, "_run", pip)
        return backend, pip

    return make


def invoke(command, args):
    return CliRunner().invoke(command, args)


def envelope(result):
    return json.loads(result.stdout)  # exactly one document


class TestBuildAndPackage:
    @pytest.mark.parametrize("command", [build_mod.build, package_mod.package])
    def test_dynamic_version_reaches_backend_and_envelope(self, project, command):
        backend, pip = project(DYNAMIC)
        result = invoke(command, ["--json"])
        assert result.exit_code == 0, result.output
        expected = ResolvedVersion("1.2.4.dev1+gabc", source="backend")
        assert backend.calls[0]["version"] == expected
        assert envelope(result)["data"]["version"] == {
            "value": "1.2.4.dev1+gabc",
            "source": "backend",
        }
        assert "--no-build-isolation" not in pip.calls[0]
        assert (
            "Version 1.2.4.dev1+gabc (from setuptools.build_meta:__legacy__, via pip)"
            in result.stderr
        )

    def test_static_version_runs_no_pip_and_prints_nothing_new(self, project):
        backend, pip = project(STATIC)
        result = invoke(build_mod.build, [])
        assert result.exit_code == 0, result.output
        assert pip.calls == []
        assert backend.calls[0]["version"] == ResolvedVersion("1.0.0", source="static")
        assert "Version" not in result.stderr

    def test_flag_beats_environment(self, project, monkeypatch):
        backend, pip = project(DYNAMIC)
        monkeypatch.setenv("KIVYFORGE_APP_VERSION", "3.0")
        result = invoke(build_mod.build, ["--app-version", "v2.0", "--json"])
        assert result.exit_code == 0, result.output
        assert backend.calls[0]["version"] == ResolvedVersion("2.0", source="override")
        assert pip.calls == []
        assert "Version 2.0 (from --app-version)" in result.stderr

    def test_environment_override(self, project, monkeypatch):
        backend, _pip = project(DYNAMIC)
        monkeypatch.setenv("KIVYFORGE_APP_VERSION", "3.0")
        result = invoke(build_mod.build, [])
        assert result.exit_code == 0, result.output
        assert backend.calls[0]["version"].value == "3.0"
        assert "from KIVYFORGE_APP_VERSION" in result.stderr

    def test_invalid_override_names_the_flag(self, project):
        project(STATIC)
        result = invoke(build_mod.build, ["--app-version", "1.0.0-SNAPSHOT"])
        assert result.exit_code == 1
        assert "--app-version '1.0.0-SNAPSHOT' is not a valid version" in result.output

    def test_no_build_isolation_passes_through(self, project):
        _backend, pip = project(DYNAMIC)
        result = invoke(build_mod.build, ["--no-build-isolation"])
        assert result.exit_code == 0, result.output
        assert "--no-build-isolation" in pip.calls[0]

    def test_no_build_isolation_with_override_is_refused(self, project):
        backend, _pip = project(DYNAMIC)
        result = invoke(
            build_mod.build, ["--app-version", "2.0", "--no-build-isolation"]
        )
        assert result.exit_code == 1
        assert "has no effect with --app-version" in result.output
        assert backend.calls == []

    def test_no_build_isolation_with_a_static_version_is_an_info_note(self, project):
        _backend, pip = project(STATIC)
        result = invoke(build_mod.build, ["--no-build-isolation", "--json"])
        assert result.exit_code == 0, result.output
        assert pip.calls == []
        codes = {d["code"]: d["severity"] for d in envelope(result)["diagnostics"]}
        assert codes == {"KF-VERSION-ISOLATION-UNUSED": "info"}

    def test_unresolved_is_exit_1_with_no_version_in_the_envelope(self, project):
        backend, pip = project(DYNAMIC)
        pip.returncode = 1
        result = invoke(build_mod.build, ["--json"])
        assert result.exit_code == 1
        doc = envelope(result)
        assert doc["ok"] is False
        assert "version" not in doc["data"]
        assert [d["code"] for d in doc["diagnostics"]] == ["KF-VERSION-UNRESOLVED"]
        assert backend.calls == []

    def test_a_build_failing_after_resolution_keeps_the_version(self, project):
        from kivyforge.cli._common import ToolchainError

        project(DYNAMIC, fail=ToolchainError("gradle broke", exit_code=5))
        result = invoke(build_mod.build, ["--json"])
        assert result.exit_code == 5
        assert envelope(result)["data"]["version"]["value"] == "1.2.4.dev1+gabc"

    def test_version_file_not_refreshed_warns(self, project):
        project(DYNAMIC + SCM)
        result = invoke(build_mod.build, ["--app-version", "2.0", "--json"])
        assert result.exit_code == 0, result.output
        codes = [d["code"] for d in envelope(result)["diagnostics"]]
        assert codes == ["KF-VERSION-FILE-NOT-REFRESHED"]
        assert "src/_version.py was not rewritten" in result.stderr


class TestApple:
    def test_app_store_export_of_a_dev_version_fails_before_the_backend(self, project):
        backend, _pip = project(DYNAMIC, platform="ios")
        result = invoke(package_mod.package, ["--json"])  # app-store is the default
        assert result.exit_code == 1
        doc = envelope(result)
        assert [d["code"] for d in doc["diagnostics"]] == ["KF-VERSION-APPLE-FORMAT"]
        assert "ITMS-90060" in doc["diagnostics"][0]["message"]
        assert doc["diagnostics"][0]["remediation"]
        assert backend.calls == []

    def test_build_release_is_an_export_too(self, project):
        backend, _pip = project(DYNAMIC, platform="ios")
        result = invoke(build_mod.build, ["--release"])
        assert result.exit_code == 1
        assert backend.calls == []

    def test_ad_hoc_export_warns(self, project):
        backend, _pip = project(DYNAMIC, platform="ios")
        result = invoke(package_mod.package, ["--export-method", "ad-hoc", "--json"])
        assert result.exit_code == 0, result.output
        diags = envelope(result)["diagnostics"]
        assert [(d["code"], d["severity"]) for d in diags] == [
            ("KF-VERSION-APPLE-FORMAT", "warning")
        ]
        assert backend.calls

    def test_simulator_build_is_silent(self, project):
        _backend, _pip = project(DYNAMIC, platform="ios")
        result = invoke(build_mod.build, ["--simulator", "--json"])
        assert result.exit_code == 0, result.output
        assert envelope(result)["diagnostics"] == []

    def test_macos_package_warns_and_build_does_not(self, project):
        project(DYNAMIC, platform="macos")
        packaged = invoke(package_mod.package, ["--json"])
        built = invoke(build_mod.build, ["--json"])
        assert [d["code"] for d in envelope(packaged)["diagnostics"]] == [
            "KF-VERSION-APPLE-FORMAT"
        ]
        assert envelope(built)["diagnostics"] == []

    def test_conforming_version_exports_cleanly(self, project):
        project(STATIC, platform="ios")
        result = invoke(package_mod.package, ["--json"])
        assert result.exit_code == 0, result.output
        assert envelope(result)["diagnostics"] == []


class TestRun:
    def test_run_resolves_and_passes_the_version(self, project):
        backend, pip = project(DYNAMIC)
        result = invoke(run_mod.run, ["-p", "macos"])
        assert result.exit_code == 0, result.output
        assert backend.calls[0]["version"].value == "1.2.4.dev1+gabc"
        assert "Version 1.2.4.dev1+gabc" in result.stderr
        assert result.stdout == ""  # the app's output is run's product

    def test_no_build_carries_no_version_and_runs_no_pip(self, project):
        backend, pip = project(DYNAMIC)
        result = invoke(run_mod.run, ["--no-build"])
        assert result.exit_code == 0, result.output
        assert backend.calls[0]["version"] is None
        assert pip.calls == []

    @pytest.mark.parametrize(
        ("args", "why"),
        [
            (["--no-build", "--app-version", "2.0"], "--no-build"),
            (["--no-build", "--no-build-isolation"], "--no-build"),
            (["--list-devices", "--app-version", "2.0"], "--list-devices"),
        ],
    )
    def test_flags_that_cannot_apply_are_refused(self, project, args, why):
        backend, _pip = project(DYNAMIC)
        result = invoke(run_mod.run, args)
        assert result.exit_code == 1
        assert f"has no effect with {why}" in result.output
        assert backend.calls == []

    def test_environment_override_is_ignored_where_nothing_builds(
        self, project, monkeypatch
    ):
        backend, _pip = project(DYNAMIC)
        monkeypatch.setenv("KIVYFORGE_APP_VERSION", "2.0")
        result = invoke(run_mod.run, ["--no-build"])
        assert result.exit_code == 0, result.output
        assert backend.calls[0]["version"] is None

    def test_apple_warnings_are_not_raised_by_run(self, project):
        # run is a development build: nothing uploads it.
        project(DYNAMIC, platform="macos")
        result = invoke(run_mod.run, [])
        assert result.exit_code == 0, result.output
        assert "ITMS" not in result.stderr


def test_lock_has_no_app_version():
    result = CliRunner().invoke(lock_cmd, ["--app-version", "1.0"])
    assert result.exit_code == 2
    assert "No such option" in result.output
