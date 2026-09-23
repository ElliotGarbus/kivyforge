"""T3: assert a *signed* Windows binary's Authenticode signature verifies.

test-matrix.md §5.1's signature box asked for ``signtool verify /pa`` "on a
*built app* rather than on the vendored launcher". Both halves live here,
because they are the same verification pointed at different files:

* ``test_a_signed_binary_verifies`` takes any signed PE via
  ``--windows-signed-exe``. The ``windows_signing`` CI job already signs a
  copy of the vendored launcher through kivyforge's own ``SigntoolSigner``
  and then ran a bare ``signtool verify /pa``, checking only the exit code;
  pointing that step here instead adds the timestamp and verification-count
  assertions and gets the report parser itself under CI.
* ``test_the_bundled_launcher_is_signed`` takes a built onedir bundle via
  ``--windows-onedir`` + ``--windows-project`` and verifies the launcher
  *inside it*. `kivyforge package` signs exactly one file
  (``_sign_launcher``: the launcher exe in the dist copy), so that file is
  the whole of what there is to verify.

  **This one is still local-only, but not for the reason it used to be.**
  ``windows_onedir`` has built a Windows bundle on every push since
  2026-09-22, and it *does* verify that bundle's launcher — through the
  first test above, after signing it with a throwaway cert. What it cannot
  exercise is this path, because this path requires a project that
  configures ``[tool.kivy.windows.signing]``, and no fixture does: a per-run
  thumbprint in a fixture's ``pyproject.toml`` would change its
  ``pyproject_sha256`` and break the same job's ``lock --check``
  (test-matrix.md §5.3). So this covers a real project that signs through
  ``package`` itself, which CI has no way to be.

Both skip without their options so a local `pytest` run stays green. The
report parsing is hermetic and unit-tested in ``tests/test_artifact_checks.py``
against real signtool output; only the spawn is here.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kivyforge.config.loader import load_config
from kivyforge.platforms.windows.bundle import launcher_name
from tests.artifact_checks import signtool_report_problems
from tests.conftest import skip_missing_toolchain

pytestmark = pytest.mark.integration

# Newest SDK build directory first: signtool is installed per Windows SDK
# version, and a machine commonly has several.
_SDK_BIN = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")


def _find_signtool() -> Path | None:
    """``signtool`` from PATH, else the newest one in the Windows SDK.

    PATH first because that is what ``SigntoolSigner.sign`` itself resolves
    (via ``shutil.which``), and the ``windows_signing`` job puts it there
    deliberately — looking in the SDK first could verify with a different
    signtool than the one that signed.
    """
    found = shutil.which("signtool")
    if found:
        return Path(found)
    if not _SDK_BIN.is_dir():
        return None
    for version_dir in sorted(
        (d for d in _SDK_BIN.glob("10.*") if d.is_dir()), reverse=True
    ):
        candidate = version_dir / "x64" / "signtool.exe"
        if candidate.is_file():
            return candidate
    return None


def _verify(path: Path) -> None:
    """Run ``signtool verify /pa /v`` on *path* and assert it passes."""
    if sys.platform != "win32":
        pytest.skip("signtool is Windows-only")
    signtool = _find_signtool()
    if signtool is None:
        skip_missing_toolchain(
            "signtool",
            f"not on PATH and not under {_SDK_BIN}; it ships with the Windows SDK",
        )

    proc = subprocess.run(
        # /pa applies the Authenticode policy (a real trust-chain check, not
        # just "is a signature present"); /v is what prints the timestamp line
        # and the verification counts the parser reads.
        [str(signtool), "verify", "/pa", "/v", str(path)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    report = proc.stdout + proc.stderr
    problems = signtool_report_problems(report)
    assert not problems, (
        f"{path.name} does not have a valid Authenticode signature "
        f"(signtool exit {proc.returncode}):\n  " + "\n  ".join(problems)
    )


def test_a_signed_binary_verifies(pytestconfig):
    given = pytestconfig.getoption("--windows-signed-exe")
    if not given:
        pytest.skip("no --windows-signed-exe given; T3 needs a signed file")
    path = Path(given)
    if not path.is_file():
        pytest.fail(f"--windows-signed-exe {path} does not exist")
    _verify(path)


def test_the_bundled_launcher_is_signed(pytestconfig):
    """The built-app half: verify the launcher inside a real onedir bundle.

    Fails rather than skips when the project configures no signing. An
    unsigned bundle is a legitimate build — it is the v1 default — but it is
    not something this test can be pointed at, and reporting "passed" for it
    would be the silent-skip failure again.
    """
    bundle = pytestconfig.getoption("--windows-onedir")
    project = pytestconfig.getoption("--windows-project")
    if not bundle or not project:
        pytest.skip(
            "needs --windows-onedir and --windows-project; the launcher's "
            "filename comes from the project's config"
        )
    config = load_config(
        Path(project) / "pyproject.toml", require_ios=False, require_windows=True
    )
    if not config.windows_required.signing.configured:
        pytest.fail(
            f"--windows-project {project} configures no "
            "[tool.kivy.windows.signing].thumbprint, so its launcher is "
            "unsigned by design and there is no signature to verify"
        )
    launcher = Path(bundle) / launcher_name(config)
    if not launcher.is_file():
        pytest.fail(f"{launcher} does not exist in the bundle")
    _verify(launcher)
