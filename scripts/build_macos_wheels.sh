#!/usr/bin/env bash
# Build Kivy cp314 macOS universal2 wheels locally (Path A for Kivy examples).
#
# The macOS analog of build_ios_wheels.sh. Kivy 3.0.0.dev0 has no public macOS
# wheels yet, so the Kivy-3.0 cross-platform examples (hello-kivy,
# mobile-geometry, svg-explorer) need locally-built macOS wheels to
# `kivyforge lock -p macos`. Wheels land in OUTPUT_DIR (default:
# examples/wheels/macos) and are picked up via each example's
# [tool.kivy.macos].find_links = ["../../wheels/macos"].
#
# The new PyPI-based examples (dice-roller, notes, desktop-viewer) use Kivy 2.3.1
# straight from PyPI and do NOT need this script.
#
# Usage:
#   scripts/build_macos_wheels.sh [OUTPUT_DIR]
#
# Environment:
#   MACOSX_DEPLOYMENT_TARGET  Minimum macOS version for wheel platform tags
#                             (default: 11.0). Should be <= each example's
#                             [tool.kivy.macos].minimum_system_version.
#   CIBW_BUILD                CPython selector (default: cp314-*), matching the
#                             examples' [tool.kivy.macos.python].version and the
#                             bundled python-build-standalone runtime.
#
# Prerequisites: macOS, Xcode command-line tools, network. Host Python 3.x.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${1:-$ROOT/examples/wheels/macos}"
BUILD_ROOT="${BUILD_ROOT:-$ROOT/.build/macos-wheels}"
KIVY_SRC="${KIVY_SRC:-$BUILD_ROOT/kivy}"
KIVY_REF="${KIVY_REF:-master}"
MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-11.0}"

mkdir -p "$OUTPUT_DIR" "$BUILD_ROOT"

if [[ ! -d "$KIVY_SRC/.git" ]]; then
  echo "Cloning kivy/kivy (${KIVY_REF}) into $KIVY_SRC ..."
  git clone --depth 1 --branch "$KIVY_REF" https://github.com/kivy/kivy.git "$KIVY_SRC"
else
  echo "Refreshing existing Kivy checkout at $KIVY_SRC to origin/${KIVY_REF} ..."
  git -C "$KIVY_SRC" fetch --depth 1 origin "$KIVY_REF"
  git -C "$KIVY_SRC" reset --hard FETCH_HEAD
fi
echo "Kivy checkout at: $(git -C "$KIVY_SRC" log -1 --oneline)"

echo "Installing cibuildwheel build deps ..."
python3 -m pip install -q -r "$KIVY_SRC/.ci/cicd-requirements.txt" || true
python3 -m pip install -q 'cibuildwheel>=2.20' delocate meson ninja

pushd "$KIVY_SRC" >/dev/null

# Build a universal2 wheel so a two-arch [tool.kivy.macos].archs lock resolves a
# single fat wheel (no per-arch lipo merge needed at bundle time). delocate,
# invoked by cibuildwheel's repair step, vendors SDL2 et al. into the wheel.
export CIBW_PLATFORM=macos
export CIBW_ARCHS_MACOS="universal2"
export CIBW_BUILD="${CIBW_BUILD:-cp314-*}"
export CIBW_ENABLE=cpython-prerelease
export MACOSX_DEPLOYMENT_TARGET

WHEELHOUSE="$(mktemp -d "$BUILD_ROOT/kivy-wheelhouse.XXXXXX")"
echo "Running cibuildwheel (MACOSX_DEPLOYMENT_TARGET=$MACOSX_DEPLOYMENT_TARGET, output -> $WHEELHOUSE) ..."
python3 -m cibuildwheel --output-dir "$WHEELHOUSE"

popd >/dev/null

echo "Copying wheels to $OUTPUT_DIR ..."
cp -v "$WHEELHOUSE"/*.whl "$OUTPUT_DIR/"
rm -rf "$WHEELHOUSE"

echo "Done. Built wheels:"
ls -1 "$OUTPUT_DIR"/*.whl
echo
echo "Next: cd into a Kivy-3.0 example and run \`kivyforge lock -p macos\`."
