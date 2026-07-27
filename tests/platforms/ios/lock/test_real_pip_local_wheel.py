"""Integration test: the real ``PipResolver`` against a genuinely local wheel.

Every other lock test in this package injects ``FakeResolver`` /
``FakeSpmResolver`` (see ``conftest.py``'s own module docstring: "no network,
no pip subprocess"). That keeps the suite fast, but it also means no test
ever exercises a real pip subprocess resolving a real ``file://`` wheel — the
one seam the rest of the suite deliberately fakes around. The other lock
tests already cover everything on either side of that seam:

- ``find_links`` config parsing + repo-boundary scope rules
  (``tests/config/test_loader.py``).
- ``_normalize_wheel_source`` given a real ``file://`` URI on real files
  (``test_find_links.py::TestBuildUsesFindLinksValidation``).
- ``LockedWheel(path=...)`` <-> TOML round-trip (``tests/lock/test_pep751.py``).

What none of them touch is pip's own JSON ``--report`` output for a wheel
that only exists on disk, which is exactly the kind of "did we correctly
understand the tool's real contract" risk fakes cannot catch (see this
session's marker-retargeting fix for a case where that risk was real).

This still needs no network: pip resolves purely from a local ``find_links``
directory (``offline=True`` => ``--no-index``, no ``extra_index_urls``)
against a hand-built minimal wheel. The wheel is a ``py3-none-any`` universal
wheel, which pip accepts for any ``--platform``/``--abi``/``--implementation``
it's given — so this needs no iOS toolchain and runs on any host with a
modern pip, matching the resolver's own host-independence design.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from kivyforge.config import load_config_from_text
from kivyforge.platforms.ios.lock import PipResolver, build_lockfile

from .conftest import FakePythonProvider


def _write_minimal_wheel(directory: Path, *, name: str, version: str) -> Path:
    """Hand-build a minimal, genuinely valid pure-Python wheel."""
    dist_info = f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    wheel_meta = (
        "Wheel-Version: 1.0\n"
        "Generator: kivyforge-test\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    )
    filename = f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
    path = directory / filename
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{dist_info}/METADATA", metadata)
        zf.writestr(f"{dist_info}/WHEEL", wheel_meta)
        zf.writestr(f"{dist_info}/RECORD", "")
    return path


def _pyproject_text(pkg_name: str) -> str:
    return (
        "[project]\n"
        "name = 'app'\n"
        "version = '1'\n"
        f"dependencies = ['{pkg_name}']\n"
        "[tool.kivy]\n"
        "app_dir = 'src'\n"
        "[tool.kivy.ios]\n"
        "schema_version = 1\n"
        "bundle_id = 'o.x.app'\n"
        "find_links = ['wheels']\n"
        "[tool.kivy.ios.python]\n"
        "version = '3.15.0'\n"
    )


def test_pip_resolver_locks_a_real_local_wheel_to_path(tmp_path):
    """The seam FakeResolver can never exercise: a real pip subprocess
    resolving a wheel that only exists on disk, end-to-end into a lockfile
    ``path =`` entry with the right relative path and sha256."""
    project = tmp_path / "app"
    project.mkdir()
    wheels = project / "wheels"
    wheels.mkdir()
    wheel_path = _write_minimal_wheel(wheels, name="kf-localtest", version="0.1.0")

    text = _pyproject_text("kf-localtest")
    cfg = load_config_from_text(text)

    lock = build_lockfile(
        cfg,
        text,
        project_root=project,
        resolver=PipResolver(),
        python_provider=FakePythonProvider(),
        offline=True,
    )

    packages = {p.name: p for p in lock.packages}
    assert "kf-localtest" in packages
    pkg = packages["kf-localtest"]
    assert pkg.version == "0.1.0"

    # A pure-Python "any" wheel resolves once, not once per iOS slice — unlike
    # a compiled package, there is only ever one wheel to pin here.
    assert len(pkg.wheels) == 1
    wheel = pkg.wheels[0]
    assert wheel.path == f"wheels/{wheel_path.name}"
    assert wheel.url is None
    assert wheel.sha256 == hashlib.sha256(wheel_path.read_bytes()).hexdigest()
