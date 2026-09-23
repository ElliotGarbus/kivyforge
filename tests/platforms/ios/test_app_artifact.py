"""T3: assert a *built* iOS ``.app`` is the artifact the build promised.

Driven by ``--ios-app`` — until now iOS was the one platform with no T3 tier
at all (test-matrix.md §5.1): ``ios_simulator`` builds a real ``.app`` on
every push and had nothing inspecting it. Mirrors
``tests/platforms/macos/test_app_artifact.py`` exactly: the checks themselves
are hermetic and unit-tested in ``tests/test_artifact_checks.py``; this module
is only the wiring that points them at a real bundle.

Skips without ``--ios-app`` so a local `pytest` run stays green.

``--ios-project`` additionally turns on the Info.plist-vs-config comparison;
see ``test_the_app_is_internally_consistent``. There is no ``--ios-stripped``
option and no ``.pyc``-magic assertion here — see ``tests/artifact_checks.py``'s
iOS module note on why that check cannot be written honestly yet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config
from kivyforge.platforms.macos.machotools import codesign_verify
from tests.artifact_checks import ios_app_problems, ios_expected_plist

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def app(pytestconfig) -> Path:
    given = pytestconfig.getoption("--ios-app")
    if not given:
        pytest.skip("no --ios-app given; T3 needs an artifact to inspect")
    path = Path(given)
    if not path.is_dir():
        pytest.fail(f"--ios-app {path} does not exist or is not a directory")
    return path


def test_the_app_is_internally_consistent(app, pytestconfig):
    arch = pytestconfig.getoption("--ios-arch")

    # The Info.plist-vs-config half of test-matrix.md §5.1. Without
    # --ios-project only the plist's internal shape is checked.
    project = pytestconfig.getoption("--ios-project")
    expected_plist = None
    if project:
        config = load_config(
            Path(project) / "pyproject.toml", require_macos=False, require_ios=True
        )
        expected_plist = ios_expected_plist(config)

    problems = ios_app_problems(app, arch=arch, expected_plist=expected_plist)
    assert not problems, (
        f"{app.name} is not the artifact the build promised (arch={arch}):\n  "
        + "\n  ".join(problems)
    )


def test_the_app_is_codesigned(app):
    """``codesign --verify`` against a *built* app.

    Reuses the macOS wrapper (``platforms.macos.machotools.codesign_verify``)
    rather than duplicating it: ``codesign`` is the same tool regardless of
    which bundle it is pointed at, and iOS builds — device or simulator, ad-
    hoc or team-signed — are all still Mach-O bundles on a Mac host, the only
    host this test (like every other iOS test) can ever run on.
    """
    if sys.platform != "darwin":
        pytest.skip("codesign is macOS-only")
    assert codesign_verify(app), f"{app.name} does not have a valid code signature"
