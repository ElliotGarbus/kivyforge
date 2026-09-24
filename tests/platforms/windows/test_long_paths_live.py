"""A built onedir bundle vs. MAX_PATH with long paths **off** (test-matrix §5.6).

``LongPathsEnabled`` is off on a default Windows install, which is what most
users run. The dev box and (it turns out) CI runners have it on, so the
failure had never been reproduced. The ``windows_onedir`` job switches it off
on its disposable runner and points this module at the bundle it just packaged
via ``--windows-long-paths-off-bundle``. Without the option everything skips.

The bundle is moved (a rename, so instant) into folders of chosen lengths, and
its own ``python.exe`` is asked to open the deepest file and import the deepest
module:

* at exactly the headroom kivyforge reports (:func:`folder_headroom`), both
  must work, so the package-time warning never over-promises;
* one character past it, opening the deepest file must fail, so the number is
  not needlessly conservative either.

The largest folder at which the deepest *import* still works is found by
bisection and printed, since that is the figure a user actually hits.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from kivyforge.platforms.windows.pathdepth import (
    MAX_PATH_CHARS,
    deepest_relative_path,
    folder_headroom,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_windows]


@pytest.fixture(scope="module")
def bundle(pytestconfig) -> Path:
    given = pytestconfig.getoption("--windows-long-paths-off-bundle")
    if not given:
        pytest.skip("no --windows-long-paths-off-bundle given; needs a prepared host")
    path = Path(given).resolve()
    if not (path / "python" / "python.exe").is_file():
        pytest.fail(f"{path} is not a onedir bundle (no python\\python.exe)")
    return path


def _registry_long_paths() -> int | None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            return int(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except OSError:
        return None


@pytest.fixture(scope="module")
def base() -> Iterator[Path]:
    # A short base so the padding, not the base, decides the folder length.
    root = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / "lp"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    yield root
    shutil.rmtree("\\\\?\\" + str(root), ignore_errors=True)


def _python_can_open(path: str) -> bool:
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; open(sys.argv[1], 'rb').close()", path],
        capture_output=True,
    )
    return proc.returncode == 0


def test_long_paths_are_really_off(bundle, base):
    # `bundle` only for its skip: without the option there is nothing to test.
    """Precondition for everything below; fails rather than skips.

    A registry value can be set without taking effect for the processes that
    matter, so this checks both the value and the behaviour: a file created
    through the ``\\\\?\\`` prefix (which bypasses MAX_PATH) must be
    unreachable through an ordinary path from a fresh process.
    """
    assert _registry_long_paths() == 0, (
        f"LongPathsEnabled is {_registry_long_paths()!r}, not 0; the job must "
        "switch it off before this step"
    )
    deep = base / ("q" * 200) / ("r" * 80)
    assert len(str(deep)) > MAX_PATH_CHARS
    os.makedirs("\\\\?\\" + str(deep.parent), exist_ok=True)
    with open("\\\\?\\" + str(deep), "wb") as f:
        f.write(b"x")
    assert not _python_can_open(str(deep)), (
        "a fresh process opened a path longer than MAX_PATH, so long paths are "
        "still in effect and the results below would prove nothing"
    )


def _deepest_module(bundle: Path) -> tuple[str, str]:
    """``(module, relative file)`` for the deepest importable module.

    Deepest first; the first one that imports at the bundle's current (short
    enough) location wins, so a module that fails to import for unrelated
    reasons is skipped rather than blamed on path length.
    """
    site = bundle / "python" / "Lib" / "site-packages"
    candidates = []
    for dirpath, _dirs, files in os.walk(site):
        if "__pycache__" in Path(dirpath).parts:
            continue
        for name in files:
            if name.endswith((".py", ".pyc")):
                full = Path(dirpath) / name
                candidates.append(full)
    candidates.sort(key=lambda p: len(str(p.relative_to(bundle))), reverse=True)
    for full in candidates[:25]:
        parts = list(full.relative_to(site).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        if _bundle_python(bundle, f"import {module}").returncode == 0:
            return module, str(full.relative_to(bundle))
    pytest.fail("none of the 25 deepest modules imports even from a short folder")


def _bundle_python(bundle: Path, code: str, *args: str):
    argv = [str(bundle / "python" / "python.exe"), "-c", code, *args]
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except OSError as exc:
        # Past ~240 characters of folder, python.exe's own path exceeds
        # MAX_PATH and Windows will not start it at all (WinError 206), even
        # with long paths on. That is a failure to import, not a test error.
        return subprocess.CompletedProcess(argv, 206, "", str(exc))


def _move_to(current: Path, base: Path, folder_len: int) -> Path:
    """Rename *current* into a folder whose full path is *folder_len* long."""
    pad = folder_len - len(str(base)) - 1 - len(current.name) - 1
    assert pad >= 1, f"folder length {folder_len} is too short for this base"
    target = base / ("p" * pad) / current.name
    assert len(str(target)) == folder_len
    target.parent.mkdir(exist_ok=True)
    os.rename(current, target)
    return target


def test_the_reported_headroom_is_exact(bundle, base):
    deepest = deepest_relative_path(bundle)
    headroom = folder_headroom(deepest)
    module, module_rel = _deepest_module(bundle)
    print(f"\ndeepest {len(deepest)}: {deepest}")
    print(f"headroom (predicted max folder length): {headroom}")
    print(f"deepest importable module {len(module_rel)}: {module}")

    original = bundle
    here = bundle
    try:
        here = _move_to(here, base, headroom)
        at = _bundle_python(
            here, "import sys; open(sys.argv[1], 'rb').close()", str(here / deepest)
        )
        imp = _bundle_python(here, f"import {module}")
        print(
            f"at {headroom}: open deepest rc={at.returncode}, import rc={imp.returncode}"
        )
        assert at.returncode == 0, (
            f"deepest file unreadable at the headroom:\n{at.stderr}"
        )
        assert imp.returncode == 0, (
            f"deepest import failed at the headroom:\n{imp.stderr}"
        )

        here = _move_to(here, base, headroom + 1)
        past = _bundle_python(
            here, "import sys; open(sys.argv[1], 'rb').close()", str(here / deepest)
        )
        print(
            f"at {headroom + 1}: open deepest rc={past.returncode}: "
            f"{past.stderr.strip().splitlines()[-1] if past.stderr else ''}"
        )
        assert past.returncode != 0, (
            "the deepest file was still readable one character past the headroom; "
            "the reported number is conservative, or long paths are not off"
        )

        # Informational: the longest folder the deepest *import* survives.
        # Capped below CreateDirectory's 248-character limit on the folder
        # itself, which is not the limit being measured.
        lo, hi = headroom, 240
        while lo < hi:
            mid = (lo + hi + 1) // 2
            here = _move_to(here, base, mid)
            if _bundle_python(here, f"import {module}").returncode == 0:
                lo = mid
            else:
                hi = mid - 1
        print(
            f"deepest import works up to a folder of {lo} characters "
            f"(module file {len(module_rel)} chars; {lo + 1 + len(module_rel)} total)"
        )
    finally:
        if here != original:
            os.rename(here, original)
