"""T3: assert a *built* release APK's signature is the one config asked for.

test-matrix.md §5.1 listed "signatures verify — ``apksigner verify``" as the
open half of the signature box (macOS's ``codesign --verify`` closed the other
half on 2026-09-14). This is it.

Its own module rather than another test in ``test_apk_artifact.py`` for two
reasons. It is the only Android T3 check that **spawns a tool** instead of
reading the file — there is no reading a signature block by hand — so it needs
``skip_missing_toolchain`` handling the others do not. And it is the only one
that is meaningful on the **release** APK alone: a debug APK is signed with
the debug keystore, so asserting the project's configured signing posture
against one would be asserting something about Gradle's defaults rather than
about the project. Keeping it separate means the ``android_gradle`` job runs
it once, against the release artifact, instead of running it twice and
skipping half the time — and a skip in this module means something is wrong,
which is the property that makes a skip worth reading.

Driven by ``--android-apk`` plus ``--android-project``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config
from tests.artifact_checks import apksigner_report_problems
from tests.conftest import skip_missing_toolchain

pytestmark = pytest.mark.integration


def _find_apksigner() -> Path | None:
    """The newest ``apksigner`` in the SDK's build-tools, else one on PATH.

    ``adb.sdk_tool`` cannot be reused: ``build-tools`` is versioned, so the
    tool sits at ``build-tools/<version>/apksigner`` rather than under a fixed
    subdirectory, and on Windows it is a ``.bat`` rather than the ``.exe``
    that helper appends.
    """
    from kivyforge.platforms.android.doctor import RealAndroidProbe

    names = ("apksigner.bat", "apksigner") if os.name == "nt" else ("apksigner",)
    sdk = RealAndroidProbe().sdk_root()
    if sdk is not None:
        # Newest version dir first, matching what AGP resolves to; the SDK
        # keeps older build-tools installed alongside.
        for version_dir in sorted(
            (d for d in (sdk / "build-tools").glob("*") if d.is_dir()), reverse=True
        ):
            for name in names:
                candidate = version_dir / name
                if candidate.is_file():
                    return candidate
    found = shutil.which("apksigner")
    return Path(found) if found else None


def test_the_release_apk_signature_verifies(pytestconfig):
    """``apksigner verify`` at the project's own ``min_sdk``.

    Verifying at ``min_sdk`` rather than at apksigner's default is the point.
    The question worth answering is not "is this signature well-formed" but
    "will every platform version this project claims to support accept it",
    and the two differ: a v1-only signature installs happily on API 23 and is
    what the platform ignores from 24 up, which is precisely why
    ``[tool.kivy.android.signing].v1_signing`` defaults off.
    """
    given_apk = pytestconfig.getoption("--android-apk")
    given_project = pytestconfig.getoption("--android-project")
    if not given_apk or not given_project:
        pytest.skip(
            "needs --android-apk and --android-project; the check compares a "
            "built APK's signature against [tool.kivy.android.signing]"
        )
    apk = Path(given_apk)
    if not apk.is_file():
        pytest.fail(f"--android-apk {apk} does not exist")

    config = load_config(
        Path(given_project) / "pyproject.toml", require_ios=False, require_android=True
    )
    android = config.android
    assert android is not None, "load_config(require_android=True) guarantees this"

    apksigner = _find_apksigner()
    if apksigner is None:
        skip_missing_toolchain(
            "apksigner", "not in <sdk>/build-tools/*/ and not on PATH"
        )

    proc = subprocess.run(
        [
            str(apksigner),
            "verify",
            "-v",
            "--min-sdk-version",
            str(android.min_sdk),
            str(apk),
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, (
        f"apksigner verify failed on {apk.name} (exit {proc.returncode}) at "
        f"min_sdk {android.min_sdk}:\n{proc.stdout}\n{proc.stderr}"
    )

    # The scheme lines are on stdout; stderr carries apksigner's warnings and
    # is folded into failure messages rather than parsed, so a warning can
    # never be mistaken for a scheme result.
    problems = apksigner_report_problems(
        proc.stdout, v1_signing=android.signing.v1_signing
    )
    assert not problems, (
        f"{apk.name}'s signature is not what config asked for:\n  "
        + "\n  ".join(problems)
        + f"\n\napksigner said:\n{proc.stdout}"
    )
