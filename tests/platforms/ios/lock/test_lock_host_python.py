"""``kivyforge lock`` and the host-CPython table, through the CLI (iOS).

The lookup is the suite's ``FakeHostPythonFetcher`` (tests/conftest.py), so
these count its calls to prove when ``lock`` stays off the network.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from click.testing import CliRunner

from kivyforge.cli import lock as lock_cli
from kivyforge.cli.lock import lock
from kivyforge.lock import host_python as hp
from kivyforge.platforms.ios.lock import dumps, load
from kivyforge.report import diagnostics, exit_codes


@pytest.fixture(autouse=True)
def patch_backends(monkeypatch, fake_resolver, fake_python_provider):
    import kivyforge.platforms.ios.lock.builder as builder

    real_build = builder.build_lockfile

    def fake_build(config, *, project_root=None, prefer=(), offline=False, **_kw):
        return real_build(
            config,
            project_root=project_root,
            resolver=fake_resolver,
            python_provider=fake_python_provider,
            prefer=prefer,
            offline=offline,
        )

    monkeypatch.setattr(lock_cli, "build_lockfile", fake_build)


@pytest.fixture
def project(tmp_path, minimal_pyproject, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(minimal_pyproject + "\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(*args):
    return CliRunner().invoke(lock, list(args))


def _table(project):
    table = load(project / "pylock.ios.toml").host_python
    assert table is not None
    return table


def _strip_table(project):
    """Rewrite the lock as one written before the table existed."""
    path = project / "pylock.ios.toml"
    path.write_text(dumps(dataclasses.replace(load(path), host_python=None)))


class TestLockWritesTheTable:
    def test_pins_the_mac_host(self, project, host_python_fetcher):
        result = _run()
        assert result.exit_code == 0, result.output
        (entry,) = _table(project)
        assert entry.triple == hp.MACOS_ARM64
        assert entry.state == hp.PINNED
        assert entry.variant == "install_only_stripped"
        assert len(host_python_fetcher.calls) == 1

    def test_the_table_is_in_the_file(self, project):
        _run()
        text = (project / "pylock.ios.toml").read_text()
        assert "[[tool.kivyforge.host_python]]" in text
        assert 'state = "pinned"' in text


class TestCheckStaysOffTheNetwork:
    def test_a_complete_lock_passes_without_a_lookup(
        self, project, host_python_fetcher
    ):
        _run()
        calls = len(host_python_fetcher.calls)
        result = _run("--check")
        assert result.exit_code == 0, result.output
        assert len(host_python_fetcher.calls) == calls

    def test_plain_lock_keeps_the_pins(self, project, host_python_fetcher):
        _run()
        before = _table(project)
        calls = len(host_python_fetcher.calls)
        result = _run()
        assert "already in sync" in result.output
        assert _table(project) == before
        assert len(host_python_fetcher.calls) == calls


class TestAnOlderLock:
    def test_check_reports_it_incomplete_not_drifted(self, project):
        _run()
        _strip_table(project)
        result = _run("--check", "--json")
        assert result.exit_code == exit_codes.LOCK_DRIFT
        envelope = json.loads(result.stdout)
        assert envelope["diagnostics"][-1]["code"] == diagnostics.LOCK_INCOMPLETE
        assert "kivyforge lock" in envelope["diagnostics"][-1]["remediation"]

    def test_plain_lock_completes_it_and_keeps_every_other_pin(self, project):
        """Not "already in sync": the shortcut checks the table first (3.3)."""
        _run()
        _strip_table(project)
        before = load(project / "pylock.ios.toml")
        result = _run()
        assert result.exit_code == 0, result.output
        assert "host CPython pinned" in result.output
        after = load(project / "pylock.ios.toml")
        assert after.host_python is not None
        assert dataclasses.replace(after, host_python=None) == before

    def test_check_passes_after_that(self, project):
        _run()
        _strip_table(project)
        _run()
        assert _run("--check").exit_code == 0


class TestUpdateRePins:
    def test_update_looks_the_host_python_up_again(self, project, host_python_fetcher):
        _run()
        calls = len(host_python_fetcher.calls)
        result = _run("--update")
        assert result.exit_code == 0, result.output
        assert len(host_python_fetcher.calls) == calls + 1


class TestOffline:
    def test_a_first_offline_lock_records_unresolved(self, project):
        result = _run("--offline", "--json")
        assert result.exit_code == 0, result.output
        (entry,) = _table(project)
        assert entry.state == hp.UNRESOLVED_OFFLINE
        warnings = [d for d in json.loads(result.stdout)["diagnostics"]]
        assert any("locked offline" in d["message"] for d in warnings)

    def test_check_then_reports_it_incomplete(self, project):
        _run("--offline")
        result = _run("--check", "--json")
        assert result.exit_code == exit_codes.LOCK_DRIFT
        assert json.loads(result.stdout)["diagnostics"][-1]["code"] == (
            diagnostics.LOCK_INCOMPLETE
        )

    def test_plain_lock_with_network_resolves_it(self, project):
        _run("--offline")
        result = _run()
        assert result.exit_code == 0, result.output
        (entry,) = _table(project)
        assert entry.state == hp.PINNED


class TestNoBuildYet:
    @pytest.fixture
    def no_builds(self, host_python_fetcher, monkeypatch):
        monkeypatch.setattr(
            host_python_fetcher,
            "find_common_install_only",
            lambda minor, triples, **kw: (None, {}),
        )

    def test_lock_succeeds_and_warns(self, project, no_builds):
        result = _run("--json")
        assert result.exit_code == 0, result.output
        (entry,) = _table(project)
        assert entry.state == hp.NO_BUILD
        messages = [d["message"] for d in json.loads(result.stdout)["diagnostics"]]
        assert any("no final python-build-standalone CPython" in m for m in messages)

    def test_check_passes_with_a_warning(self, project, no_builds):
        _run()
        result = _run("--check", "--json")
        assert result.exit_code == 0, result.output
        codes = [d["code"] for d in json.loads(result.stdout)["diagnostics"]]
        assert diagnostics.LOCK_WARNING in codes
