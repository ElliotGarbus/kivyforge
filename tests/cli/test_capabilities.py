"""``kivyforge capabilities`` — the introspection verb (roadmap item 3, point 6).

The value of this verb is that nothing in it is restated: these tests check it
stays *derived*, because a hand-maintained copy would pass a shape assertion
right up until the day it went stale.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from kivyforge.capabilities import HOSTS, collect
from kivyforge.cli import main
from kivyforge.cli.capabilities import capabilities
from kivyforge.platforms import available_platform_names, get_platform
from kivyforge.report import diagnostics, exit_codes


@pytest.fixture
def runner():
    return CliRunner()


def _data(runner, args=()):
    result = runner.invoke(capabilities, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


class TestEnvelope:
    def test_shape(self, runner):
        envelope = _data(runner)
        assert envelope["command"] == "capabilities"
        assert envelope["ok"] is True
        # No project, so no target platform: the key is nullable for this case.
        assert envelope["platform"] is None
        assert envelope["diagnostics"] == []

    def test_needs_no_project(self, runner, tmp_path, monkeypatch):
        """An agent asks this *before* it has a pyproject.toml to point at."""
        monkeypatch.chdir(tmp_path)
        envelope = _data(runner)
        assert envelope["data"]["platforms"]


class TestDerivedFromTheRegistry:
    def test_every_registered_platform_appears(self, runner):
        envelope = _data(runner)
        names = [p["name"] for p in envelope["data"]["platforms"]]
        assert names == available_platform_names()

    def test_formats_and_aliases_come_from_the_backends(self, runner):
        envelope = _data(runner)
        for entry in envelope["data"]["platforms"]:
            backend = get_platform(entry["name"])
            assert tuple(entry["package_formats"]) == backend.package_formats
            assert tuple(entry["aliases"]) == backend.aliases
            assert entry["default_package_format"] == backend.default_package_format
            assert tuple(entry["archs"]) == backend.archs

    def test_the_host_matrix_is_asked_of_each_backend(self, runner):
        """Not a table: the same check the verbs gate on, per host."""
        envelope = _data(runner)
        by_name = {p["name"]: p for p in envelope["data"]["platforms"]}
        # iOS is the case that matters: it is why the verb exists.
        assert by_name["ios"]["hosts"] == {
            "Darwin": True,
            "Linux": False,
            "Windows": False,
        }
        # Android is cross-compiled from anywhere; the desktops are host-only.
        assert all(by_name["android"]["hosts"][host] for host in HOSTS)
        assert by_name["windows"]["hosts"] == {
            "Darwin": False,
            "Linux": False,
            "Windows": True,
        }

    def test_a_backend_whose_gate_changes_changes_the_matrix(self, monkeypatch):
        """The matrix follows the code, which is the whole claim."""
        monkeypatch.setattr(
            get_platform("ios"), "check_host_capability", lambda **kw: None
        )
        found = collect()
        ios = next(p for p in found.platforms if p.name == "ios")
        assert ios.buildable_on == HOSTS

    def test_host_default_matches_the_resolution_chain(self, runner):
        envelope = _data(runner)
        for entry in envelope["data"]["platforms"]:
            assert entry["host_default_for"] == get_platform(entry["name"]).host_system


class TestVocabularies:
    def test_verbs_are_read_off_the_group(self, runner):
        envelope = _data(runner)
        listed = {entry["name"]: entry["json"] for entry in envelope["data"]["verbs"]}
        assert set(listed) == set(main.commands)
        # run is the one verb deliberately left human-only.
        assert listed["run"] is False
        assert listed["build"] is True

    def test_exit_codes_are_the_reserved_taxonomy(self, runner):
        envelope = _data(runner)
        assert envelope["data"]["exit_codes"] == {
            str(code): meaning for code, meaning in exit_codes.RESERVED.items()
        }

    def test_diagnostic_codes_are_the_published_vocabulary(self, runner):
        envelope = _data(runner)
        codes = envelope["data"]["diagnostic_codes"]
        assert codes == sorted(codes)
        # Spot-check both ends: a failure code and a success-path note.
        assert diagnostics.LOCK_DRIFT in codes
        assert diagnostics.SIGNING_UNCONFIGURED in codes
        assert all(code.startswith("KF-") for code in codes)


class TestHumanReport:
    def test_names_platforms_hosts_and_exit_codes(self, runner):
        result = runner.invoke(capabilities, [])
        assert result.exit_code == 0
        assert "Platforms" in result.stdout
        assert "ios" in result.stdout
        assert "macOS" in result.stdout  # friendlier than "Darwin" for a human
        assert "Human-only verbs:  run" in result.stdout
        assert "5  build failed" in result.stdout

    def test_json_suppresses_the_human_report(self, runner):
        result = runner.invoke(capabilities, ["--json"])
        assert "Platforms" not in result.stdout
        json.loads(result.stdout)  # exactly one document
