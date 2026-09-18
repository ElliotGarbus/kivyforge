"""T3: assert a *built* AppImage/AppDir is the artifact the build promised.

The Linux counterpart of ``test_apk_artifact.py``, and the same division of
labour: the checks themselves are hermetic and unit-tested in
``tests/test_artifact_checks.py``; this module is only the wiring that points
them at a real file.

``--linux-appimage`` takes the distributable and extracts it, so the thing under
inspection is what a user would actually download. ``--linux-appdir`` takes the
tree directly (``kivyforge package -f folder``) for the case where extraction is
not wanted. Extraction prefers ``--appimage-extract`` (squashfs, no FUSE) and
falls back to ``unsquashfs -o <offset>`` when the type2 runtime is a foreign
arch and cannot exec on the runner — the aarch64-on-x86_64 case.

Skips without one of those options so a local `pytest` run stays green.
"""

from __future__ import annotations

import importlib.util
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from kivyforge.bundle.pycompile import find_interpreter
from tests.artifact_checks import (
    linux_appdir_problems,
    linux_appimage_file_problems,
    shipped_python_tags_appdir,
)

pytestmark = pytest.mark.integration

_SQUASHFS_MAGIC = b"hsqs"


def _squashfs_offset(appimage: Path) -> int | None:
    """Byte offset of the squashfs appended to a type-2 AppImage, or None."""
    with appimage.open("rb") as fh:
        data = fh.read()
    idx = data.find(_SQUASHFS_MAGIC)
    return idx if idx >= 0 else None


def _extract_appimage(appimage: Path, into: Path) -> Path:
    """Unpack *appimage* into *into*/squashfs-root without needing FUSE.

    Native-arch images exec ``--appimage-extract``. A cross-built image is a
    foreign ELF, so that raises ``OSError``; ``unsquashfs`` then reads the
    appended filesystem from the offset of the ``hsqs`` magic.
    """
    extracted = into / "squashfs-root"
    exec_error: OSError | None = None
    result: subprocess.CompletedProcess[str] | None = None
    try:
        result = subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=into,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        exec_error = exc
    else:
        if result.returncode == 0 and extracted.is_dir():
            return extracted

    offset = _squashfs_offset(appimage)
    unsquashfs = shutil.which("unsquashfs")
    squash_err = ""
    if offset is not None and unsquashfs is not None:
        sq = subprocess.run(
            [
                unsquashfs,
                "-o",
                str(offset),
                "-d",
                str(extracted),
                str(appimage),
            ],
            capture_output=True,
            text=True,
        )
        if sq.returncode == 0 and extracted.is_dir():
            return extracted
        squash_err = sq.stderr.strip() or sq.stdout.strip() or f"exit {sq.returncode}"
    elif offset is None:
        squash_err = "no squashfs magic (hsqs) in the file"
    else:
        squash_err = "unsquashfs is not on PATH"

    if exec_error is not None:
        detail = str(exec_error)
    elif result is not None:
        detail = f"exit {result.returncode}\n{result.stderr.strip()}"
    else:
        detail = "unknown extract failure"
    pytest.fail(
        f"could not extract {appimage.name} ({detail}). "
        "Native path: the file must be executable; --appimage-extract needs no "
        f"FUSE. Cross-arch fallback: {squash_err}"
    )


def _probe_magic(argv: list[str]) -> bytes | None:
    """First four bytes of ``importlib.util.MAGIC_NUMBER`` from *argv*, or None."""
    try:
        probe = subprocess.run(
            [
                *argv,
                "-c",
                "import importlib.util,sys;"
                "sys.stdout.buffer.write(importlib.util.MAGIC_NUMBER)",
            ],
            capture_output=True,
        )
    except OSError:
        return None
    if probe.returncode == 0 and len(probe.stdout) == 4:
        return probe.stdout
    return None


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
    return _extract_appimage(appimage, into), appimage


def _expected_magic(appdir: Path) -> bytes:
    """The ``.pyc`` header the runtime *this AppDir ships* will accept.

    Asked of that runtime directly when it can run here. An APK cannot do that
    (its ``libpython`` is always foreign), and neither can a cross-built Linux
    AppDir: the staged aarch64 interpreter will not exec on x86_64. Magic is
    keyed to CPython minor, not arch, so the same fallback the byte-compile
    ladder uses — a final host CPython of that minor via :func:`find_interpreter`
    — is an exact answer. Only if that is missing too do we fail, naming the
    runner rather than blaming the artifact.
    """
    tags = shipped_python_tags_appdir(appdir)
    if len(tags) != 1:
        pytest.fail(
            f"expected exactly one CPython runtime in {appdir.name}, found {tags}; "
            "cannot tell which .pyc magic to require"
        )

    staged = appdir / "usr" / "python" / "bin" / f"python{tags[0]}"
    if staged.is_file():
        magic = _probe_magic([str(staged)])
        if magic is not None:
            return magic

    found = find_interpreter(tags[0])
    if found is not None:
        argv = [sys.executable] if found == () else list(found)
        magic = _probe_magic(argv)
        if magic is not None:
            return magic

    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    pytest.fail(
        f"{appdir.name} ships CPython {tags[0]}, whose staged interpreter "
        f"will not run here, and no final CPython {tags[0]} is on PATH "
        f"(this suite runs under {running}) — so the .pyc magic that runtime "
        "accepts is unknowable. Run the T3 job on a host that can execute the "
        f"artifact, or install CPython {tags[0]}."
    )


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
