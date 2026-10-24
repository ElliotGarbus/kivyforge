"""Native binaries end to end with real ``clang``, ``codesign`` and dyld.

macos-native-binaries-placement-proposal §7 step 2: section 2's helpers and
libraries, compiled, staged through ``stage_native_binaries`` into a bundle,
signed, verified, and run. The hermetic tests prove the link check agrees with
the spikes on synthetic headers; this proves the spikes still hold on the
runner's macOS, and that what the check passes really loads.

The interpreter is a compiled stand-in carrying the bundled CPython's run path
(``@executable_path/../lib``), since fetching the real runtime would make this
job need the network. ``ctypes`` loads happen in the interpreter running the
tests, which is enough for libraries that resolve through ``@loader_path``.
"""

from __future__ import annotations

import hashlib
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kivyforge.lock.wheelruntime.model import (
    LockedNativeBinary,
    PythonRuntime,
    RuntimeArtifact,
    WheelRuntimeLock,
)
from kivyforge.platforms.macos import AppBundleError
from kivyforge.platforms.macos.native_stage import stage_native_binaries
from kivyforge.platforms.macos.signing import sign_bundle_adhoc
from kivyforge.report import diagnostics
from tests.conftest import skip_missing_toolchain

pytestmark = [
    pytest.mark.requires_toolchain,
    pytest.mark.skipif(
        sys.platform != "darwin", reason="Mach-O and dyld are macOS-only"
    ),
]

ARCH = "arm64" if platform.machine() == "arm64" else "x86_64"

_LIB = "int greet(void) { return 42; }\n"
_HELPER = (
    "#include <stdio.h>\nint greet(void);\n"
    'int main(void) { printf("greet=%d\\n", greet()); return 0; }\n'
)
_B = "int b(void) { return 7; }\n"
_A = "int b(void); int a(void) { return b() * 6; }\n"
_MAIN = "int main(void) { return 0; }\n"


def _run(*cmd: str | Path, cwd: Path) -> None:
    subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    for tool in ("clang", "install_name_tool", "codesign"):
        if shutil.which(tool) is None:
            skip_missing_toolchain(tool, "install the Xcode command line tools")
    d = tmp_path_factory.mktemp("native")
    for name, text in {
        "lib.c": _LIB,
        "helper.c": _HELPER,
        "b.c": _B,
        "a.c": _A,
        "main.c": _MAIN,
    }.items():
        (d / name).write_text(text)
    cc = ("clang", "-arch", ARCH)

    _run(
        *cc,
        "-dynamiclib",
        "-install_name",
        "@rpath/libx.dylib",
        "-o",
        "libx.dylib",
        "lib.c",
        cwd=d,
    )
    _run(*cc, "-o", "helperA", "helper.c", "libx.dylib", cwd=d)
    _run(
        "install_name_tool",
        "-change",
        "@rpath/libx.dylib",
        "@executable_path/libx.dylib",
        "helperA",
        cwd=d,
    )
    _run(
        *cc,
        "-o",
        "helperB",
        "helper.c",
        "libx.dylib",
        "-Wl,-rpath,@executable_path",
        cwd=d,
    )
    _run(
        *cc,
        "-o",
        "helperC",
        "helper.c",
        "libx.dylib",
        "-Wl,-rpath,@executable_path/../Frameworks",
        cwd=d,
    )
    _run(*cc, "-o", "helperD", "helper.c", "libx.dylib", cwd=d)
    _run(
        "install_name_tool",
        "-change",
        "@rpath/libx.dylib",
        "@loader_path/libx.dylib",
        "helperD",
        cwd=d,
    )

    _run(
        *cc,
        "-dynamiclib",
        "-install_name",
        "@rpath/libB.dylib",
        "-o",
        "libB.dylib",
        "b.c",
        cwd=d,
    )
    lib = (*cc, "-dynamiclib", "a.c", "libB.dylib")
    _run(*lib, "-install_name", "@rpath/libA1.dylib", "-o", "libA1.dylib", cwd=d)
    _run(
        "install_name_tool",
        "-change",
        "@rpath/libB.dylib",
        "@executable_path/../Frameworks/libB.dylib",
        "libA1.dylib",
        cwd=d,
    )
    _run(
        *lib,
        "-install_name",
        "@rpath/libA2.dylib",
        "-o",
        "libA2.dylib",
        "-Wl,-rpath,@loader_path",
        cwd=d,
    )
    _run(*lib, "-install_name", "@rpath/libA3.dylib", "-o", "libA3.dylib", cwd=d)

    _run(*cc, "-o", "App", "main.c", cwd=d)
    _run(*cc, "-o", "python3", "main.c", "-Wl,-rpath,@executable_path/../lib", cwd=d)
    _run(*cc, "-bundle", "-o", "plugin.so", "lib.c", cwd=d)
    return d


def _app(root: Path) -> Path:
    """A minimal ``.app`` with a launcher and a stand-in interpreter."""
    app = root / "Spike.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    shutil.copy2(root / "src" / "App", contents / "MacOS" / "App")
    python = contents / "Resources" / "python" / "bin"
    python.mkdir(parents=True)
    shutil.copy2(root / "src" / "python3", python / "python3")
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump(
            {
                "CFBundleExecutable": "App",
                "CFBundleIdentifier": "org.example.spike174",
                "CFBundlePackageType": "APPL",
            },
            f,
        )
    return app


def _stage(built: Path, tmp_path: Path, *names: str, notes=None):
    shutil.copytree(built, tmp_path / "src")
    entries = [
        LockedNativeBinary(
            name,
            "1.0",
            hashlib.sha256((tmp_path / "src" / name).read_bytes()).hexdigest(),
            path=f"src/{name}",
        )
        for name in names
    ]
    lock = WheelRuntimeLock(
        platform="macos",
        requires_python=">=3.13",
        packages=(),
        python_runtime=PythonRuntime(
            provider="pbs",
            version="3.13.0",
            artifacts=(RuntimeArtifact(arch=ARCH, url="https://e/a", sha256="c"),),
        ),
        archs=(ARCH,),
        kivyforge_version="0.1.0",
        generated_at="2026-01-01T00:00:00Z",
        lock_inputs_sha256="d" * 64,
        tool_kivyforge_schema_version=1,
        native_binaries=tuple(entries),
    )
    app = _app(tmp_path)
    collected = [] if notes is None else notes
    stage_native_binaries(
        lock,
        app / "Contents",
        target_arch=ARCH,
        project_root=tmp_path,
        echo=lambda _msg: None,
        note=lambda code, msg, ctx=None: collected.append((code, msg, ctx)),
    )
    return app


def test_apples_layout_signs_verifies_and_runs(built, tmp_path):
    app = _stage(built, tmp_path, "helperC", "libx.dylib", "libA2.dylib", "libB.dylib")
    contents = app / "Contents"
    assert (contents / "Helpers" / "helperC").is_file()
    assert (contents / "Frameworks" / "libA2.dylib").is_file()

    sign_bundle_adhoc(app)
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)],
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    # By name, through the PATH the launcher sets.
    env = {**os.environ, "PATH": f"{contents / 'Helpers'}:{os.environ['PATH']}"}
    out = subprocess.run(
        ["helperC"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    assert out.stdout.strip() == "greet=42"

    # From the documented path: Path(sys.prefix).parents[1] / "Frameworks".
    prefix = contents / "Resources" / "python"
    load = (
        "import ctypes, sys; from pathlib import Path; "
        f"frameworks = Path({str(prefix)!r}).parents[1] / 'Frameworks'; "
        "print(ctypes.CDLL(str(frameworks / 'libA2.dylib')).a())"
    )
    out = subprocess.run(
        [sys.executable, "-c", load],
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    assert out.stdout.strip() == "42"


def test_helpers_expecting_a_sibling_are_refused(built, tmp_path):
    with pytest.raises(AppBundleError) as exc:
        _stage(built, tmp_path, "helperA", "helperB", "helperD", "libx.dylib")
    assert exc.value.code == diagnostics.MACOS_NATIVE_LOAD_PATH
    text = str(exc.value)
    for helper in ("helperA", "helperB", "helperD"):
        assert f"Contents/Helpers/{helper} links libx.dylib" in text
    assert not (tmp_path / "Spike.app" / "Contents" / "Helpers").exists()


def test_helpers_really_fail_where_the_check_says(built, tmp_path):
    """The refusal above is dyld's verdict, not just the check's."""
    contents = tmp_path / "Spike.app" / "Contents"
    (contents / "Helpers").mkdir(parents=True)
    (contents / "Frameworks").mkdir()
    shutil.copy2(built / "libx.dylib", contents / "Frameworks")
    for helper in ("helperA", "helperB", "helperC", "helperD"):
        shutil.copy2(built / helper, contents / "Helpers")
    ran = {
        helper: subprocess.run(
            [str(contents / "Helpers" / helper)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        for helper in ("helperA", "helperB", "helperC", "helperD")
    }
    assert ran["helperC"].returncode == 0
    for helper in ("helperA", "helperB", "helperD"):
        assert ran[helper].returncode != 0
        assert "Library not loaded" in ran[helper].stderr


def test_a1_is_refused(built, tmp_path):
    with pytest.raises(AppBundleError) as exc:
        _stage(built, tmp_path, "libA1.dylib", "libB.dylib")
    assert exc.value.code == diagnostics.MACOS_NATIVE_LOAD_PATH
    assert "Python (ctypes)" in str(exc.value)


def test_a3_warns(built, tmp_path):
    notes: list = []
    app = _stage(built, tmp_path, "libA3.dylib", "libB.dylib", notes=notes)
    assert (app / "Contents" / "Frameworks" / "libA3.dylib").is_file()
    ((code, message, _),) = notes
    assert code == diagnostics.MACOS_NATIVE_LOAD_PATH
    assert "Contents/Resources/python/lib/libB.dylib" in message


def test_plugin_is_refused(built, tmp_path):
    with pytest.raises(AppBundleError) as exc:
        _stage(built, tmp_path, "plugin.so")
    assert exc.value.code == diagnostics.MACOS_NATIVE_UNSUPPORTED
    assert "MH_BUNDLE" in str(exc.value)
