"""``kivyforge upgrade`` and the pinned host CPython (proposal 3.10).

It fetches the archive with the platform's other pinned artifacts; the first
build extracts it, offline if need be.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.bundle import hostpython
from kivyforge.cli import upgrade as upgrade_mod
from kivyforge.cli.upgrade import upgrade
from kivyforge.lock import host_python as hp
from kivyforge.platforms.ios.lock import dumps
from kivyforge.report import exit_codes
from tests.cli.test_status_clean_upgrade import PYPROJECT, _lock

PINNED = hp.HostPython(
    hp.MACOS_ARM64,
    hp.PINNED,
    "3.15",
    version="3.15.0",
    variant="install_only_stripped",
    url=f"{hostpython.PBS_DOWNLOAD_BASE}/20261020/cpython-3.15.0-x.tar.gz",
    sha256="d" * 64,
)


@pytest.fixture(autouse=True)
def mac(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("kivyforge.host.host_machine", lambda: "arm64")


@pytest.fixture
def fetched(monkeypatch):
    """Record every artifact fetched, the platform's and the host CPython's."""
    names: list[str] = []

    def fake_fetch(*, name, sha256, filename, url=None, **kw):
        names.append(name)
        return Path("/cache") / filename

    monkeypatch.setattr(upgrade_mod, "fetch_artifact", fake_fetch)
    monkeypatch.setattr(
        hostpython,
        "ensure_archive",
        lambda entry, **kw: names.append("host-python") or Path("/cache/a"),
    )
    return names


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    (tmp_path / "src").mkdir()

    def write(entries=(PINNED,)):
        lock = dataclasses.replace(_lock(PYPROJECT), host_python=entries)
        (tmp_path / "pylock.ios.toml").write_text(dumps(lock))

    write()
    return write


def _run(*args):
    return CliRunner().invoke(upgrade, ["-p", "ios", *args])


def test_no_selector_fetches_it_with_the_runtime(project, fetched):
    result = _run("--json")
    assert result.exit_code == 0, result.output
    assert fetched == ["Python.xcframework", "host-python"]
    assert "host-python" in json.loads(result.stdout)["data"]["refreshed"]


def test_python_fetches_it_too(project, fetched):
    assert _run("--python").exit_code == 0
    assert fetched == ["Python.xcframework", "host-python"]


def test_xcframeworks_leaves_it_alone(project, fetched):
    assert _run("--xcframeworks").exit_code == 0
    assert "host-python" not in fetched


def test_name_host_python_fetches_only_it(project, fetched):
    result = _run("--name", "host-python")
    assert result.exit_code == 0, result.output
    assert fetched == ["host-python"]


def test_name_host_python_without_a_pin_fails(project, fetched):
    project(entries=None)
    result = _run("--name", "host-python")
    assert result.exit_code != 0
    assert "pins no host CPython" in result.output


def test_a_lock_without_a_pin_is_passed_over_with_a_line(project, fetched):
    project(entries=None)
    result = _run()
    assert result.exit_code == 0, result.output
    assert fetched == ["Python.xcframework"]
    assert "Not refreshing the host CPython" in result.stderr


def test_never_forbids_it(project, fetched, monkeypatch):
    monkeypatch.setenv(hostpython.DOWNLOADS_VAR, "never")
    result = _run("--name", "host-python")
    assert result.exit_code == exit_codes.CONFIG_ERROR
    assert hostpython.DOWNLOADS_VAR in result.output
