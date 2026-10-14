"""Real build backends agree with the app metadata kivyforge generates.

docs/design/dev/package-metadata-proposal.md section 5, layer 2: spikes S1 and
S2 as tests, so a backend that changes behaviour fails here first.

* setuptools, hatchling, pdm-backend, flit-core and poetry-core each build a
  wheel of one project using every entry-point form, and each wheel's
  ``entry_points.txt`` reads back as what kivyforge writes from ``[project]``
  alone. Compared as Python reads them, ``(group, name, module, attr,
  extras)``, because poetry-core spells ``Fancy [fancy]`` as ``Fancy[fancy]``.
* setuptools still takes entry points from ``setup.cfg``/``setup.py`` when
  ``[project]`` declares none (F2), also with an empty
  ``[project.entry-points]`` table (F7), with a deprecation warning; and only
  ``[project]``'s when it declares some. The error of section 2.3 rests on
  this. When setuptools stops including them, a test here fails, and 2.3 can
  be revisited.

Needs the network (pip installs each backend into an isolated build
environment), so it runs only with ``--app-metadata-live``.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from kivyforge.bundle import app_metadata
from kivyforge.config.loader import load_declared_project

pytestmark = pytest.mark.integration

BACKENDS = {
    "setuptools": ('"setuptools>=64"', "setuptools.build_meta"),
    "hatchling": ('"hatchling"', "hatchling.build"),
    "pdm-backend": ('"pdm-backend"', "pdm.backend"),
    "flit-core": ('"flit_core>=3.4"', "flit_core.buildapi"),
    "poetry-core": ('"poetry-core>=2"', "poetry.core.masonry.api"),
}

PROJECT = """\
[build-system]
requires = [{requires}]
build-backend = "{backend}"

[project]
name = "metaprobe-live"
version = "1.2.3"
description = "The package-metadata layer 2 probe"
{project_extra}
"""

EVERY_FORM = """
[project.scripts]
probe-cli = "metaprobe_live.cli:main"

[project.gui-scripts]
probe-gui = "metaprobe_live.cli:gui"

[project.entry-points."metaprobe.plugins"]
MyPlugin = "metaprobe_live.plugins:Mine"
fancy = "metaprobe_live.extra:Fancy [fancy]"
module-only = "metaprobe_live.loose"

[project.entry-points.pytest11]
probe = "metaprobe_live.pytest_plugin"
"""

SETUP_CFG = """\
[options.entry_points]
metaprobe.plugins =
    from-setup-cfg = metaprobe_live:FromCfg
"""

SETUP_PY = """\
from setuptools import setup

setup(entry_points={"metaprobe.plugins": ["from-setup-py = metaprobe_live:FromPy"]})
"""

#: setuptools' deprecation of entry points from outside [project] (F2).
_IGNORED = re.compile(r"entry.points.*outside of .?pyproject\.toml.? is ignored", re.I)


@pytest.fixture(scope="module", autouse=True)
def _opted_in(pytestconfig) -> None:
    if not pytestconfig.getoption("--app-metadata-live"):
        pytest.skip("no --app-metadata-live given; needs the network")


def _project(root: Path, backend: str, project_extra: str, **files: str) -> Path:
    requires, build_backend = BACKENDS[backend]
    root.mkdir()
    (root / "pyproject.toml").write_text(
        PROJECT.format(
            requires=requires, backend=build_backend, project_extra=project_extra
        ),
        encoding="utf-8",
    )
    package = root / "metaprobe_live"
    package.mkdir()
    (package / "__init__.py").write_text('"""Probe."""\n', encoding="utf-8")
    for name, text in files.items():
        (root / name.replace("_", ".")).write_text(text, encoding="utf-8")
    return root


def _wheel(project: Path, out: Path) -> tuple[Path, str]:
    """Build with pip, isolated; return the wheel and the backend's output."""
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-v"]
        + ["--wheel-dir", str(out), str(project)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    (wheel,) = out.glob("*.whl")
    return wheel, proc.stdout + proc.stderr


def _as_read(dist_info: Path) -> set[tuple]:
    """Entry points as ``importlib.metadata`` reads them from a folder."""
    return {
        (e.group, e.name, e.module, e.attr, tuple(e.extras))
        for e in md.PathDistribution(dist_info).entry_points
    }


def _wheel_entry_points(wheel: Path, tmp_path: Path) -> set[tuple]:
    folder = tmp_path / "from-wheel.dist-info"
    folder.mkdir()
    with zipfile.ZipFile(wheel) as zf:
        (name,) = [
            n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt")
        ]
        (folder / "entry_points.txt").write_bytes(zf.read(name))
    return _as_read(folder)


def _generated_entry_points(project: Path, tmp_path: Path) -> set[tuple]:
    declared, _ = load_declared_project(project / "pyproject.toml")
    folder = tmp_path / "generated.dist-info"
    folder.mkdir()
    text = app_metadata.render_entry_points(declared.entry_points)
    (folder / "entry_points.txt").write_text(text, encoding="utf-8")
    return _as_read(folder)


@pytest.mark.parametrize("backend", sorted(BACKENDS))
def test_every_backend_writes_what_kivyforge_writes(tmp_path, backend):
    """S1: reading ``[project]`` alone gives what a backend produces."""
    project = _project(tmp_path / "proj", backend, EVERY_FORM)

    wheel, _ = _wheel(project, tmp_path / "out")

    built = _wheel_entry_points(wheel, tmp_path)
    assert built == _generated_entry_points(project, tmp_path)
    assert ("metaprobe.plugins", "MyPlugin", "metaprobe_live.plugins", "Mine", ()) in (
        built
    )


def _plugins(wheel: Path, tmp_path: Path) -> set[str]:
    found = _wheel_entry_points(wheel, tmp_path)
    return {name for group, name, *_ in found if group == "metaprobe.plugins"}


class TestSetuptoolsOutsideProject:
    """S2/F2/F7, and kivyforge's 2.3 decision on each case beside it."""

    def _check(self, project: Path) -> bool:
        declared, _ = load_declared_project(project / "pyproject.toml")
        try:
            app_metadata.check_declaration(declared, project)
        except app_metadata.EntryPointsOutsideProject:
            return False
        return True

    def test_setup_cfg_alone_is_used_with_a_warning(self, tmp_path):
        project = _project(tmp_path / "p", "setuptools", "", setup_cfg=SETUP_CFG)
        wheel, output = _wheel(project, tmp_path / "out")
        assert _plugins(wheel, tmp_path) == {"from-setup-cfg"}
        assert _IGNORED.search(output), output[-3000:]
        assert not self._check(project)  # 2.3: an error

    def test_an_empty_table_changes_nothing(self, tmp_path):
        extra = "\n[project.entry-points]\n"
        project = _project(tmp_path / "p", "setuptools", extra, setup_py=SETUP_PY)
        wheel, _ = _wheel(project, tmp_path / "out")
        assert _plugins(wheel, tmp_path) == {"from-setup-py"}
        assert not self._check(project)

    def test_dynamic_takes_them_without_a_warning(self, tmp_path):
        extra = 'dynamic = ["entry-points"]\n'
        project = _project(tmp_path / "p", "setuptools", extra, setup_cfg=SETUP_CFG)
        wheel, output = _wheel(project, tmp_path / "out")
        assert _plugins(wheel, tmp_path) == {"from-setup-cfg"}
        assert not _IGNORED.search(output)
        assert self._check(project)  # 2.4: a warning instead

    def test_static_scripts_drop_dynamic_setup_cfg_groups(self, tmp_path):
        """Found by the metaprobe (2026-10-14): ``scripts`` static, only
        ``entry-points`` dynamic, and setuptools 84 builds without
        ``setup.cfg``'s groups and without a warning. kivyforge warns (2.4)
        and generates nothing, so the app gets exactly what setuptools wrote;
        this pins what that is."""
        extra = (
            'dynamic = ["entry-points"]\n'
            '[project.scripts]\nprobe-cli = "metaprobe_live:main"\n'
        )
        project = _project(tmp_path / "p", "setuptools", extra, setup_cfg=SETUP_CFG)
        wheel, output = _wheel(project, tmp_path / "out")
        groups = {e[0] for e in _wheel_entry_points(wheel, tmp_path)}
        assert groups == {"console_scripts"}
        assert not _IGNORED.search(output)
        assert self._check(project)

    def test_project_entry_points_win(self, tmp_path):
        extra = '\n[project.entry-points."metaprobe.plugins"]\nours = "metaprobe_live:Ours"\n'
        project = _project(
            tmp_path / "p", "setuptools", extra, setup_cfg=SETUP_CFG, setup_py=SETUP_PY
        )
        wheel, _ = _wheel(project, tmp_path / "out")
        assert _plugins(wheel, tmp_path) == {"ours"}
        assert self._check(project)  # generated from [project], as setuptools does
