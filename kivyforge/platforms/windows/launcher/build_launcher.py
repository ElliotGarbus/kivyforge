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

Determinism, in three flags: ``/Brepro`` on both the compile and link steps
replaces the PE timestamp with a content hash (no wall-clock time), the linker
``/RELEASE`` writes a deterministic checksum, and ``/EMITTOOLVERSIONINFO:NO``
omits the PE **"rich header"** — the block stamping the exact build of every
tool that touched the image.  kivyforge's launcher **appends nothing** to the
binary, so there is no zip/timestamp tail to non-determinize it (unlike
distlib).

``/EMITTOOLVERSIONINFO:NO`` is what makes the binary reproducible *across
machines*, and it is not optional: ``VCTOOLSVERSION`` (the toolset directory
name, e.g. ``14.51.36231``) does **not** identify the compiler shipped inside
it — ``cl`` there reports a different build (e.g. ``19.51.36248``), and Microsoft
services that binary in place.  Two hosted runner images can therefore expose
the same ``VCTOOLSVERSION`` while running ``cl``/``link`` builds ``36248`` and
``36252``.  Those builds land in the rich header, whose length shifts every
following file offset and perturbs the ``/Brepro`` hash: 307 bytes of drift with
*byte-identical machine code*.  No pin can fix that (vcvars selects by directory
version, which is the thing that doesn't discriminate) — so drop the stamp.

The toolset pin below is still worth keeping, but for the other half of the
problem: a genuinely different MSVC or Windows SDK can emit different *code*.

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
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "launcher.c"
VENDOR_DIR = HERE.parent / "vendor"
# arm64: launcher.c is portable, so arm64 reuses the same source but needs a
# SECOND vendored binary (launcher-arm64.exe) + SHA256SUMS entry. Make these
# per-arch and thread arch through compile_launcher/_vcvars_env/do_build/do_verify.
# Cross-compile from an x64 runner via `vcvarsall x64_arm64`. See arm64-windows.md §5.
LAUNCHER_NAME = "launcher-amd64.exe"
VENDORED_LAUNCHER = VENDOR_DIR / LAUNCHER_NAME
MANIFEST = VENDOR_DIR / "SHA256SUMS"
# The MSVC + Windows SDK pin that produced the vendored binary: build and CI
# verify load them via ``vcvarsall <arch> <winsdk> -vcvars_ver=<tools>``.
#
# ``TOOLSET.txt`` format (one or two lines, ``#`` comments allowed)::
#
#     14.51.36231          # full VCTOOLSVERSION (required)
#     10.0.26100.0         # WindowsSDKVersion (optional but recorded by build)
#
# This pin holds *code generation* steady — a different MSVC or SDK can inline
# different CRT/SDK code and change the emitted instructions. It deliberately
# does **not** carry the burden of pinning the compiler *identity*: the module
# docstring explains why it cannot (VCTOOLSVERSION names a directory, not the
# serviced ``cl`` inside it), which is what ``/EMITTOOLVERSIONINFO:NO`` handles
# instead. Pin the *full* VCTOOLSVERSION rather than major.minor, though:
# ``-vcvars_ver=14.51`` means "latest installed 14.51.xxxxx". When a runner
# image drops either pin, verify fails loudly and ``revendor_launcher`` re-pins
# against the new defaults.
TOOLSET_FILE = VENDOR_DIR / "TOOLSET.txt"

# Deterministic compile/link flags. Keep these lists in lockstep with any change
# that would alter the emitted bytes (both here and in the CI workflow); every
# change to them requires a re-vendor.
_CL_FLAGS = ["/nologo", "/c", "/O1", "/Brepro", "/utf-8", "/DUNICODE", "/D_UNICODE"]
_LINK_FLAGS = ["/nologo", "/Brepro", "/RELEASE", "/EMITTOOLVERSIONINFO:NO"]
_LINK_LIBS = ["kernel32.lib", "shell32.lib"]


class LauncherBuildError(Exception):
    """The launcher could not be compiled or failed its reproducibility check."""


@dataclass(frozen=True)
class ToolsetPin:
    """The exact MSVC + Windows SDK pair a launcher binary was built with."""

    vc_tools: str
    winsdk: str | None = None

    def label(self) -> str:
        return (
            f"MSVC {self.vc_tools} + Windows SDK {self.winsdk}"
            if self.winsdk
            else f"MSVC {self.vc_tools}"
        )


def pinned_toolset() -> ToolsetPin | None:
    """The pinned MSVC (+ optional Windows SDK), or ``None`` if unrecorded.

    Accepts legacy single-line ``major.minor`` / full-version-only pins;
    ``do_build`` rewrites them to the two-line full form on the next re-vendor.
    """
    if not TOOLSET_FILE.is_file():
        return None
    lines = [
        line.strip()
        for line in TOOLSET_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        return None
    vc_tools = lines[0]
    winsdk = lines[1] if len(lines) > 1 else None
    return ToolsetPin(vc_tools, winsdk)


def write_toolset_pin(pin: ToolsetPin) -> None:
    """Persist *pin* so CI verify can reload the exact same vcvars pair."""
    lines = [
        "# MSVC VCTOOLSVERSION + Windows SDK used to build launcher-amd64.exe.",
        "# Re-vendor via the `revendor_launcher` CI workflow when either drifts.",
        pin.vc_tools,
    ]
    if pin.winsdk:
        lines.append(pin.winsdk)
    TOOLSET_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _vc_tools_version(env: dict[str, str]) -> str:
    """The ``VCTOOLSVERSION`` from a vcvars environment, or empty if unset."""
    return env.get("VCTOOLSVERSION", "").strip()


def _windows_sdk_version(env: dict[str, str]) -> str:
    """The ``WindowsSDKVersion`` from a vcvars environment, trailing ``\\`` stripped."""
    return env.get("WINDOWSSDKVERSION", "").strip().strip("\\")


def _vcvars_env(
    arch: str = "x64",
    *,
    vcvars_ver: str | None = None,
    winsdk_version: str | None = None,
) -> dict[str, str]:
    """Return the environment after loading the Visual Studio dev vars for *arch*.

    Locates the toolset with ``vswhere`` and runs ``vcvarsall.bat``, capturing
    the resulting environment so ``cl``/``link`` resolve without the caller
    being inside a Developer Command Prompt. ``vcvars_ver`` pins the MSVC
    toolset (full ``VCTOOLSVERSION``, e.g. ``14.51.36231``); ``winsdk_version``
    pins the Windows SDK (e.g. ``10.0.26100.0``).
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
    # arm64: cross-compiling the arm64 launcher needs the ARM64 toolset — also
    # require "Microsoft.VisualStudio.Component.VC.Tools.ARM64" and load vcvars
    # with arch="x64_arm64". See arm64-windows.md §5.
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
    # Positional form: vcvarsall <arch> [winsdk_version] [-vcvars_ver=...].
    marker = "__KIVYFORGE_ENV__"
    sdk_arg = f" {winsdk_version}" if winsdk_version else ""
    ver_arg = f" -vcvars_ver={vcvars_ver}" if vcvars_ver else ""
    with tempfile.TemporaryDirectory(prefix="kivy-vcvars-") as tmp:
        bat = Path(tmp) / "env.bat"
        bat.write_text(
            f'@echo off\r\ncall "{vcvarsall}" {arch}{sdk_arg}{ver_arg} >nul\r\n'
            f"echo {marker}\r\nset\r\n",
            encoding="utf-8",
        )
        result = subprocess.run(["cmd", "/c", str(bat)], capture_output=True, text=True)
    if result.returncode != 0 or marker not in result.stdout:
        raise LauncherBuildError(
            f"failed to initialize the MSVC environment via {vcvarsall}"
            f" (arch={arch}, winsdk={winsdk_version or 'latest'}, "
            f"vcvars_ver={vcvars_ver or 'latest'}):\n"
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
    winsdk_version: str | None = None,
) -> Path:
    """Deterministically compile a single C *source* to *dest* with MSVC.

    Shared by the launcher build and the launcher end-to-end test (which builds
    a tiny console stub standing in for ``python.exe``). ``subsystem`` links
    ``/SUBSYSTEM:<subsystem>``; ``extra_libs`` appends import libraries;
    ``vcvars_ver`` / ``winsdk_version`` pin the MSVC toolset and Windows SDK
    for byte-reproducibility.
    """
    if sys.platform != "win32":
        raise LauncherBuildError(
            "C sources can only be compiled on Windows (needs MSVC)."
        )
    if not source.is_file():
        raise LauncherBuildError(f"C source missing: {source}")
    env = {k.upper(): v for k, v in os.environ.items()} | _vcvars_env(
        arch, vcvars_ver=vcvars_ver, winsdk_version=winsdk_version
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
        link = [
            link_exe,
            *_LINK_FLAGS,
            f"/SUBSYSTEM:{subsystem}",
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
    dest: Path,
    *,
    arch: str = "x64",
    vcvars_ver: str | None = None,
    winsdk_version: str | None = None,
) -> Path:
    """Compile ``launcher.c`` to *dest* deterministically. Returns *dest*."""
    return compile_c_source(
        SOURCE,
        dest,
        subsystem="WINDOWS",
        arch=arch,
        vcvars_ver=vcvars_ver,
        winsdk_version=winsdk_version,
    )


def _which(tool: str, env: dict[str, str]) -> str:
    """Resolve *tool* to an absolute path using the loaded MSVC env's PATH.

    Windows' ``CreateProcess`` searches the *parent* process PATH, not the
    child ``env`` we pass to ``subprocess`` — so ``cl``/``link`` must be resolved
    against the vcvars PATH ourselves.
    """
    found = shutil.which(tool, path=env.get("PATH", ""))
    if found is None:
        pin = pinned_toolset()
        hint = (
            f" The pinned toolset {pin.label()!r} (vendor/TOOLSET.txt) may not "
            "be installed on this machine/runner — re-vendor against a current "
            "toolset via the `revendor_launcher` CI workflow."
            if pin
            else " The Visual Studio C++ build tools may be incomplete."
        )
        raise LauncherBuildError(f"{tool} not found on the MSVC toolset PATH.{hint}")
    return found


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str], step: str) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise LauncherBuildError(
            f"launcher {step} step failed (exit {proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def has_tool_version_stamp(image: bytes) -> bool:
    """True if *image* (PE bytes) still carries an MSVC "rich header".

    The rich header sits between the DOS stub and the ``PE\\0\\0`` signature at
    ``e_lfanew``, and records the exact build of every tool that contributed to
    the image — which is precisely what differs between two runner images
    carrying the same ``VCTOOLSVERSION``. ``/EMITTOOLVERSIONINFO:NO`` omits it;
    this is the assertion that the flag took effect, so a toolchain that
    quietly stops honoring it fails the build instead of silently re-breaking
    cross-machine reproducibility.
    """
    if len(image) < 0x40 or image[:2] != b"MZ":
        return False
    e_lfanew = int.from_bytes(image[0x3C:0x40], "little")
    if not 0x40 <= e_lfanew <= len(image):
        return False
    return b"Rich" in image[0x40:e_lfanew]


def _reject_tool_version_stamp(image: bytes, what: str) -> None:
    if has_tool_version_stamp(image):
        raise LauncherBuildError(
            f"the {what} carries an MSVC tool-version ('rich') header, so "
            "/EMITTOOLVERSIONINFO:NO did not take effect. That header stamps "
            "the serviced cl/link build, which differs between runner images "
            "sharing one VCTOOLSVERSION — leaving it in makes the binary "
            "non-reproducible across machines. Check that the linker still "
            "supports the flag before vendoring this binary."
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
    # Resolve once, record the full MSVC + Windows SDK pair, and compile
    # against that exact pair — never re-resolve via a major.minor / "latest
    # SDK" alias, which would silently pick different builds on another runner.
    env = {k.upper(): v for k, v in os.environ.items()} | _vcvars_env(
        vcvars_ver=pin.vc_tools if pin else None,
        winsdk_version=pin.winsdk if pin else None,
    )
    tools_version = _vc_tools_version(env)
    sdk_version = _windows_sdk_version(env)
    if not tools_version:
        raise LauncherBuildError(
            "vcvars did not export VCTOOLSVERSION; cannot record a "
            "reproducible toolset pin in vendor/TOOLSET.txt."
        )
    recorded = ToolsetPin(tools_version, sdk_version or None)
    write_toolset_pin(recorded)
    compile_launcher(
        VENDORED_LAUNCHER,
        vcvars_ver=recorded.vc_tools,
        winsdk_version=recorded.winsdk,
    )
    _reject_tool_version_stamp(VENDORED_LAUNCHER.read_bytes(), "freshly built launcher")
    digest = sha256_of(VENDORED_LAUNCHER)
    entries = _read_manifest()
    entries[LAUNCHER_NAME] = digest
    _write_manifest(entries)
    print(f"built {VENDORED_LAUNCHER} ({digest}); {recorded.label()}")
    return 0


def do_verify() -> int:
    if not VENDORED_LAUNCHER.is_file():
        raise LauncherBuildError(
            f"vendored launcher missing: {VENDORED_LAUNCHER}. Run the `build` "
            "subcommand to produce it."
        )
    vendored = VENDORED_LAUNCHER.read_bytes()
    pin = pinned_toolset()
    # Resolve first so a missing/mismatched pin fails with the toolset name,
    # and so the mismatch error can report which compiler + SDK actually ran.
    env = {k.upper(): v for k, v in os.environ.items()} | _vcvars_env(
        vcvars_ver=pin.vc_tools if pin else None,
        winsdk_version=pin.winsdk if pin else None,
    )
    used = ToolsetPin(_vc_tools_version(env), _windows_sdk_version(env) or None)
    with tempfile.TemporaryDirectory(prefix="kivy-launcher-verify-") as tmp:
        rebuilt_path = Path(tmp) / LAUNCHER_NAME
        compile_launcher(
            rebuilt_path,
            vcvars_ver=pin.vc_tools if pin else None,
            winsdk_version=pin.winsdk if pin else None,
        )
        rebuilt = rebuilt_path.read_bytes()
    _reject_tool_version_stamp(rebuilt, "freshly compiled launcher")
    if rebuilt != vendored:
        # A vendored binary that still carries the stamp predates
        # /EMITTOOLVERSIONINFO:NO and can never match a current rebuild — say so
        # rather than sending the reader off to compare toolset versions.
        cause = (
            "  The vendored binary still carries an MSVC tool-version ('rich') "
            "header, so it predates the /EMITTOOLVERSIONINFO:NO link flag and "
            "cannot match a current rebuild. Re-vendor once via the "
            "`revendor_launcher` CI workflow; this is expected on the commit "
            "that introduced the flag."
            if has_tool_version_stamp(vendored)
            else "  Either the C source or the compile/link flags changed "
            "without re-vendoring (run `build`), or this runner's "
            "MSVC/Windows-SDK pair emits different code than the one that "
            "produced the vendored binary — re-vendor via the "
            "`revendor_launcher` CI workflow when the hosted image rolls."
        )
        raise LauncherBuildError(
            "the freshly compiled launcher does not byte-match the vendored "
            f"binary ({VENDORED_LAUNCHER}).\n"
            f"  vendored: {len(vendored)} bytes, sha256={hashlib.sha256(vendored).hexdigest()}\n"
            f"  rebuilt:  {len(rebuilt)} bytes, sha256={hashlib.sha256(rebuilt).hexdigest()}\n"
            f"  pinned: {pin.label() if pin else '(none)'}; "
            f"compiler used: {used.label()}\n" + cause
        )
    manifest = _read_manifest()
    expected = manifest.get(LAUNCHER_NAME)
    actual = hashlib.sha256(vendored).hexdigest()
    if expected and expected != actual:
        raise LauncherBuildError(
            f"vendored launcher SHA-256 {actual} does not match the manifest "
            f"pin {expected}."
        )
    print(f"verified {VENDORED_LAUNCHER} is reproducible ({actual}); {used.label()}")
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
