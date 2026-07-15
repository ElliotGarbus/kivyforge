"""Deterministically build (and vendor / verify) the Windows launcher .exe.

The launcher is **compiled once in CI, never on user or dev machines** — the
onedir bundle ships the prebuilt, vendored binary. This script is the source of
that binary and its reproducibility gate:

    python -m kivyforge.platforms.windows.launcher.build_launcher build
        Compile launcher.c and (over)write the vendored binary + its SHA-256 in
        the manifest.  Run locally when the C source changes.

    python -m kivyforge.platforms.windows.launcher.build_launcher verify
        Recompile to a temp dir and byte-compare against the vendored binary,
        failing on any drift.  This is the CI reproducibility check.

Determinism: MSVC ``/Brepro`` on both the compile and link steps replaces the
PE timestamp with a content hash (no wall-clock time), and the linker
``/RELEASE`` writes a deterministic checksum.  kivyforge's launcher **appends
nothing** to the binary, so there is no zip/timestamp tail to non-determinize it
(unlike distlib).  Byte-identity holds for a *fixed MSVC toolset*: the PE "rich
header" encodes the compiler build, so CI must pin the same Visual Studio
toolset that produced the vendored binary (the workflow does).

Windows-only (needs ``cl``/``link`` from Visual Studio Build Tools).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "launcher.c"
VENDOR_DIR = HERE.parent / "vendor"
LAUNCHER_NAME = "launcher-amd64.exe"
VENDORED_LAUNCHER = VENDOR_DIR / LAUNCHER_NAME
MANIFEST = VENDOR_DIR / "SHA256SUMS"
# The MSVC toolset (major.minor) that produced the vendored binary. Byte-identity
# holds only for a fixed toolset (the PE "rich header" encodes it), so build and
# the CI verify both pin this; CI selects it via vcvarsall -vcvars_ver.
TOOLSET_FILE = VENDOR_DIR / "TOOLSET.txt"

# Deterministic compile/link flags. Keep this list in lockstep with any change
# that would alter the emitted bytes (both here and in the CI workflow).
_CL_FLAGS = ["/nologo", "/c", "/O1", "/Brepro", "/utf-8", "/DUNICODE", "/D_UNICODE"]
_LINK_LIBS = ["kernel32.lib", "shell32.lib"]


class LauncherBuildError(Exception):
    """The launcher could not be compiled or failed its reproducibility check."""


def pinned_toolset() -> str | None:
    """The pinned MSVC toolset (``major.minor``), or ``None`` if unrecorded."""
    if TOOLSET_FILE.is_file():
        text = TOOLSET_FILE.read_text(encoding="utf-8").strip()
        return text or None
    return None


def _vcvars_env(arch: str = "x64", *, vcvars_ver: str | None = None) -> dict[str, str]:
    """Return the environment after loading the Visual Studio dev vars for *arch*.

    Locates the toolset with ``vswhere`` and runs ``vcvarsall.bat``, capturing
    the resulting environment so ``cl``/``link`` resolve without the caller
    being inside a Developer Command Prompt. ``vcvars_ver`` pins the toolset
    (e.g. ``14.38``) for reproducibility.
    """
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = (
        Path(program_files_x86)
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not vswhere.is_file():
        raise LauncherBuildError(
            f"vswhere not found at {vswhere}; install Visual Studio (with the "
            "C++ build tools) to build the launcher."
        )
    proc = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
    )
    install = proc.stdout.strip().splitlines()
    if not install:
        raise LauncherBuildError(
            "no Visual Studio install with the C++ x64 toolset was found "
            "(vswhere returned nothing)."
        )
    vcvarsall = Path(install[0]) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    if not vcvarsall.is_file():
        raise LauncherBuildError(f"vcvarsall.bat not found at {vcvarsall}.")

    # Run vcvarsall then `set`, and parse the exported environment back out.
    # A temp batch file avoids the nested-quote mangling that breaks passing the
    # whole compound command (with a quoted, space-containing path) as one arg.
    marker = "__KIVYFORGE_ENV__"
    ver_arg = f" -vcvars_ver={vcvars_ver}" if vcvars_ver else ""
    with tempfile.TemporaryDirectory(prefix="kivy-vcvars-") as tmp:
        bat = Path(tmp) / "env.bat"
        bat.write_text(
            f'@echo off\r\ncall "{vcvarsall}" {arch}{ver_arg} >nul\r\n'
            f"echo {marker}\r\nset\r\n",
            encoding="utf-8",
        )
        result = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True)
    if result.returncode != 0 or marker not in result.stdout:
        raise LauncherBuildError(
            f"failed to initialize the MSVC environment via {vcvarsall}:\n"
            f"{result.stdout}\n{result.stderr}"
        )
    env: dict[str, str] = {}
    seen_marker = False
    for line in result.stdout.splitlines():
        if not seen_marker:
            if line.strip() == marker:
                seen_marker = True
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            # Uppercase keys so PATH is unambiguous when merged over os.environ
            # (cmd's `set` prints `Path=...`, os.environ has `PATH=...`).
            env[key.upper()] = value
    return env


def compile_c_source(
    source: Path,
    dest: Path,
    *,
    subsystem: str = "WINDOWS",
    extra_libs: tuple[str, ...] = (),
    arch: str = "x64",
    vcvars_ver: str | None = None,
) -> Path:
    """Deterministically compile a single C *source* to *dest* with MSVC.

    Shared by the launcher build and the launcher end-to-end test (which builds
    a tiny console stub standing in for ``python.exe``). ``subsystem`` links
    ``/SUBSYSTEM:<subsystem>``; ``extra_libs`` appends import libraries;
    ``vcvars_ver`` pins the MSVC toolset for byte-reproducibility.
    """
    if sys.platform != "win32":
        raise LauncherBuildError(
            "C sources can only be compiled on Windows (needs MSVC)."
        )
    if not source.is_file():
        raise LauncherBuildError(f"C source missing: {source}")
    env = {k.upper(): v for k, v in os.environ.items()} | _vcvars_env(
        arch, vcvars_ver=vcvars_ver
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kivy-cc-") as tmp:
        tmpdir = Path(tmp)
        obj = tmpdir / (source.stem + ".obj")
        out = tmpdir / dest.name
        cl_exe = _which("cl", env)
        link_exe = _which("link", env)
        cl = [cl_exe, *_CL_FLAGS, f"/Fo{obj}", str(source)]
        _run(cl, cwd=tmpdir, env=env, step="compile")
        link_flags = ["/nologo", "/Brepro", "/RELEASE", f"/SUBSYSTEM:{subsystem}"]
        link = [
            link_exe,
            *link_flags,
            f"/OUT:{out}",
            str(obj),
            *_LINK_LIBS,
            *extra_libs,
        ]
        _run(link, cwd=tmpdir, env=env, step="link")
        if not out.is_file():
            raise LauncherBuildError("link produced no output binary.")
        shutil.copy2(out, dest)
    return dest


def compile_launcher(
    dest: Path, *, arch: str = "x64", vcvars_ver: str | None = None
) -> Path:
    """Compile ``launcher.c`` to *dest* deterministically. Returns *dest*."""
    return compile_c_source(
        SOURCE, dest, subsystem="WINDOWS", arch=arch, vcvars_ver=vcvars_ver
    )


def _which(tool: str, env: dict[str, str]) -> str:
    """Resolve *tool* to an absolute path using the loaded MSVC env's PATH.

    Windows' ``CreateProcess`` searches the *parent* process PATH, not the
    child ``env`` we pass to ``subprocess`` — so ``cl``/``link`` must be resolved
    against the vcvars PATH ourselves.
    """
    found = shutil.which(tool, path=env.get("PATH", ""))
    if found is None:
        raise LauncherBuildError(
            f"{tool} not found on the MSVC toolset PATH; the Visual Studio C++ "
            "build tools may be incomplete."
        )
    return found


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str], step: str) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise LauncherBuildError(
            f"launcher {step} step failed (exit {proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _read_manifest() -> dict[str, str]:
    if not MANIFEST.is_file():
        return {}
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if digest and name:
            entries[name.strip()] = digest.strip()
    return entries


def _write_manifest(entries: dict[str, str]) -> None:
    lines = [
        "# SHA-256 of vendored Windows binaries (kivyforge).",
        "# Regenerate the launcher with: python -m "
        "kivyforge.platforms.windows.launcher.build_launcher build",
    ]
    for name in sorted(entries):
        lines.append(f"{entries[name]}  {name}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def do_build() -> int:
    pin = pinned_toolset()
    # Resolve the actual toolset and record major.minor so the CI verify can pin
    # the same one. When already pinned, honor the pin.
    env = {k.upper(): v for k, v in os.environ.items()} | _vcvars_env(vcvars_ver=pin)
    tools_version = env.get("VCTOOLSVERSION", "")
    major_minor = ".".join(tools_version.split(".")[:2]) if tools_version else ""
    if major_minor:
        TOOLSET_FILE.write_text(major_minor + "\n", encoding="utf-8")
    compile_launcher(VENDORED_LAUNCHER, vcvars_ver=pin or major_minor or None)
    digest = sha256_of(VENDORED_LAUNCHER)
    entries = _read_manifest()
    entries[LAUNCHER_NAME] = digest
    _write_manifest(entries)
    print(f"built {VENDORED_LAUNCHER} ({digest}); toolset {major_minor or 'latest'}")
    return 0


def do_verify() -> int:
    if not VENDORED_LAUNCHER.is_file():
        raise LauncherBuildError(
            f"vendored launcher missing: {VENDORED_LAUNCHER}. Run the `build` "
            "subcommand to produce it."
        )
    vendored = VENDORED_LAUNCHER.read_bytes()
    pin = pinned_toolset()
    with tempfile.TemporaryDirectory(prefix="kivy-launcher-verify-") as tmp:
        rebuilt_path = Path(tmp) / LAUNCHER_NAME
        compile_launcher(rebuilt_path, vcvars_ver=pin)
        rebuilt = rebuilt_path.read_bytes()
    if rebuilt != vendored:
        raise LauncherBuildError(
            "the freshly compiled launcher does not byte-match the vendored "
            f"binary ({VENDORED_LAUNCHER}).\n"
            f"  vendored: {len(vendored)} bytes, sha256={hashlib.sha256(vendored).hexdigest()}\n"
            f"  rebuilt:  {len(rebuilt)} bytes, sha256={hashlib.sha256(rebuilt).hexdigest()}\n"
            "  Either the C source changed without re-vendoring (run `build`), "
            "or the MSVC toolset differs from the one that produced the vendored "
            "binary (pin the same Visual Studio toolset in CI)."
        )
    manifest = _read_manifest()
    expected = manifest.get(LAUNCHER_NAME)
    actual = hashlib.sha256(vendored).hexdigest()
    if expected and expected != actual:
        raise LauncherBuildError(
            f"vendored launcher SHA-256 {actual} does not match the manifest "
            f"pin {expected}."
        )
    print(f"verified {VENDORED_LAUNCHER} is reproducible ({actual})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    args = parser.parse_args(argv)
    try:
        return do_build() if args.action == "build" else do_verify()
    except LauncherBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
