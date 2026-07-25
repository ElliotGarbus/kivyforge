"""``kivyforge run --smoke`` — the contract smoke test (android/06 §--smoke).

Drives the generated instrumented test via Gradle's own connected-test path
(``connectedDebugAndroidTest`` / ``connectedReleaseAndroidTest``), which
validates the two load-bearing runtime mechanisms — the extension-module
finder and the pyjnius ``invoke0`` glue — on a real device/emulator with no
app-specific test code. Non-zero exit on any failure; it is the mechanism that
promotes a compatibility-matrix row to Validated (android/08).
"""

from __future__ import annotations

from pathlib import Path

from .gradlew import GradleError, run_gradle


class SmokeError(Exception):
    pass


def run_smoke(project_dir: Path, *, release: bool = False) -> None:
    """Run the generated contract test; raise ``SmokeError`` on failure.

    A device/emulator must already be attached (Gradle's connected-test task
    selects it). ``release`` targets the release variant so the probe also
    exercises byte-compilation, stripping, and R8 under a test signing config.
    """
    task = (
        "connectedReleaseAndroidTest"
        if release
        else "connectedDebugAndroidTest"
    )
    try:
        run_gradle(project_dir, [task])
    except GradleError as exc:
        raise SmokeError(
            f"the contract smoke test failed ({task}).\n"
            "  This means a load-bearing runtime mechanism broke on-device — "
            "the extension-module finder or the pyjnius invoke0 glue.\n"
            f"  Gradle output is above; the test report is under "
            f"{project_dir / 'app' / 'build' / 'reports' / 'androidTests'}.\n"
            f"  {exc}"
        ) from exc
