"""What pip and setuptools do when asked only for a project's metadata.

docs/design/dev/dynamic-version-proposal.md resolves a dynamic
``[project].version`` by running ``pip install --dry-run --report`` on the
project, isolated by default and with ``--no-build-isolation`` only on request.
These tests pin the behaviour that design rests on, against real setuptools-scm
projects in temporary git repositories:

* both modes report the version setuptools-scm derives from git;
* the isolated run writes ``<name>.egg-info`` into the project tree, and the
  non-isolated run does not;
* a project that gets setuptools-scm through ``setup_requires`` reports
  ``0.0.0``, with pip exiting 0, when run non-isolated in an environment that
  satisfies ``[build-system].requires``. This is why isolation is the default
  and not chosen automatically;
* with an older copy of the project installed where pip runs (the usual state
  under ``uv run``), the report still gives the tree's version;
* a non-setuptools backend (hatchling with hatch-vcs) resolves the same way and
  leaves the tree untouched.

The design documents the egg-info as a side effect rather than undoing it, and
its cause is pinned too. With isolation, pip calls the backend's ``get_requires_for_build_wheel`` hook to
learn what else to install into the build environment, and setuptools implements
that hook by running a plain ``egg_info`` command, which writes to the project's
package root (the project root, or ``src/`` in a src layout).
``prepare_metadata_for_build_wheel`` keeps its own egg-info in the metadata
directory pip hands it. Without isolation pip installs nothing, so it never asks
and the egg-info is never written. ``test_get_requires_hook_writes_egg_info``
calls the two hooks directly, so the cause is shown without depending on pip's
log wording.

Needs git and the network, so it runs only with ``--pip-metadata-live``, and
once opted in a missing precondition **fails** rather than skips.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

PYPROJECT = """\
[build-system]
requires = ["setuptools>=64", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
name = "myapp"
dynamic = ["version"]

[tool.setuptools_scm]
"""

# One commit past tag v1.2.3: setuptools-scm's default scheme bumps the patch
# and appends the distance and the short commit hash.
DEV_VERSION = re.compile(r"1\.2\.4\.dev1\+g([0-9a-f]{7,})")


@pytest.fixture(scope="module", autouse=True)
def _opted_in(pytestconfig) -> None:
    if not pytestconfig.getoption("--pip-metadata-live"):
        pytest.skip("no --pip-metadata-live given; needs git and network")
    if shutil.which("git") is None:
        pytest.fail("--pip-metadata-live given, but git is not on PATH")


def _git(repo: Path, *args: str) -> str:
    # An empty global config and no system config, so the user's signing or
    # hook settings cannot change what gets committed.
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _make_project(root: Path, *, src_layout: bool) -> Path:
    root.mkdir()
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    package = (root / "src" / "myapp") if src_layout else (root / "myapp")
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "tag", "v1.2.3")
    (root / "CHANGES").write_text("one more\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "after the tag")
    return root


def _egg_infos(root: Path) -> list[str]:
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*.egg-info")
        if ".git" not in p.parts
    )


@pytest.fixture(scope="module")
def backend_python(tmp_path_factory) -> Path:
    """A venv with the backend installed, for the non-isolated mode."""
    env_dir = tmp_path_factory.mktemp("backend-venv")
    venv.create(env_dir, with_pip=True)
    bindir = "Scripts" if sys.platform == "win32" else "bin"
    python = env_dir / bindir / ("python.exe" if sys.platform == "win32" else "python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "-q", "pip>=25.1", "setuptools>=64"]
        + ["setuptools-scm>=8"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
    )
    return python


def _pip_metadata_version(python: Path, project: Path, *, isolated: bool) -> str:
    cmd = [str(python), "-m", "pip", "install", "--dry-run", "--ignore-installed"]
    cmd += ["--no-deps", "--quiet", "--report", "-"]
    if not isolated:
        cmd.append("--no-build-isolation")
    proc = subprocess.run(
        [*cmd, str(project)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["install"][0]["metadata"]["version"]


def _assert_dev_version(version: str, project: Path) -> None:
    match = DEV_VERSION.fullmatch(version)
    assert match, version
    assert _git(project, "rev-parse", "HEAD").startswith(match.group(1))


@pytest.mark.parametrize("src_layout", [False, True], ids=["flat", "src"])
def test_isolated_reports_version_and_writes_egg_info(tmp_path, src_layout):
    project = _make_project(tmp_path / "proj", src_layout=src_layout)
    assert _egg_infos(project) == []

    version = _pip_metadata_version(Path(sys.executable), project, isolated=True)

    _assert_dev_version(version, project)
    expected = "src/myapp.egg-info" if src_layout else "myapp.egg-info"
    assert _egg_infos(project) == [expected]


@pytest.mark.parametrize("src_layout", [False, True], ids=["flat", "src"])
def test_non_isolated_reports_version_and_leaves_tree_clean(
    tmp_path, backend_python, src_layout
):
    project = _make_project(tmp_path / "proj", src_layout=src_layout)

    version = _pip_metadata_version(backend_python, project, isolated=False)

    _assert_dev_version(version, project)
    assert _egg_infos(project) == []


def test_get_requires_hook_writes_egg_info(tmp_path, backend_python):
    """The cause: setuptools' get_requires hook, not the metadata hook."""
    project = _make_project(tmp_path / "proj", src_layout=False)
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    call_hook = (
        "import sys, setuptools.build_meta as b\n"
        "if sys.argv[1] == 'get_requires':\n"
        "    b.get_requires_for_build_wheel()\n"
        "else:\n"
        "    b.prepare_metadata_for_build_wheel(sys.argv[2])\n"
    )

    def run(*args: str) -> None:
        subprocess.run(
            [str(backend_python), "-c", call_hook, *args],
            cwd=project,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
        )

    run("prepare_metadata", str(metadata_dir))
    assert _egg_infos(project) == []
    assert any(metadata_dir.glob("*.dist-info"))

    run("get_requires")
    assert _egg_infos(project) == ["myapp.egg-info"]


LEGACY_PYPROJECT = """\
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"
"""

LEGACY_SETUP = """\
from setuptools import setup

setup(
    name="myapp",
    packages=["myapp"],
    use_scm_version=True,
    setup_requires=["setuptools-scm"],
)
"""


@pytest.fixture(scope="module")
def setuptools_only_python(tmp_path_factory) -> Path:
    """A venv satisfying LEGACY_PYPROJECT's requires, without setuptools-scm."""
    env_dir = tmp_path_factory.mktemp("setuptools-only-venv")
    venv.create(env_dir, with_pip=True)
    bindir = "Scripts" if sys.platform == "win32" else "bin"
    python = env_dir / bindir / ("python.exe" if sys.platform == "win32" else "python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "-q", "pip>=25.1", "setuptools>=64"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
    )
    return python


def test_non_isolated_misses_setup_requires_silently(tmp_path, setuptools_only_python):
    """Satisfied [build-system].requires is not enough: pip says 0.0.0, exit 0."""
    project = tmp_path / "legacy"
    (project / "myapp").mkdir(parents=True)
    (project / "myapp" / "__init__.py").write_text("", encoding="utf-8")
    (project / "pyproject.toml").write_text(LEGACY_PYPROJECT, encoding="utf-8")
    (project / "setup.py").write_text(LEGACY_SETUP, encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "init")
    _git(project, "tag", "v1.2.3")

    python = setuptools_only_python
    assert _pip_metadata_version(python, project, isolated=False) == "0.0.0"
    assert _pip_metadata_version(python, project, isolated=True) == "1.2.3"


def test_ignore_installed_reports_the_tree_not_the_installed_copy(
    tmp_path, backend_python
):
    """Under `uv run kf` the project is usually installed where pip runs."""
    project = _make_project(tmp_path / "proj", src_layout=False)
    _git(project, "checkout", "-q", "v1.2.3")
    pip = [str(backend_python), "-m", "pip"]
    install = [*pip, "install", "-q", "--no-build-isolation", str(project)]
    subprocess.run(install, stdin=subprocess.DEVNULL, capture_output=True, check=True)
    _git(project, "checkout", "-q", "-")
    try:
        version = _pip_metadata_version(backend_python, project, isolated=False)
        _assert_dev_version(version, project)
    finally:
        subprocess.run(
            [*pip, "uninstall", "-qy", "myapp"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
        )


HATCH_PYPROJECT = """\
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "myapp"
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
"""


def test_hatch_vcs_resolves_and_leaves_the_tree_untouched(tmp_path):
    project = tmp_path / "hatch"
    (project / "src" / "myapp").mkdir(parents=True)
    (project / "src" / "myapp" / "__init__.py").write_text("", encoding="utf-8")
    (project / "pyproject.toml").write_text(HATCH_PYPROJECT, encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "init")
    _git(project, "tag", "v1.2.3")
    (project / "CHANGES").write_text("one more\n", encoding="utf-8")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "after the tag")

    version = _pip_metadata_version(Path(sys.executable), project, isolated=True)

    _assert_dev_version(version, project)
    assert _git(project, "status", "--porcelain", "--ignored") == ""
