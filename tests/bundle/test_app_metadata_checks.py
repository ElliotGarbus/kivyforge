"""Entry points kivyforge cannot write: the error (2.3) and the warning (2.4).

docs/design/dev/package-metadata-proposal.md. Entry points declared only in
``setup.cfg``/``setup.py`` fail the build (D1): generating from ``[project]``
alone would drop them, which is #122. Entry points in ``[project].dynamic`` are
known only to the backend, so the build warns and generates nothing (D2). Both
are checked by ``build``/``package``/``run`` before any backend runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import kivyforge.cli.build as build_mod
import kivyforge.cli.package as package_mod
import kivyforge.cli.run as run_mod
from kivyforge.build_outcome import BuildOutcome
from kivyforge.bundle import app_metadata
from kivyforge.bundle.app_metadata import EntryPointsOutsideProject
from kivyforge.config.loader import load_declared_project
from kivyforge.report import diagnostics, exit_codes

SETUPTOOLS = '[build-system]\nbuild-backend = "setuptools.build_meta"\n'
LEGACY = '[build-system]\nbuild-backend = "setuptools.build_meta:__legacy__"\n'
HATCHLING = '[build-system]\nbuild-backend = "hatchling.build"\n'
PROJECT = '[project]\nname = "myapp"\nversion = "1.0"\n'
KIVY = '\n[tool.kivy]\napp_dir = "src"\n'
DECLARED = '[project.entry-points."myapp.plugins"]\nmine = "myapp:Mine"\n'

SETUP_CFG = """\
[metadata]
name = myapp

[options.entry_points]
myapp.plugins =
    mine = myapp:Mine
"""
SETUP_PY = """\
from setuptools import setup

setup(entry_points={"myapp.plugins": ["mine = myapp:Mine"]})
"""


def project_at(tmp_path: Path, pyproject: str, **files: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(pyproject + KIVY, encoding="utf-8")
    for name, text in files.items():
        (tmp_path / name.replace("_", ".")).write_text(text, encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    return tmp_path


def check(root: Path) -> None:
    project, _ = load_declared_project(root / "pyproject.toml")
    app_metadata.check_declaration(project, root)


def warning(root: Path):
    project, app_dir = load_declared_project(root / "pyproject.toml")
    return app_metadata.not_generated(project, root, app_dir)


class TestEntryPointsOutsideProject:
    @pytest.mark.parametrize("build_system", ["", SETUPTOOLS, LEGACY])
    def test_setup_cfg(self, tmp_path, build_system):
        root = project_at(tmp_path, build_system + PROJECT, setup_cfg=SETUP_CFG)
        with pytest.raises(EntryPointsOutsideProject) as exc:
            check(root)
        assert exc.value.code == diagnostics.METADATA_ENTRY_POINTS_OUTSIDE_PROJECT
        assert exc.value.exit_code == exit_codes.CONFIG_ERROR
        assert exc.value.context == {"path": "setup.cfg"}
        assert "setup.cfg" in str(exc.value)
        assert "Fix: move them from setup.cfg into [project.entry-points]" in str(
            exc.value
        )

    def test_setup_py(self, tmp_path):
        root = project_at(tmp_path, PROJECT, setup_py=SETUP_PY)
        with pytest.raises(EntryPointsOutsideProject) as exc:
            check(root)
        assert exc.value.context == {"path": "setup.py"}

    def test_an_empty_table_is_no_opt_out(self, tmp_path):
        """F7: setuptools 84 still used setup.py's with it."""
        pyproject = PROJECT + "[project.entry-points]\n"
        root = project_at(tmp_path, pyproject, setup_py=SETUP_PY)
        with pytest.raises(EntryPointsOutsideProject):
            check(root)

    def test_entry_points_in_project_win(self, tmp_path):
        """S2: setuptools then uses only [project]'s, as kivyforge does."""
        root = project_at(
            tmp_path, PROJECT + DECLARED, setup_cfg=SETUP_CFG, setup_py=SETUP_PY
        )
        check(root)

    def test_another_backend_never_reads_setup_py(self, tmp_path):
        root = project_at(tmp_path, HATCHLING + PROJECT, setup_py=SETUP_PY)
        check(root)

    def test_a_setup_py_without_entry_points(self, tmp_path):
        """A setup.py kept for a build step gets generated metadata."""
        setup_py = "from setuptools import setup\n\nsetup()\n"
        root = project_at(tmp_path, PROJECT, setup_py=setup_py)
        check(root)
        project, _ = load_declared_project(root / "pyproject.toml")
        assert project.entry_points == ()

    def test_an_empty_setup_cfg_section(self, tmp_path):
        setup_cfg = "[options.entry_points]\n"
        check(project_at(tmp_path, PROJECT, setup_cfg=setup_cfg))

    def test_a_setup_cfg_configparser_cannot_read(self, tmp_path):
        setup_cfg = "[options.entry_points]\nx = 1\nx = 2\n"  # duplicate option
        check(project_at(tmp_path, PROJECT, setup_cfg=setup_cfg))

    def test_dynamic_entry_points_are_the_warning_instead(self, tmp_path):
        pyproject = PROJECT + 'dynamic = ["entry-points"]\n'
        root = project_at(tmp_path, pyproject, setup_cfg=SETUP_CFG)
        check(root)
        assert warning(root) is not None


class TestNotGenerated:
    def test_nothing_dynamic_nothing_said(self, tmp_path):
        assert warning(project_at(tmp_path, PROJECT + DECLARED)) is None

    @pytest.mark.parametrize("key", ["entry-points", "scripts", "gui-scripts"])
    def test_dynamic_only(self, tmp_path, key):
        root = project_at(tmp_path, PROJECT + f'dynamic = ["{key}"]\n')
        found = warning(root)
        assert found is not None
        assert found.code == diagnostics.METADATA_NOT_GENERATED
        assert found.severity == diagnostics.WARNING
        assert found.context == {"reason": "dynamic", "fallback": "none"}
        assert "no package metadata" in found.message

    def test_static_and_dynamic(self, tmp_path):
        pyproject = PROJECT + 'dynamic = ["entry-points"]\n' + DECLARED
        found = warning(project_at(tmp_path, pyproject))
        assert found is not None
        assert found.context["reason"] == "static-and-dynamic"

    def test_names_the_egg_info_that_ships_instead(self, tmp_path):
        root = project_at(tmp_path, PROJECT + 'dynamic = ["entry-points"]\n')
        (root / "src" / "other.egg-info").mkdir()
        (root / "src" / "myapp.egg-info").mkdir()
        found = warning(root)
        assert found is not None
        assert found.context == {
            "reason": "dynamic",
            "fallback": "src/myapp.egg-info",
        }
        assert "src/myapp.egg-info" in found.message


# --------------------------------------------------------------------------- #
# Through the verbs
# --------------------------------------------------------------------------- #


class FakeBackend:
    name = "macos"
    package_formats = ("folder",)
    default_package_format = "folder"

    def __init__(self) -> None:
        self.calls = 0

    def build(self, project_root, **kwargs):
        self.calls += 1
        return BuildOutcome(())

    package = build

    def run(self, project_root, **kwargs):
        self.calls += 1


@pytest.fixture
def verb(tmp_path, monkeypatch):
    monkeypatch.delenv("KIVYFORGE_APP_VERSION", raising=False)
    backend = FakeBackend()
    for module in (build_mod, package_mod, run_mod):

        def resolve_target(cli_platform, verb, report=None):
            if report is not None:
                report.platform = backend.name
            return backend, tmp_path

        monkeypatch.setattr(module, "resolve_target", resolve_target)
    return backend


@pytest.mark.parametrize("command", [build_mod.build, package_mod.package])
def test_the_error_stops_the_verb(tmp_path, verb, command):
    project_at(tmp_path, PROJECT, setup_cfg=SETUP_CFG)

    result = CliRunner().invoke(command, ["--json"])

    assert result.exit_code == exit_codes.CONFIG_ERROR
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    (found,) = envelope["diagnostics"]
    assert found["code"] == "KF-METADATA-ENTRY-POINTS-OUTSIDE-PROJECT"
    assert found["context"] == {"path": "setup.cfg"}
    assert found["remediation"].startswith("move them from setup.cfg")
    assert verb.calls == 0


def test_run_checks_too(tmp_path, verb):
    project_at(tmp_path, PROJECT, setup_py=SETUP_PY)

    result = CliRunner().invoke(run_mod.run, ["-p", "macos"])

    assert result.exit_code == exit_codes.CONFIG_ERROR
    assert "setup.py declares entry points" in result.stderr
    assert verb.calls == 0


def test_the_warning_is_reported_and_the_build_goes_on(tmp_path, verb):
    project_at(tmp_path, PROJECT + 'dynamic = ["scripts"]\n')

    result = CliRunner().invoke(build_mod.build, ["--json"])

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    (found,) = envelope["diagnostics"]
    assert found["code"] == "KF-METADATA-NOT-GENERATED"
    assert found["severity"] == "warning"
    assert found["context"] == {"reason": "dynamic", "fallback": "none"}
    assert "warning: [project].dynamic lists scripts" in result.stderr
    assert verb.calls == 1
