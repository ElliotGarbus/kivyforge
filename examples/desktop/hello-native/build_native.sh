#!/usr/bin/env bash
#
# build_native.sh — compile this example's non-wheel native binaries into the
# repo-relative sources that pyproject.toml's [tool.kivy.<platform>.native.binaries]
# tables point at. The output layout is per-platform:
#
#   macOS:   binaries/macos/{roll,libgreet.dylib}   (universal2: arm64 + x86_64)
#   Linux:   binaries/linux/{roll,libgreet.so}      (host arch, host cc)
#   Windows: binaries/windows/{roll.exe,greet.dll}  (amd64; run under git-bash)
#
# The host platform is auto-detected, so the same script serves all three desktop
# backends (Windows via git-bash / MSYS2, where uname reports MINGW*/MSYS*). On a
# Windows box with Visual Studio but no mingw/git-bash, use build_native.ps1
# (MSVC) instead — it produces the same binaries/windows/{roll.exe,greet.dll}.
# These artifacts are gitignored (they are build output, and a C compiler is a
# desktop-backend requirement). Run this once before `kivyforge lock -p <platform>`.
#
# Windows toolchain: this script uses a mingw/clang C compiler (gcc or clang on
# PATH) so greet()'s __declspec(dllexport) lands in the DLL export table without a
# .def file. MSVC `cl` also works (cl /O2 roll.c; cl /LD greet.c) — swap it in if
# that is your toolchain; the dllexport macro in native/libgreet.c covers both.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="$(uname -s)"

case "$HOST" in
    Darwin)
        OUT="$HERE/binaries/macos"
        mkdir -p "$OUT"
        # Universal2 so a universal2 .app can run both arches; `kivyforge doctor`
        # verifies the staged Mach-O cover every configured arch.
        clang -arch arm64 -arch x86_64 -O2 -Wall \
            -o "$OUT/roll" "$HERE/native/roll.c"
        clang -arch arm64 -arch x86_64 -O2 -Wall -dynamiclib \
            -o "$OUT/libgreet.dylib" "$HERE/native/libgreet.c"
        echo "built (macos, universal2):"
        echo "  $OUT/roll"
        echo "  $OUT/libgreet.dylib"
        ;;
    Linux)
        OUT="$HERE/binaries/linux"
        mkdir -p "$OUT"
        CC="${CC:-cc}"
        # NOTE: a prebuilt artifact bakes in the GLIBC version-needs of the build
        # host — rebuilding on a newer distro can silently raise the shipped
        # binary's host requirement above the runtime's glibc 2.17 floor. That is
        # the "consume-prebuilt-artifacts" caveat in action: the build host's
        # glibc floor is your call (build on the oldest distro you support). A
        # deferred `doctor` fast-follow will WARN on version-needs above the floor.
        "$CC" -O2 -Wall -fPIC -o "$OUT/roll" "$HERE/native/roll.c"
        "$CC" -O2 -Wall -fPIC -shared -o "$OUT/libgreet.so" "$HERE/native/libgreet.c"
        echo "built (linux, $(uname -m)):"
        echo "  $OUT/roll"
        echo "  $OUT/libgreet.so"
        ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
        OUT="$HERE/binaries/windows"
        mkdir -p "$OUT"
        # Prefer a mingw/clang compiler: both auto/dllexport greet() into the DLL
        # export table so ctypes.WinDLL("greet.dll").greet resolves. (MSVC `cl`
        # works too — see the header note.)
        if command -v gcc >/dev/null 2>&1; then
            CC="gcc"
        elif command -v clang >/dev/null 2>&1; then
            CC="clang"
        else
            echo "error: no gcc/clang found on PATH. Install MSYS2/mingw-w64 (or" \
                 "use MSVC cl per the header note) to build the Windows binaries." >&2
            exit 2
        fi
        "$CC" -O2 -Wall -o "$OUT/roll.exe" "$HERE/native/roll.c"
        "$CC" -O2 -Wall -shared -o "$OUT/greet.dll" "$HERE/native/libgreet.c"
        echo "built (windows, amd64, $CC):"
        echo "  $OUT/roll.exe"
        echo "  $OUT/greet.dll"
        ;;
    *)
        echo "error: unsupported host '$HOST' (expected Darwin, Linux, or" \
             "MINGW/MSYS/Windows)." >&2
        exit 2
        ;;
esac
