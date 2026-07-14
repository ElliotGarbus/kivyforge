#!/usr/bin/env bash
#
# build_native.sh — compile this example's non-wheel native binaries into the
# repo-relative sources that pyproject.toml's [tool.kivy.<platform>.native.binaries]
# tables point at. The output layout is per-platform:
#
#   macOS: binaries/macos/{roll,libgreet.dylib}   (universal2: arm64 + x86_64)
#   Linux: binaries/linux/{roll,libgreet.so}      (host arch, host cc)
#
# The host platform is auto-detected, so the same script serves both desktop
# backends. These artifacts are gitignored (they are build output, and a C
# compiler is already a desktop-backend requirement). Run this once before
# `kivyforge lock -p <platform>`.
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
    *)
        echo "error: unsupported host '$HOST' (expected Darwin or Linux)." >&2
        exit 2
        ;;
esac
