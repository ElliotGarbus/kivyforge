"""``kivyforge bytecompiler`` — which platforms it covers, and what it installs.

The backends, the search and the install are faked: this pins the verb's own
decisions (docs/design/dev/host-python-download-proposal.md section 3.2). Each
backend's ``byte_compile_need`` is tested beside it, and the install in
``tests/bundle/test_hostpython.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kivyforge.bundle import hostpython
from kivyforge.bundle.hostpython import ByteCompileNeed, Installed
from kivyforge.bundle.pycompile import Candidate
from kivyforge.cli import bytecompiler as verb
from kivyforge.platforms import HostCapabilityError
from kivyforge.report import diagnostics, exit_codes
from kivyforge.report.failures import ClassifiedError

LOCK_MISSING = ClassifiedError(
    "pylock.android.toml is missing, so the version android ships is unknown.\n"
    "  Fix: run `kivyforge lock -p android`.",
    code=diagnostics.LOCK_MISSING,
    exit_code=exit_codes.LOCK_DRIFT,
)


class _Backend:
    def __init__(self, name, need=None, *, host_ok=True):
        self.name = name
        self._need = need
        self._host_ok = host_ok

    def check_host(self):
        if not self._host_ok:
            raise HostCapabilityError(f"{self.name} needs a Mac")

    def byte_compile_need(self, project_root):
        return self._need


def _need(platform, version: str | None = "3.15.2", **kw):
    fields = {"byte_compile": True, "host_compiler": True, "python_version": version}
    fields.update(kw)
    return ByteCompileNeed(platform, **fields)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project root with a pyproject.toml, as the cwd."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def world(monkeypatch, project):
    """Fake backends, search and install; returns the knobs and the calls."""
    state = {
        "backends": {},
        "found": {},
        "installed": {},
        "installs": [],
        "install_error": None,
    }

    monkeypatch.setattr(
        verb, "configured_platforms", lambda pyproject: set(state["backends"])
    )
    monkeypatch.setattr(verb, "get_platform", lambda name: state["backends"][name])

    def find(version, *, searched=None):
        minor = ".".join(version.split(".")[:2])
        hit = state["found"].get(minor)
        if hit is not None and searched is not None:
            searched.append(Candidate(hit[0], hit[1]))
        return None if hit is None else (hit[0],)

    monkeypatch.setattr(verb, "find_interpreter", find)
    monkeypatch.setattr(
        hostpython,
        "installed_interpreter",
        lambda minor, root=None: state["installed"].get(minor),
    )

    def install(minor, *, prefer=None, on_progress=None, **kw):
        state["installs"].append((minor, prefer))
        if state["install_error"] is not None:
            raise state["install_error"]
        exe = Path(f"/cache/host-python/{minor}/python/bin/python{minor}")
        return Installed(version=prefer or f"{minor}.0", interpreter=exe)

    monkeypatch.setattr(hostpython, "install", install)
    monkeypatch.setattr(verb.shutil, "which", lambda cmd: None)
    return state


def _add(world, name, need=None, **kw):
    world["backends"][name] = _Backend(name, need, **kw)


def _run(*args):
    return CliRunner().invoke(verb.bytecompiler, list(args))


def _json(*args):
    result = _run(*args, "--json")
    return result, json.loads(result.stdout)


class TestCoversConfiguredPlatforms:
    def test_installs_each_minor_the_locks_ship(self, world):
        _add(world, "ios", _need("ios", "3.15.2"))
        _add(world, "android", _need("android", "3.14.6"))
        result, env = _json()
        assert result.exit_code == 0, result.output
        assert world["installs"] == [("3.14", "3.14.6"), ("3.15", "3.15.2")]
        assert [
            (i["minor"], i["platforms"], i["source"])
            for i in env["data"]["interpreters"]
        ] == [
            ("3.14", ["android"], "installed"),
            ("3.15", ["ios"], "installed"),
        ]

    def test_platforms_sharing_a_minor_share_one_install(self, world):
        """Installed at the newest patch any of them ships."""
        _add(world, "ios", _need("ios", "3.15.0"))
        _add(world, "android", _need("android", "3.15.2"))
        result, env = _json()
        assert result.exit_code == 0, result.output
        assert world["installs"] == [("3.15", "3.15.2")]
        assert env["data"]["interpreters"][0]["platforms"] == ["ios", "android"]

    def test_product_lines_on_stdout(self, world):
        _add(world, "ios", _need("ios"))
        result = _run()
        assert result.exit_code == 0, result.output
        exe = Path("/cache/host-python/3.15/python/bin/python3.15")
        assert result.stdout == f"Installed CPython 3.15.2 for byte-compiling: {exe}\n"
        assert "[bytecompiler] ios ships CPython 3.15.2" in result.stderr


class TestNothingInstalledWhenNotNeeded:
    def test_an_interpreter_already_found(self, world):
        world["found"]["3.15"] = ("python3.15", "3.15.0")
        _add(world, "ios", _need("ios"))
        result, env = _json()
        assert result.exit_code == 0, result.output
        assert world["installs"] == []
        (entry,) = env["data"]["interpreters"]
        assert (entry["source"], entry["version"], entry["path"]) == (
            "found",
            "3.15.0",
            "python3.15",
        )

    def test_kivyforges_own_install_is_already_installed(self, world):
        # The search returns str(installed), so the two compare equal on any OS.
        exe = Path("/cache/host-python/3.15/python/bin/python3.15")
        world["found"]["3.15"] = (str(exe), "3.15.2")
        world["installed"]["3.15"] = exe
        _add(world, "ios", _need("ios"))
        _, env = _json()
        assert env["data"]["interpreters"][0]["source"] == "already-installed"

    def test_force_reinstalls_anyway(self, world):
        world["found"]["3.15"] = ("python3.15", "3.15.0")
        _add(world, "ios", _need("ios"))
        result = _run("--force")
        assert result.exit_code == 0, result.output
        assert world["installs"] == [("3.15", "3.15.2")]

    @pytest.mark.parametrize(
        ("need", "reason"),
        [
            (
                _need("macos", host_compiler=False),
                "its build compiles with the runtime it ships",
            ),
            (_need("ios", byte_compile=False), "byte_compile = false"),
            (_need("ios", "3.16.0b2"), "a pre-release"),
        ],
    )
    def test_skipped_platforms_are_reported(self, world, need, reason):
        _add(world, need.platform, need)
        result, env = _json()
        assert result.exit_code == 0, result.output
        assert world["installs"] == []
        assert env["data"]["interpreters"] == []
        (skip,) = env["data"]["skipped"]
        assert skip["platform"] == need.platform
        assert reason in skip["reason"]

    def test_nothing_to_do_says_so(self, world):
        _add(world, "macos", _need("macos", host_compiler=False))
        result = _run()
        assert result.exit_code == 0, result.output
        assert "Nothing to install" in result.stdout


class TestWithoutP:
    def test_a_host_that_cannot_build_a_platform_skips_it(self, world):
        _add(world, "ios", _need("ios"), host_ok=False)
        _add(world, "android", _need("android", "3.14.6"))
        result, env = _json()
        assert result.exit_code == 0, result.output
        assert world["installs"] == [("3.14", "3.14.6")]
        assert [d["code"] for d in env["diagnostics"]] == [diagnostics.HOST_INCAPABLE]
        assert env["diagnostics"][0]["severity"] == diagnostics.INFO

    def test_a_platform_without_a_lock_is_skipped(self, world):
        _add(world, "ios", _need("ios"))
        _add(world, "android", _need("android", None, lock_problem=LOCK_MISSING))
        result, env = _json()
        assert result.exit_code == 0, result.output
        assert world["installs"] == [("3.15", "3.15.2")]
        assert [d["code"] for d in env["diagnostics"]] == [diagnostics.LOCK_MISSING]

    def test_only_lock_problems_fail_with_the_lock_code(self, world):
        _add(world, "android", _need("android", None, lock_problem=LOCK_MISSING))
        result, env = _json()
        assert result.exit_code == exit_codes.LOCK_DRIFT
        assert env["ok"] is False
        assert env["diagnostics"][-1]["code"] == diagnostics.LOCK_MISSING


class TestWithP:
    def test_narrows_to_that_platform(self, world):
        _add(world, "ios", _need("ios"))
        _add(world, "android", _need("android", "3.14.6"))
        result = _run("-p", "android")
        assert result.exit_code == 0, result.output
        assert world["installs"] == [("3.14", "3.14.6")]

    def test_a_missing_lock_fails(self, world):
        _add(world, "android", _need("android", None, lock_problem=LOCK_MISSING))
        result, env = _json("-p", "android")
        assert result.exit_code == exit_codes.LOCK_DRIFT
        assert env["platform"] == "android"
        assert env["diagnostics"][-1]["code"] == diagnostics.LOCK_MISSING

    def test_a_host_that_cannot_build_it_fails(self, world):
        _add(world, "ios", _need("ios"), host_ok=False)
        result, env = _json("-p", "ios")
        assert result.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert env["diagnostics"][-1]["code"] == diagnostics.HOST_INCAPABLE


class TestFailures:
    def test_a_failed_download_is_one_envelope(self, world):
        world["install_error"] = hostpython.HostPythonError(
            "failed to download\n  Fix: retry with network access.",
            code=diagnostics.HOST_PYTHON_FETCH,
        )
        _add(world, "ios", _need("ios"))
        result, env = _json()
        assert result.exit_code == exit_codes.ENVIRONMENT_ERROR
        assert env["ok"] is False
        assert env["diagnostics"][-1]["code"] == diagnostics.HOST_PYTHON_FETCH
        assert env["diagnostics"][-1]["remediation"] == "retry with network access."

    def test_outside_a_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _run()
        assert result.exit_code == exit_codes.CONFIG_ERROR
        assert "pyproject.toml" in result.output
