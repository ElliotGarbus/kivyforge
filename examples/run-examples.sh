#!/usr/bin/env bash
#
# run-examples.sh — rebuild every example from scratch and launch it on the
# target platform's simulator/host for visual verification.
#
# Examples live in two groups, split by Kivy runtime requirement:
#   examples/desktop/<app>/   — macOS/Linux/Windows; Kivy 2.3.1 from PyPI
#   examples/mobile/<app>/    — iOS/Android; Kivy 3.0 (vendored, pre-release)
# Wheels shared by the examples live in examples/wheels/<platform>/.
#
# For each example it:
#   1. deletes the lock file (pylock.<platform>.toml)
#   2. cleans the generated project      (kivyforge clean)
#   3. re-locks                          (kivyforge lock)
#   4. builds for the simulator          (kivyforge build -p <platform> --simulator)
#   5. launches on the simulator         (kivyforge run   -p <platform> --simulator)
#
# Usage:
#   ./run-examples.sh                     # all examples, pause between each
#   ./run-examples.sh hello-kivy ...      # only the named examples
#   ./run-examples.sh --no-pause          # don't wait for Enter between examples
#   ./run-examples.sh -p ios              # target platform (default: ios)
#   ./run-examples.sh -p macos            # desktop suite -> .app bundles
#   ./run-examples.sh -p linux            # desktop suite -> AppDir + ./AppRun
#
set -u

EXAMPLES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$EXAMPLES_DIR/.." && pwd)"

# Use the repo virtualenv's kivyforge if present.
if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.venv/bin/activate"
fi

if ! command -v kivyforge >/dev/null 2>&1; then
    echo "error: 'kivyforge' not found on PATH (activate the kivyforge venv first)" >&2
    exit 1
fi

PAUSE=1
PLATFORM="ios"
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-pause) PAUSE=0 ;;
        -p|--platform)
            shift
            [[ $# -gt 0 ]] || { echo "error: $0 -p needs a platform" >&2; exit 2; }
            PLATFORM="$1"
            ;;
        -h|--help)
            # Print the leading comment block (skip the shebang, stop at the
            # first non-comment line).
            awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' \
                "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *) ARGS+=("$1") ;;
    esac
    shift
done

# The resolution chain honours KIVYFORGE_PLATFORM, so `lock`/`clean` (which do
# not yet take -p) target the same platform as the explicit build/run flags.
export KIVYFORGE_PLATFORM="$PLATFORM"
LOCK="pylock.${PLATFORM}.toml"

# Default set per platform. iOS runs the mobile suite (Kivy 3.0); macOS and
# Linux run the desktop suite, which builds from public PyPI wheels (Kivy 2.3.1)
# with no wheel-building step.
if [[ "$PLATFORM" == "macos" || "$PLATFORM" == "linux" ]]; then
    DEFAULT_EXAMPLES=(
        dice-roller
        notes
        desktop-viewer
    )
else
    DEFAULT_EXAMPLES=(
        hello-world
        hello-kivy
        keychain-spm
        mobile-geometry
        pyobjus-ball
        pyobjus-deviceinfo
        svg-explorer
    )
fi

if [[ ${#ARGS[@]} -gt 0 ]]; then
    EXAMPLES=("${ARGS[@]}")
else
    EXAMPLES=("${DEFAULT_EXAMPLES[@]}")
fi

# Locate an example by name across the group directories (desktop, mobile).
resolve_example_dir() {
    local name="$1"
    local group
    for group in desktop mobile; do
        if [[ -d "$EXAMPLES_DIR/$group/$name" ]]; then
            echo "$EXAMPLES_DIR/$group/$name"
            return 0
        fi
    done
    # Allow passing an explicit relative path (e.g. ios/keychain-spm).
    if [[ -d "$EXAMPLES_DIR/$name" ]]; then
        echo "$EXAMPLES_DIR/$name"
        return 0
    fi
    return 1
}

PASSED=()
FAILED=()

run_step() {
    # run_step "<label>" cmd args...
    local label="$1"; shift
    echo ">>> $label: $*"
    if ! "$@"; then
        echo "!!! $label FAILED"
        return 1
    fi
}

for ex in "${EXAMPLES[@]}"; do
    echo
    echo "============================================================"
    echo "  $ex  ($PLATFORM)"
    echo "============================================================"

    dir="$(resolve_example_dir "$ex")"
    if [[ -z "$dir" ]]; then
        echo "!!! $ex: directory not found under desktop/ or mobile/"
        FAILED+=("$ex")
        continue
    fi

    pushd "$dir" >/dev/null || { FAILED+=("$ex"); continue; }

    ok=1
    rm -f "$LOCK" && echo ">>> removed $LOCK" || ok=0
    [[ $ok -eq 1 ]] && { run_step "clean" kivyforge clean || ok=0; }
    [[ $ok -eq 1 ]] && { run_step "lock"  kivyforge lock  || ok=0; }
    if [[ "$PLATFORM" == "macos" ]]; then
        # No simulator on macOS; build the .app, then open it (non-blocking) so
        # the verification loop can continue while the window is up.
        [[ $ok -eq 1 ]] && { run_step "build" kivyforge build -p macos || ok=0; }
        [[ $ok -eq 1 ]] && { run_step "open"  open build/macos/*.app   || ok=0; }
    elif [[ "$PLATFORM" == "linux" ]]; then
        # No simulator on Linux; build the AppDir, then run ./AppRun directly —
        # the fast dev loop needs no AppImage/FUSE. `run` blocks until the window
        # is closed (that IS the visual check); for headless CI wrap this script's
        # `run` step in `xvfb-run -a` with software GL (LIBGL_ALWAYS_SOFTWARE=1).
        [[ $ok -eq 1 ]] && { run_step "build" kivyforge build -p linux || ok=0; }
        [[ $ok -eq 1 ]] && { run_step "run"   kivyforge run   -p linux || ok=0; }
    else
        [[ $ok -eq 1 ]] && { run_step "build" kivyforge build -p "$PLATFORM" --simulator || ok=0; }
        [[ $ok -eq 1 ]] && { run_step "run"   kivyforge run   -p "$PLATFORM" --simulator || ok=0; }
    fi

    popd >/dev/null

    if [[ $ok -eq 1 ]]; then
        echo "+++ $ex: launched"
        PASSED+=("$ex")
    else
        echo "--- $ex: FAILED"
        FAILED+=("$ex")
    fi

    last_index=$(( ${#EXAMPLES[@]} - 1 ))
    if [[ $PAUSE -eq 1 && "$ex" != "${EXAMPLES[$last_index]}" ]]; then
        echo
        read -r -p "Verify '$ex' in the simulator, then press Enter for the next example... " _
    fi
done

echo
echo "============================================================"
echo "  Summary"
echo "============================================================"
echo "passed (${#PASSED[@]}): ${PASSED[*]:-none}"
echo "failed (${#FAILED[@]}): ${FAILED[*]:-none}"

[[ ${#FAILED[@]} -eq 0 ]]
