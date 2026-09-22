"""T3: assert AGP's *merged* release manifest carries what config declared.

The manifest kivyforge generates is covered by the hermetic generation tests.
This covers the one that actually ships — the output of AGP's manifest merge,
after every ``.aar`` and Maven library manifest has contributed to it. The two
are different documents, and only the second one is in the APK.

``kivyforge package`` already exports that document: the generated
``exportKivyforgeReleaseManifest`` task copies it to
``MERGED_MANIFEST_RELPATH`` so the release policy pass can lint it. Until now
nothing looked at whether it still *contained the project's declarations* —
policy lints for a dangerous posture and would pass a manifest that had
silently lost every permission the project asked for (test-matrix.md §5.1).

Driven by ``--android-merged-manifest`` plus ``--android-project``. Both are
needed because the check is a comparison: the manifest is one side of it and
``pyproject.toml`` is the other. Skips without them so a local `pytest` run
stays green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kivyforge.config.loader import load_config
from kivyforge.config.model import Config
from kivyforge.platforms.android.generate.project import MERGED_MANIFEST_RELPATH
from tests.artifact_checks import android_manifest_problems

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def merged_manifest(pytestconfig) -> Path:
    given = pytestconfig.getoption("--android-merged-manifest")
    if not given:
        pytest.skip(
            "no --android-merged-manifest given; T3 needs the merged manifest "
            f"`kivyforge package` exports to {MERGED_MANIFEST_RELPATH.as_posix()}"
        )
    path = Path(given)
    if not path.is_file():
        pytest.fail(f"--android-merged-manifest {path} does not exist")
    return path


@pytest.fixture(scope="module")
def project_config(pytestconfig) -> Config:
    given = pytestconfig.getoption("--android-project")
    if not given:
        # A fail rather than a skip: the manifest was supplied, so the run
        # intended to check it, and quietly checking nothing is the failure
        # mode this whole tier exists to remove.
        pytest.fail(
            "--android-merged-manifest needs --android-project too; the check "
            "compares the merged manifest against that project's pyproject.toml"
        )
    pyproject = Path(given) / "pyproject.toml"
    if not pyproject.is_file():
        pytest.fail(f"--android-project {given} has no pyproject.toml")
    return load_config(pyproject, require_ios=False, require_android=True)


def test_the_merged_manifest_declares_what_config_asked_for(
    merged_manifest, project_config
):
    android = project_config.android
    assert android is not None, "load_config(require_android=True) guarantees this"

    problems = android_manifest_problems(
        merged_manifest.read_text(encoding="utf-8"),
        android=android,
        orientation=project_config.kivy.orientation,
        version_name=project_config.project.version,
    )
    assert not problems, (
        f"{merged_manifest.name} does not carry what pyproject.toml declared:\n  "
        + "\n  ".join(problems)
    )
