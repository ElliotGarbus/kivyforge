#!/usr/bin/env bash
#
# verify-ios-device.sh — walk one (or more) mobile examples through the full
# iOS *physical device* lifecycle, so you can visually confirm the app
# actually builds, signs, installs, and launches on real hardware. This is
# the --device/--release companion to run-examples.sh (which only ever
# exercises the simulator) and verify-desktop-examples.sh (the desktop
# macOS/Linux equivalent full-loop script).
#
# Manual pre-flight checklist — every item below was an actual failure
# uncovered by ad-hoc device testing, kept here so it's a runbook instead of
# tribal knowledge. This script checks what it can (see precheck_device
# below) but some of these require your judgment:
#
#   1. An Apple ID is signed into Xcode -> Settings -> Accounts, and that
#      account's team matches [tool.kivy.ios.signing].team_id in the
#      example's pyproject.toml. Missing this fails xcodebuild with:
#        "error: No Account for Team \"<TEAM_ID>\". Add a new account in
#         Accounts settings or verify that your accounts have valid
#         credentials."
#        "error: No profiles for '<bundle_id>' were found: ..."
#   2. The device is connected (USB or Wi-Fi) and appears in
#      `xcrun devicectl list devices` with State "connected" or
#      "available (paired)". Xcode does NOT need to be running for this —
#      devicectl opens its own tunnel on demand when you install/launch.
#   3. The device is UNLOCKED at the moment `kivyforge run --device`
#      launches the app. A locked screen fails late (after a successful
#      install) with:
#        "Unable to launch <bundle_id> because the device was not, or could
#         not be, unlocked."
#   4. Exactly one iOS device is paired/selected. If you also have another
#      paired Apple accessory (e.g. an Apple Watch) or multiple iPhones,
#      either unpair the extras or pin one explicitly with
#      --destination 'NAME' (see `kivyforge run --list-devices`).
#
# For each example it runs, in order:
#   1. doctor    — kivyforge doctor -p ios               (pre-flight; informational)
#   2. clean     — kivyforge clean
#   3. lock      — kivyforge lock -p ios --update         (regenerate + verify, then restore)
#   4. build     — kivyforge build -p ios --device        (Debug, on-device signing)
#   5. run       — kivyforge run   -p ios --device        (install + launch; visual check)
#   6. package   — kivyforge package -p ios --export-method development
#                                                          (archive + export a .ipa; skip with --no-release)
#
# Steps 5 pauses so you can look at the phone — that IS the visual check.
# Between examples the script also pauses for Enter.
#
# Usage:
#   ./verify-ios-device.sh                        # default: hello-kivy
#   ./verify-ios-device.sh keychain-spm ...       # only the named example(s)
#   ./verify-ios-device.sh --no-pause             # don't wait for Enter between examples
#   ./verify-ios-device.sh --no-release           # skip the package/export step
#   ./verify-ios-device.sh --destination 'NAME'   # pin a device (see kivyforge run --list-devices)
#   ./verify-ios-device.sh --keep-lock            # keep the regenerated lock (don't restore committed)
#   ./verify-ios-device.sh -h                     # this help
#
set -u

EXAMPLES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$EXAMPLES_DIR/.." && pwd)"
PLATFORM="ios"

# Use the repo virtualenv's kivyforge if present.
if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.venv/bin/activate"
fi

if ! command -v kivyforge >/dev/null 2>&1; then
    echo "error: 'kivyforge' not found on PATH (activate the kivyforge venv first)" >&2
    exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "error: iOS device builds require Xcode and must run on macOS." >&2
    echo "       (current host: $(uname -s))" >&2
    exit 1
fi

PAUSE=1
RELEASE=1
KEEP_LOCK=0
DESTINATION=""
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-pause)   PAUSE=0 ;;
        --no-release) RELEASE=0 ;;
        --keep-lock)  KEEP_LOCK=1 ;;
        --destination)
            shift
            [[ $# -gt 0 ]] || { echo "error: --destination needs a value" >&2; exit 2; }
            DESTINATION="$1"
            ;;
        -h|--help)
            awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' \
                "${BASH_SOURCE[0]}"
            exit 0
            ;;
        -*) echo "error: unknown option '$1' (see -h)" >&2; exit 2 ;;
        *)  ARGS+=("$1") ;;
    esac
    shift
done

export KIVYFORGE_PLATFORM="$PLATFORM"
LOCK="pylock.${PLATFORM}.toml"

DEFAULT_EXAMPLES=(hello-kivy)
if [[ ${#ARGS[@]} -gt 0 ]]; then
    EXAMPLES=("${ARGS[@]}")
else
    EXAMPLES=("${DEFAULT_EXAMPLES[@]}")
fi

run_step() {
    # run_step "<label>" cmd args...
    local label="$1"; shift
    echo
    echo ">>> $label: $*"
    if ! "$@"; then
        echo "!!! $label FAILED"
        return 1
    fi
    return 0
}

# The lockfile's generated_at timestamp changes every run, so compare locks
# with it stripped (the toolchain's own "semantic_equal" ignores the same
# field).
_lock_body() { grep -v '^generated_at ' "$1"; }

verify_lock_step() {
    # Regenerate the lock (exercise the resolver), confirm it still matches
    # the committed reference, then restore the committed lock unless
    # --keep-lock. Sets DRIFT_THIS=1 when the regenerated lock differs
    # semantically.
    DRIFT_THIS=0
    local backup=""
    if [[ -f "$LOCK" ]]; then
        backup="$(mktemp)"
        cp "$LOCK" "$backup"
    fi

    if ! run_step "lock" kivyforge lock -p ios --update; then
        [[ -n "$backup" ]] && rm -f "$backup"
        return 1
    fi

    if [[ -z "$backup" ]]; then
        echo "    no committed $LOCK to compare against; keeping the generated one."
        return 0
    fi

    if diff <(_lock_body "$backup") <(_lock_body "$LOCK") >/dev/null; then
        echo "    lock matches the committed reference (ignoring generated_at)."
    else
        echo "!!! lock DRIFT: regenerated $LOCK differs from the committed one:"
        diff <(_lock_body "$backup") <(_lock_body "$LOCK") | sed 's/^/      /'
        DRIFT_THIS=1
    fi

    if [[ $KEEP_LOCK -eq 1 ]]; then
        echo "    keeping the regenerated lock (--keep-lock)."
    else
        cp "$backup" "$LOCK"
        echo "    restored the committed lock (git tree left clean)."
    fi
    rm -f "$backup"
    return 0
}

precheck_device() {
    # Best-effort automated checks for pre-flight items 1-2 above. This
    # can't verify an Apple ID is signed into Xcode (no public CLI for
    # that), but it can confirm Xcode/devicectl are usable and that at
    # least one iOS device is paired — the two most common "nothing to
    # even try" failures.
    echo ">>> pre-flight: Xcode + paired device check"
    if ! xcode-select -p >/dev/null 2>&1; then
        echo "!!! no Xcode toolchain selected (xcode-select -p failed)"
        return 1
    fi
    local listing
    if ! listing="$(xcrun devicectl list devices 2>&1)"; then
        echo "!!! 'xcrun devicectl list devices' failed:"
        echo "$listing" | sed 's/^/      /'
        return 1
    fi
    echo "$listing" | sed 's/^/    /'
    if ! echo "$listing" | grep -Eq 'iPhone|iPad'; then
        echo "!!! no paired iPhone/iPad found."
        echo "    connect one via USB/Wi-Fi, trust this Mac, then re-run."
        return 1
    fi
    echo "    (remember: an Apple ID must still be signed into Xcode ->"
    echo "     Settings -> Accounts for its team to sign anything — this"
    echo "     script cannot check that for you.)"
    return 0
}

if ! precheck_device; then
    echo
    echo "error: device pre-flight failed; see checklist in this script's header." >&2
    exit 1
fi

PASSED=()
FAILED=()
DRIFTED=()

for ex in "${EXAMPLES[@]}"; do
    echo
    echo "============================================================"
    echo "  $ex  (ios, device)"
    echo "============================================================"

    dir="$EXAMPLES_DIR/mobile/$ex"
    if [[ ! -d "$dir" ]]; then
        echo "!!! $ex: directory not found under examples/mobile/"
        FAILED+=("$ex")
        continue
    fi

    pushd "$dir" >/dev/null || { FAILED+=("$ex"); continue; }

    ok=1
    DRIFT_THIS=0
    # 1. doctor — pre-flight; a warning shouldn't abort the run, so this is
    #    informational only (its result is shown, not gating).
    run_step "doctor" kivyforge doctor -p ios || \
        echo "    (doctor reported issues — continuing so you can inspect them)"

    # 2. clean
    [[ $ok -eq 1 ]] && { run_step "clean" kivyforge clean || ok=0; }
    # 3. lock (regenerate + verify against committed, then restore)
    [[ $ok -eq 1 ]] && { verify_lock_step || ok=0; }
    [[ $DRIFT_THIS -eq 1 ]] && DRIFTED+=("$ex")
    # 4. build --device (Debug, on-device signing)
    [[ $ok -eq 1 ]] && { run_step "build" kivyforge build -p ios --device || ok=0; }
    # 5. run --device (install + launch; visual check — unlock the phone!)
    if [[ $ok -eq 1 ]]; then
        if [[ -n "$DESTINATION" ]]; then
            run_step "run" kivyforge run -p ios --device --destination "$DESTINATION" || ok=0
        else
            run_step "run" kivyforge run -p ios --device || ok=0
        fi
    fi
    # 6. package --release (archive + export a .ipa)
    if [[ $ok -eq 1 && $RELEASE -eq 1 ]]; then
        run_step "package" kivyforge package -p ios --export-method development || ok=0
    elif [[ $RELEASE -eq 0 ]]; then
        echo ">>> package: skipped (--no-release)"
    fi

    popd >/dev/null

    if [[ $ok -eq 1 ]]; then
        echo
        echo "+++ $ex: OK"
        PASSED+=("$ex")
    else
        echo
        echo "--- $ex: FAILED"
        FAILED+=("$ex")
    fi

    last_index=$(( ${#EXAMPLES[@]} - 1 ))
    if [[ $PAUSE -eq 1 && "$ex" != "${EXAMPLES[$last_index]}" ]]; then
        echo
        read -r -p "Verified '$ex' on the phone? Press Enter for the next example... " _
    fi
done

echo
echo "============================================================"
echo "  Summary"
echo "============================================================"
echo "passed (${#PASSED[@]}): ${PASSED[*]:-none}"
echo "failed (${#FAILED[@]}): ${FAILED[*]:-none}"
if [[ ${#DRIFTED[@]} -gt 0 ]]; then
    echo "lock drift (${#DRIFTED[@]}): ${DRIFTED[*]}"
    echo "  ^ these committed pylock.ios.toml files no longer match a fresh"
    echo "    resolve; re-lock and recommit them when you're ready."
fi

[[ ${#FAILED[@]} -eq 0 ]]
