"""T3: assert a *built* AppImage/AppDir is the artifact the build promised.

The Linux counterpart of ``test_apk_artifact.py``, and the same division of
labour: the checks themselves are hermetic and unit-tested in
``tests/test_artifact_checks.py``; this module is only the wiring that points
them at a real file.

``--linux-appimage`` takes the distributable and extracts it, so the thing under
inspection is what a user would actually download. ``--linux-appdir`` takes the
tree directly (``kivyforge package -f folder``) for the case where extraction is
not wanted. Extraction uses ``--appimage-extract``, which unpacks the appended
squashfs without mounting anything, so no FUSE and no ``/dev/fuse`` — the two
things a container runner usually lacks.

Skips without one of those options so a local `pytest` run stays green.
"""

from __future__ import annotations

import importlib.util
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from tests.artifact_checks import (
    linux_appdir_problems,
    linux_appimage_file_problems,
    shipped_python_tags_appdir,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def artifact(pytestconfig, tmp_path_factory) -> tuple[Path, Path | None]:
    """``(appdir, appimage_or_None)`` — the tree to check, and the file it came from."""
    image = pytestconfig.getoption("--linux-appimage")
    folder = pytestconfig.getoption("--linux-appdir")
    if image and folder:
        pytest.fail("pass --linux-appimage or --linux-appdir, not both")
    if folder:
        path = Path(folder)
        if not path.is_dir():
            pytest.fail(f"--linux-appdir {path} is not a directory")
        return path, None
    if not image:
        pytest.skip(
            "no --linux-appimage/--linux-appdir given; T3 needs an artifact to inspect"
        )

    appimage = Path(image).resolve()
    if not appimage.is_file():
        pytest.fail(f"--linux-appimage {appimage} does not exist")

    into = tmp_path_factory.mktemp("appimage")
    result = subprocess.run(
        [str(appimage), "--appimage-extract"],
        cwd=into,
        capture_output=True,
        text=True,
    )
    extracted = into / "squashfs-root"
    if result.returncode != 0 or not extracted.is_dir():
        pytest.fail(
            f"could not extract {appimage.name} (exit {result.returncode}). "
            "It must be executable; --appimage-extract itself needs no FUSE.\n"
            f"{result.stderr.strip()}"
        )
    return extracted, appimage


def _expected_magic(appdir: Path) -> bytes:
    """The ``.pyc`` header the runtime *this AppDir ships* will accept.

    Asked of that runtime directly, which the Android driver cannot do — an APK
    is cross-built and its ``libpython`` will not execute on the runner, so
    there the magic comes from the running interpreter and the job has to be
    pinned to a matching minor. A desktop AppDir ships a working interpreter for
    the host arch, so the anchor is exact and the runner's own Python is
    irrelevant: dice-roller ships 3.13 (magic 3571) and is routinely checked by
    a suite running under 3.14 (magic 3627).

    Falling back to the running interpreter only matters for a cross-arch build
    (aarch64 on x86_64, roadmap item 4), and then it fails naming the runner
    rather than blaming the artifact.
    """
    tags = shipped_python_tags_appdir(appdir)
    if len(tags) != 1:
        pytest.fail(
            f"expected exactly one CPython runtime in {appdir.name}, found {tags}; "
            "cannot tell which .pyc magic to require"
        )

    staged = appdir / "usr" / "python" / "bin" / f"python{tags[0]}"
    if staged.is_file():
        probe = subprocess.run(
            [
                str(staged),
                "-c",
                "import importlib.util,sys;"
                "sys.stdout.buffer.write(importlib.util.MAGIC_NUMBER)",
            ],
            capture_output=True,
        )
        if probe.returncode == 0 and len(probe.stdout) == 4:
            return probe.stdout

    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if tags[0] != running:
        pytest.fail(
            f"{appdir.name} ships CPython {tags[0]}, whose staged interpreter "
            f"will not run here, and this suite runs under {running} — so the "
            f".pyc magic that runtime accepts is unknowable. Run the T3 job on a "
            f"host that can execute the artifact, or under CPython {tags[0]}."
        )
    return importlib.util.MAGIC_NUMBER


def test_the_appdir_is_internally_consistent(artifact, pytestconfig):
    appdir, _ = artifact
    arch = pytestconfig.getoption("--linux-arch")
    stripped = pytestconfig.getoption("--linux-stripped")

    # The runtime only has to be interrogated when there is bytecode to judge;
    # an unstripped payload ships source, so its shape needs no magic at all.
    expected_magic = _expected_magic(appdir) if stripped else b""

    problems = linux_appdir_problems(
        appdir,
        arch=arch,
        stripped=stripped,
        expected_magic=expected_magic,
    )
    assert not problems, (
        f"{appdir.name} is not the artifact the build promised "
        f"(arch={arch}, strip_source={'on' if stripped else 'off'}):\n  "
        + "\n  ".join(problems)
    )


def test_the_appimage_container_is_well_formed(artifact, pytestconfig):
    """Covers appimagetool's own output, which the extracted tree cannot show."""
    _, appimage = artifact
    if appimage is None:
        pytest.skip("--linux-appdir given; there is no .AppImage to inspect")
    arch = pytestconfig.getoption("--linux-arch")

    problems = linux_appimage_file_problems(appimage, arch=arch)
    assert not problems, (
        f"{appimage.name} is not a well-formed AppImage (arch={arch}):\n  "
        + "\n  ".join(problems)
    )


def test_the_expected_magic_came_from_the_artifact(artifact, pytestconfig):
    """Guards the anchoring itself: the magic must not be the runner's by default.

    Getting this backwards is how a checker ends up blaming the artifact for a
    runner mismatch, so it is asserted rather than left to code review.
    """
    appdir, _ = artifact
    if not pytestconfig.getoption("--linux-stripped"):
        pytest.skip("nothing is compiled in an unstripped build")

    tags = shipped_python_tags_appdir(appdir)
    magic = _expected_magic(appdir)
    assert len(magic) == 4, f"unreadable .pyc magic {magic!r}"
    if tags[0] != f"{sys.version_info.major}.{sys.version_info.minor}":
        assert magic != importlib.util.MAGIC_NUMBER, (
            f"the AppDir ships CPython {tags[0]} but the expected magic "
            f"{struct.unpack('<H', magic[:2])[0]} is this runner's — the check "
            "is anchored to the wrong interpreter"
        )
