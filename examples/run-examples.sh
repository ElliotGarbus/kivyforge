#!/usr/bin/env bash
#
# run-examples.sh — rebuild every example from scratch and launch it on the
# target platform's simulator/host for visual verification.
#
# Examples now live in per-audience groups:
#   examples/cross_platform/<app>/   — run on every platform
#   examples/ios/<app>/              — iOS-only (pyobjus / Swift interop)
# Wheels shared by the examples live in examples/wheels/<platform>/.
#
# For each example (all except hello-world) it:
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

# Default set: every example dir except hello-world, in a sensible order.
DEFAULT_EXAMPLES=(
    hello-kivy
    keychain-spm
    mobile-geometry
    pyobjus-ball
    pyobjus-deviceinfo
    svg-explorer
)

if [[ ${#ARGS[@]} -gt 0 ]]; then
    EXAMPLES=("${ARGS[@]}")
else
    EXAMPLES=("${DEFAULT_EXAMPLES[@]}")
fi

# Locate an example by name across the group directories (cross_platform, ios).
resolve_example_dir() {
    local name="$1"
    local group
    for group in cross_platform ios; do
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
        echo "!!! $ex: directory not found under cross_platform/ or ios/"
        FAILED+=("$ex")
        continue
    fi

    pushd "$dir" >/dev/null || { FAILED+=("$ex"); continue; }

    ok=1
    rm -f "$LOCK" && echo ">>> removed $LOCK" || ok=0
    [[ $ok -eq 1 ]] && { run_step "clean" kivyforge clean                            || ok=0; }
    [[ $ok -eq 1 ]] && { run_step "lock"  kivyforge lock                             || ok=0; }
    [[ $ok -eq 1 ]] && { run_step "build" kivyforge build -p "$PLATFORM" --simulator || ok=0; }
    [[ $ok -eq 1 ]] && { run_step "run"   kivyforge run   -p "$PLATFORM" --simulator || ok=0; }

    popd >/dev/null

    if [[ $ok -eq 1 ]]; then
        echo "+++ $ex: launched on simulator"
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
