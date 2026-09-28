"""T3: assert a *built* App Bundle is the artifact the build promised.

Google Play requires an App Bundle for new apps, but until 2026-09-28 no CI job
built one: every Android job packaged an APK, one ABI at a time. The
``android_bundle`` job now packages ``hello-android`` with ``-f aab`` and no
``--abi``, so both of its ABIs, and points this module at the result.

Two checks, split the same way as the APK ones:

* **content** — the APK content checks, read from the bundle's ``base/``
  module, plus the one setting a bundle carries that an APK carries in its
  manifest: whether the APKs Play generates keep native libraries compressed,
  so the platform extracts them to the real paths kivyforge's load model
  needs;
* **signature** — ``jarsigner -verify``, since a bundle is JAR-signed and
  ``apksigner`` does not apply to it. It spawns a tool, so it needs
  ``skip_missing_toolchain``.

Skips without ``--android-aab`` so a local ``pytest`` run stays green.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.artifact_checks import android_bundle_problems, jarsigner_report_problems
from tests.conftest import skip_missing_toolchain
from tests.platforms.android.test_apk_artifact import _expected_magic

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def aab(pytestconfig) -> Path:
    given = pytestconfig.getoption("--android-aab")
    if not given:
        pytest.skip("no --android-aab given; T3 needs an artifact to inspect")
    path = Path(given)
    if not path.is_file():
        pytest.fail(f"--android-aab {path} does not exist")
    return path


def test_the_bundle_is_internally_consistent(aab, pytestconfig):
    abi = pytestconfig.getoption("--android-abi")
    abis = tuple(a.strip() for a in abi.split(",") if a.strip())
    stripped = pytestconfig.getoption("--android-stripped")
    expected_magic = _expected_magic(aab) if stripped else b""

    problems = android_bundle_problems(
        aab, abis=abis, stripped=stripped, expected_magic=expected_magic
    )
    assert not problems, (
        f"{aab.name} is not the artifact the build promised "
        f"(abis={list(abis)}, strip_source={'on' if stripped else 'off'}):\n  "
        + "\n  ".join(problems)
    )


def _find_jarsigner() -> Path | None:
    """``$JAVA_HOME/bin/jarsigner``, else one on PATH.

    ``JAVA_HOME`` first because that is the JDK Gradle built with; a second
    JDK on PATH could be a different vendor or version.
    """
    exe = "jarsigner.exe" if os.name == "nt" else "jarsigner"
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / exe).is_file():
        return Path(home) / "bin" / exe
    found = shutil.which("jarsigner")
    return Path(found) if found else None


def test_the_bundle_signature_verifies(aab):
    jarsigner = _find_jarsigner()
    if jarsigner is None:
        skip_missing_toolchain("jarsigner", "not in $JAVA_HOME/bin and not on PATH")
    proc = subprocess.run(
        [str(jarsigner), "-verify", str(aab)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    problems = jarsigner_report_problems(proc.returncode, proc.stdout + proc.stderr)
    assert not problems, f"{aab.name}: " + "; ".join(problems)
