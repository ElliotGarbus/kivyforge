"""The Build Python phase removes frameworks no installed extension module needs.

python.org's ``install_python`` turns each ``.so`` it finds into
``Frameworks/<module>.framework`` and never removes one, and Xcode never
removes a file from an incremental product. So a dependency dropped from the
lock left its framework in every later build until ``kivyforge clean``.
``PRUNE_EXTENSION_FRAMEWORKS_SCRIPT`` removes them, keyed on the ``.origin``
back-reference ``install_dylib`` writes into each framework it makes.

The script runs under ``bash`` over a bundle laid out as ``install_dylib``
leaves it. The last tests run the whole phase twice with a stand-in for
``install_python`` that does what python.org's does to the bundle, so the
removal of a package's ``.fwork`` -- by the phase's own rsync -- is the real one.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from kivyforge.platforms.ios import buildsettings

pytestmark = pytest.mark.requires_posix

SIM_FWORK = "pip-deps/pyobjus/pyobjus.cpython-315-iphonesimulator.fwork"
STDLIB_FWORK = (
    "python/lib/python3.15/lib-dynload/_struct.cpython-315-iphonesimulator.fwork"
)


def _run(script: str, *, bundle: Path, project_dir: Path | None = None) -> str:
    env = {
        "PATH": os.environ["PATH"],
        "CODESIGNING_FOLDER_PATH": str(bundle),
        "EFFECTIVE_PLATFORM_NAME": "-iphonesimulator",
    }
    if project_dir is not None:
        env["PROJECT_DIR"] = str(project_dir)
    proc = subprocess.run(
        ["bash", "-c", "set -e\n" + script],
        env=env,
        cwd=project_dir,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"script failed: {proc.stdout}{proc.stderr}")
    return proc.stdout


def _prune(bundle: Path) -> str:
    return _run(buildsettings.PRUNE_EXTENSION_FRAMEWORKS_SCRIPT, bundle=bundle)


def _extension_framework(bundle: Path, module: str, fwork: str) -> Path:
    """A framework as ``install_dylib`` leaves it, with its ``.origin``."""
    framework = bundle / "Frameworks" / f"{module}.framework"
    framework.mkdir(parents=True)
    (framework / module).write_text("binary")
    (framework / "Info.plist").write_text("<plist/>")
    (framework / f"{module}.origin").write_text(fwork + "\n")
    return framework


def _fwork(bundle: Path, rel: str, module: str) -> None:
    path = bundle / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"Frameworks/{module}.framework/{module}\n")


def test_framework_of_a_removed_module_is_removed(tmp_path):
    bundle = tmp_path / "MyApp.app"
    stale = _extension_framework(bundle, "pyobjus.pyobjus", SIM_FWORK)

    out = _prune(bundle)

    assert not stale.exists()
    assert "pyobjus.pyobjus.framework" in out


def test_framework_of_an_installed_module_is_kept(tmp_path):
    bundle = tmp_path / "MyApp.app"
    kept = _extension_framework(bundle, "pyobjus.pyobjus", SIM_FWORK)
    _fwork(bundle, SIM_FWORK, "pyobjus.pyobjus")
    stdlib = _extension_framework(bundle, "_struct", STDLIB_FWORK)
    _fwork(bundle, STDLIB_FWORK, "_struct")

    assert _prune(bundle) == ""

    assert (kept / "pyobjus.pyobjus").is_file()
    assert (stdlib / "_struct").is_file()


def test_frameworks_install_python_did_not_make_are_kept(tmp_path):
    """Python, SDL3, a Swift package's, the user's: no ``.origin`` of ours."""
    bundle = tmp_path / "MyApp.app"
    frameworks = bundle / "Frameworks"
    for name in ("Python", "SDL3"):
        (frameworks / f"{name}.framework").mkdir(parents=True)
        (frameworks / f"{name}.framework" / name).write_text("binary")
    # An .origin under another name, or not naming a placeholder, is not
    # install_dylib's either.
    other = frameworks / "Vendor.framework"
    other.mkdir()
    (other / "Something.origin").write_text("pip-deps/gone.fwork\n")
    unusual = frameworks / "Odd.framework"
    unusual.mkdir()
    (unusual / "Odd.origin").write_text("pip-deps/gone.so\n")

    assert _prune(bundle) == ""

    assert sorted(p.name for p in frameworks.iterdir()) == [
        "Odd.framework",
        "Python.framework",
        "SDL3.framework",
        "Vendor.framework",
    ]


def test_no_frameworks_folder_is_not_an_error(tmp_path):
    bundle = tmp_path / "MyApp.app"
    bundle.mkdir()

    assert _prune(bundle) == ""


def test_a_bundle_path_with_spaces(tmp_path):
    bundle = tmp_path / "My Projects" / "My App.app"
    stale = _extension_framework(bundle, "pyobjus.pyobjus", SIM_FWORK)
    kept = _extension_framework(bundle, "_struct", STDLIB_FWORK)
    _fwork(bundle, STDLIB_FWORK, "_struct")

    _prune(bundle)

    assert not stale.exists()
    assert kept.is_dir()


def test_the_phase_prunes_after_install_python_and_before_metadata():
    script = buildsettings.BUILD_PYTHON_SCRIPT
    prune = script.index(buildsettings.PRUNE_EXTENSION_FRAMEWORKS_SCRIPT)
    assert script.index("install_python Python.xcframework") < prune
    assert prune < script.index(buildsettings.APP_METADATA_SCRIPT)
    assert script not in buildsettings.PREVIOUS_BUILD_PYTHON_SCRIPTS


# --------------------------------------------------------------------------- #
# The whole phase, twice
# --------------------------------------------------------------------------- #

#: Stands in for python.org's ``build/utils.sh``: the same bundle layout as its
#: ``install_dylib`` (framework name, binary, ``.fwork`` and ``.origin``),
#: without the Info.plist template and codesign that need a toolchain. The
#: standard library is left out: it is not what changes when the lock does.
FAKE_UTILS = textwrap.dedent(
    """\
    install_python() {
        shift
        for base in "$@"; do
            find "$CODESIGNING_FOLDER_PATH/$base" -name "*.so" | while read -r so; do
                rel="${so#$CODESIGNING_FOLDER_PATH/}"
                module="$(echo "${rel#$base/}" | cut -d . -f 1 | tr / .)"
                fw="Frameworks/$module.framework"
                mkdir -p "$CODESIGNING_FOLDER_PATH/$fw"
                mv "$so" "$CODESIGNING_FOLDER_PATH/$fw/$module"
                echo "$fw/$module" > "${so%.so}.fwork"
                echo "${rel%.so}.fwork" > "$CODESIGNING_FOLDER_PATH/$fw/$module.origin"
            done
        done
    }
    """
)


def _project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "MyApp-ios"
    utils = project_dir / "Python.xcframework" / "build" / "utils.sh"
    utils.parent.mkdir(parents=True)
    utils.write_text(FAKE_UTILS)
    (project_dir / "pip-deps-simulator").mkdir()
    (project_dir / "pip-deps-simulator.collected").write_text("")
    return project_dir


def _collect(project_dir: Path, *sos: str) -> None:
    """What collect leaves in the slice: a fresh install of the lock."""
    slice_dir = project_dir / "pip-deps-simulator"
    for child in slice_dir.iterdir():
        subprocess.run(["rm", "-rf", str(child)], check=True)
    for so in sos:
        path = slice_dir / so
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("binary")


def _build(project_dir: Path, bundle: Path) -> None:
    (bundle / "app").mkdir(parents=True, exist_ok=True)
    _run(buildsettings.BUILD_PYTHON_SCRIPT, bundle=bundle, project_dir=project_dir)


def _frameworks(bundle: Path) -> list[str]:
    return sorted(p.name for p in (bundle / "Frameworks").iterdir())


class TestRebuildAfterTheLockChanges:
    def test_a_removed_dependency_leaves_no_framework(self, tmp_path):
        project_dir = _project(tmp_path)
        bundle = tmp_path / "DerivedData" / "MyApp.app"
        pyobjus = "pyobjus/pyobjus.cpython-315-iphonesimulator.so"
        kivy = "kivy/_clock.cpython-315-iphonesimulator.so"
        _collect(project_dir, pyobjus, kivy)
        _build(project_dir, bundle)
        assert _frameworks(bundle) == [
            "kivy._clock.framework",
            "pyobjus.pyobjus.framework",
        ]

        _collect(project_dir, kivy)
        _build(project_dir, bundle)

        assert _frameworks(bundle) == ["kivy._clock.framework"]
        assert (bundle / "Frameworks/kivy._clock.framework/kivy._clock").is_file()
        assert not (bundle / "pip-deps" / "pyobjus").exists()

    def test_removing_the_last_dependency_empties_frameworks(self, tmp_path):
        project_dir = _project(tmp_path)
        bundle = tmp_path / "DerivedData" / "MyApp.app"
        _collect(project_dir, "pyobjus/pyobjus.cpython-315-iphonesimulator.so")
        _build(project_dir, bundle)

        _collect(project_dir)
        _build(project_dir, bundle)

        assert _frameworks(bundle) == []
