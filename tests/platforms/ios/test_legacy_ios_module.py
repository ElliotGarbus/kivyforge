"""``KF-IOS-LEGACY-IOS-MODULE``: a warning for apps that import kivy-ios's ``ios`` (#109).

kivyforge does not provide the module (``ios-module-proposal.md``): Kivy 3 and
the standard library replace every function in it, and the migration guide
maps them. An app that still imports it would fail on the device with a bare
``ModuleNotFoundError``, so ``build -p ios`` and ``doctor -p ios`` say so first.
A warning, never an error: the import may be guarded. No network, no
toolchain: ``build`` runs with staging and collection stubbed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.cli.build import build
from kivyforge.cli.doctor import doctor
from kivyforge.config import load_config_from_text
from kivyforge.doctor.result import Status
from kivyforge.platforms.ios import cli as ios_cli
from kivyforge.platforms.ios import doctor as ios_doctor
from kivyforge.platforms.ios.legacy_module import GUIDE, find_legacy_ios_imports
from kivyforge.report import diagnostics, exit_codes
from tests.platforms.ios.test_kivy_unsupported import _write_project

CODE = "KF-IOS-LEGACY-IOS-MODULE"
SENTENCE = "imports the kivy-ios `ios` module, which kivyforge does not provide"

_CONFIG = """
[project]
name = "myapp"
version = "1.0.0"

[tool.kivy]
app_dir = "src"

[tool.kivy.ios]
schema_version = 1
bundle_id = "org.example.myapp"
deployment_target = "16.0"

[tool.kivy.ios.python]
version = "3.15.0"
""".strip()


def _source(root: Path, name: str, text: str) -> Path:
    path = root / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestScan:
    def test_the_guide_exists(self):
        """The warning names a path; a rename must not leave it dangling."""
        assert (Path(__file__).parents[3] / GUIDE).is_file()

    def test_plain_import(self, tmp_path):
        _source(tmp_path, "main.py", "import os\nimport ios\n")
        found = find_legacy_ios_imports(tmp_path / "src", tmp_path)
        assert found is not None
        assert found.hits == (("src/main.py", 2),)
        assert found.message == f"src/main.py:2 {SENTENCE}"
        assert GUIDE in found.hint

    @pytest.mark.parametrize(
        "line",
        [
            "import ios",
            "from ios import get_safe_area",
            "from ios.x import y",
            "import ios, sys",
            "import ios  # kivy-ios",
            "    import ios",
        ],
    )
    def test_import_forms(self, tmp_path, line):
        _source(tmp_path, "main.py", f"x = 1\n{line}\n")
        found = find_legacy_ios_imports(tmp_path / "src", tmp_path)
        assert found is not None
        assert found.hits == (("src/main.py", 2),)

    def test_indented_guarded_import_still_warns(self, tmp_path):
        """``if platform == "ios": import ios`` is how kivy-ios apps write it."""
        _source(
            tmp_path,
            "main.py",
            "from kivy.utils import platform\n"
            "if platform == 'ios':\n"
            "    import ios\n"
            "    ios.get_safe_area()\n",
        )
        found = find_legacy_ios_imports(tmp_path / "src", tmp_path)
        assert found is not None
        assert found.hits == (("src/main.py", 3),)

    def test_try_except_guard_still_warns(self, tmp_path):
        _source(
            tmp_path,
            "main.py",
            "try:\n    import ios\nexcept ImportError:\n    ios = None\n",
        )
        assert find_legacy_ios_imports(tmp_path / "src", tmp_path) is not None

    @pytest.mark.parametrize(
        "line",
        [
            "import iostream",
            "import ios_utils",
            "from iosevka import x",
            "from kivy.ios import x",
            "import kivy.ios",
            "x = 'import ios'",
            "ios = 1",
            "print(ios.get_scale())",
        ],
    )
    def test_other_names_are_quiet(self, tmp_path, line):
        _source(tmp_path, "main.py", f"{line}\n")
        assert find_legacy_ios_imports(tmp_path / "src", tmp_path) is None

    def test_apps_own_ios_module_is_quiet(self, tmp_path):
        _source(tmp_path, "main.py", "import ios\n")
        _source(tmp_path, "ios.py", "def get_scale():\n    return 1.0\n")
        assert find_legacy_ios_imports(tmp_path / "src", tmp_path) is None

    def test_apps_own_ios_package_is_quiet(self, tmp_path):
        _source(tmp_path, "main.py", "from ios import helper\n")
        _source(tmp_path, "ios/__init__.py", "")
        assert find_legacy_ios_imports(tmp_path / "src", tmp_path) is None

    def test_nested_ios_py_is_not_the_apps_top_level_module(self, tmp_path):
        """Only a sibling of the app's modules shadows kivy-ios's; ``pkg/ios.py``
        is ``pkg.ios``."""
        _source(tmp_path, "main.py", "import ios\n")
        _source(tmp_path, "pkg/ios.py", "")
        assert find_legacy_ios_imports(tmp_path / "src", tmp_path) is not None

    def test_scans_subdirectories_one_hit_per_file_sorted(self, tmp_path):
        _source(tmp_path, "b/view.py", "x = 1\nimport ios\nimport ios\n")
        _source(tmp_path, "a.py", "import ios\n")
        _source(tmp_path, "c.py", "import os\n")
        found = find_legacy_ios_imports(tmp_path / "src", tmp_path)
        assert found is not None
        assert found.hits == (("src/a.py", 1), ("src/b/view.py", 2))
        assert found.message.startswith("src/a.py:1, src/b/view.py:2 import ")
        assert found.context == {"file": "src/a.py", "line": "1", "files": "2"}

    def test_many_files_are_summarised(self, tmp_path):
        for n in range(5):
            _source(tmp_path, f"m{n}.py", "import ios\n")
        found = find_legacy_ios_imports(tmp_path / "src", tmp_path)
        assert found is not None
        assert found.message.startswith(
            "src/m0.py:1, src/m1.py:1, src/m2.py:1 and 2 more import "
        )

    def test_only_python_files(self, tmp_path):
        _source(tmp_path, "notes.txt", "import ios\n")
        _source(tmp_path, "main.kv", "import ios\n")
        assert find_legacy_ios_imports(tmp_path / "src", tmp_path) is None

    def test_missing_app_dir(self, tmp_path):
        assert find_legacy_ios_imports(tmp_path / "src", tmp_path) is None

    def test_undecodable_file_does_not_crash(self, tmp_path):
        path = _source(tmp_path, "main.py", "")
        path.write_bytes(b"\xff\xfe import ios\n\nimport ios\n")
        found = find_legacy_ios_imports(tmp_path / "src", tmp_path)
        assert found is not None
        assert found.hits == (("src/main.py", 3),)


class TestDoctorCheck:
    @pytest.fixture
    def config(self):
        return load_config_from_text(_CONFIG)

    def test_warns_with_code_detail_and_guide(self, config, tmp_path):
        _source(tmp_path, "main.py", "import ios\n")
        result = ios_doctor.check_legacy_ios_module(config, tmp_path)
        assert result.status is Status.WARN
        assert result.code == CODE == diagnostics.IOS_LEGACY_IOS_MODULE
        assert result.detail == f"src/main.py:1 {SENTENCE}"
        assert GUIDE in result.hint

    def test_passes_when_not_imported(self, config, tmp_path):
        _source(tmp_path, "main.py", "import os\n")
        assert (
            ios_doctor.check_legacy_ios_module(config, tmp_path).status is Status.PASS
        )

    def test_quiet_for_the_apps_own_module(self, config, tmp_path):
        _source(tmp_path, "main.py", "import ios\n")
        _source(tmp_path, "ios.py", "")
        assert (
            ios_doctor.check_legacy_ios_module(config, tmp_path).status is Status.PASS
        )

    def test_skips_without_an_app_dir(self, config, tmp_path):
        assert (
            ios_doctor.check_legacy_ios_module(config, tmp_path).status is Status.SKIP
        )

    def test_is_in_the_check_set(self, config, tmp_path):
        from tests.doctor.probe_fakes import FakeProbe

        _source(tmp_path, "main.py", "import ios\n")
        results = ios_doctor.run_ios_checks(
            FakeProbe(),
            kivyforge_version="3.0.0",
            config=config,
            project_root=tmp_path,
            offline=True,
        )
        by_name = {r.name: r for r in results}
        assert by_name["kivy-ios ios module"].status is Status.WARN

    def test_environment_mode_skips_it(self):
        from tests.doctor.probe_fakes import FakeProbe

        results = ios_doctor.run_ios_checks(
            FakeProbe(), kivyforge_version="3.0.0", offline=True
        )
        by_name = {r.name: r for r in results}
        assert by_name["kivy-ios ios module"].status is Status.SKIP


@pytest.fixture
def runner():
    return CliRunner()


class TestDoctorCli:
    @pytest.fixture
    def project(self, runner, tmp_path, monkeypatch):
        from tests.doctor.probe_fakes import FakeProbe

        monkeypatch.setattr(ios_doctor, "RealProbe", FakeProbe)
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            root = Path(fs)
            (root / "pyproject.toml").write_text(_CONFIG, encoding="utf-8")
            yield root

    def test_human(self, runner, project):
        _source(project, "main.py", "import ios\n")
        result = runner.invoke(doctor, ["-p", "ios", "--offline"])
        assert f"[WARN] kivy-ios ios module: src/main.py:1 {SENTENCE}" in result.stdout
        assert f"hint: Kivy 3 and the standard library replace it; see {GUIDE}" in (
            result.stdout
        )

    def test_json(self, runner, project):
        _source(project, "main.py", "from ios import get_safe_area\n")
        result = runner.invoke(doctor, ["-p", "ios", "--offline", "--json"])
        envelope = json.loads(result.stdout)  # one document, nothing else
        assert envelope["command"] == "doctor"
        assert envelope["platform"] == "ios"
        [check] = [
            c for c in envelope["data"]["checks"] if c["name"] == "kivy-ios ios module"
        ]
        assert check["status"] == "WARN"
        assert check["code"] == CODE
        [diagnostic] = [d for d in envelope["diagnostics"] if d["code"] == CODE]
        assert diagnostic["severity"] == "warning"
        assert diagnostic["message"] == f"kivy-ios ios module: src/main.py:1 {SENTENCE}"
        assert GUIDE in diagnostic["remediation"]
        assert diagnostic["context"] == {"check": "kivy-ios ios module"}

    def test_json_is_quiet_without_the_import(self, runner, project):
        _source(project, "main.py", "import os\n")
        result = runner.invoke(doctor, ["-p", "ios", "--offline", "--json"])
        envelope = json.loads(result.stdout)
        assert CODE not in [d["code"] for d in envelope["diagnostics"]]


@pytest.fixture
def staged(monkeypatch):
    """``build`` with the toolchain stubbed out; it stops after generating."""
    monkeypatch.setattr(ios_cli, "create_staging", lambda *a, **k: None)
    monkeypatch.setattr(ios_cli, "collect_artifacts", lambda *a, **k: None)
    monkeypatch.setattr(ios_cli, "materialize_project", lambda *a, **k: None)
    monkeypatch.setattr(ios_cli, "_xcode_last_upgrade_check", lambda: None)
    monkeypatch.setattr(ios_cli, "default_simulator_arch", lambda: "arm64")


class TestBuildCli:
    def test_human_warns_on_stderr_and_builds(self, runner, tmp_path, staged):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, kivy_version="3.0.0")
            _source(Path(fs), "main.py", "import os\nimport ios\n")
            result = runner.invoke(build, ["-p", "ios"])
            assert result.exit_code == 0, result.output
            assert f"[build] warning: src/main.py:2 {SENTENCE}." in result.stderr
            assert GUIDE in result.stderr
            assert "Generated myapp-ios" in result.stdout
            assert "warning" not in result.stdout

    def test_json_is_a_warning_on_an_ok_run(self, runner, tmp_path, staged):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, kivy_version="3.0.0")
            _source(Path(fs), "main.py", "if True:\n    import ios\n")
            result = runner.invoke(build, ["-p", "ios", "--json"])
            envelope = json.loads(result.stdout)  # one document, nothing else
            assert result.exit_code == exit_codes.SUCCESS
            assert envelope["command"] == "build"
            assert envelope["platform"] == "ios"
            assert envelope["ok"] is True
            [diagnostic] = envelope["diagnostics"]
            assert diagnostic["code"] == CODE
            assert diagnostic["severity"] == "warning"
            assert diagnostic["message"].startswith(f"src/main.py:2 {SENTENCE}. ")
            assert GUIDE in diagnostic["message"]
            assert diagnostic["context"] == {
                "file": "src/main.py",
                "line": "2",
                "files": "1",
            }
            # The project was still generated: a warning does not stop the build.
            assert [a["kind"] for a in envelope["data"]["artifacts"]] == ["project"]

    def test_no_import_no_warning(self, runner, tmp_path, staged):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, kivy_version="3.0.0")
            result = runner.invoke(build, ["-p", "ios", "--json"])
            envelope = json.loads(result.stdout)
            assert envelope["ok"] is True
            assert envelope["diagnostics"] == []
            assert "warning" not in result.stderr

    def test_apps_own_ios_py_is_quiet(self, runner, tmp_path, staged):
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            _write_project(fs, kivy_version="3.0.0")
            _source(Path(fs), "main.py", "import ios\n")
            _source(Path(fs), "ios.py", "")
            result = runner.invoke(build, ["-p", "ios", "--json"])
            assert json.loads(result.stdout)["diagnostics"] == []
