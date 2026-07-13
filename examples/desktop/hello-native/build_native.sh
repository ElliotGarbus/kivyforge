#!/usr/bin/env bash
#
# build_native.sh — compile this example's native binaries as universal2
# (arm64 + x86_64) into binaries/macos/, the repo-relative sources that
# pyproject.toml's [tool.kivy.macos.native.binaries] points at.
#
# These artifacts are gitignored (they are build output, and clang is already a
# macOS-backend requirement). Run this once before `kivyforge lock -p macos`.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/binaries/macos"
mkdir -p "$OUT"

# Universal2 so a universal2 .app can run both arches; `kivyforge doctor`
# verifies the staged Mach-O cover every configured arch.
clang -arch arm64 -arch x86_64 -O2 -Wall \
    -o "$OUT/roll" "$HERE/native/roll.c"
clang -arch arm64 -arch x86_64 -O2 -Wall -dynamiclib \
    -o "$OUT/libgreet.dylib" "$HERE/native/libgreet.c"

echo "built (universal2):"
echo "  $OUT/roll"
echo "  $OUT/libgreet.dylib"
