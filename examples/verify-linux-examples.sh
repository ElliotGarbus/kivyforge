#!/usr/bin/env bash
#
# verify-linux-examples.sh — walk each desktop example through the full Linux
# lifecycle, one at a time, so you can visually verify every operation and its
# result. This is the Linux-only, "full loop" companion to run-examples.sh
# (which does the quick clean/lock/build/run dev loop across platforms).
#
# For each desktop example it runs, in order:
#   1. doctor   — kivyforge doctor -p linux           (pre-flight health check)
#   2. clean    — kivyforge clean                     (remove build/ + dist/)
#   3. lock     — kivyforge lock  -p linux            (regenerate + verify the lock)
#   4. build    — kivyforge build -p linux            (assemble the AppDir)
#   5. run      — kivyforge run   -p linux            (launch via ./AppRun; GUI)
#   6. package  — kivyforge package -p linux          (produce the .AppImage)
#   7. AppImage — ./dist/linux/<app>-<ver>-<arch>.AppImage   (launch the artifact)
#
# The lock step regenerates pylock.linux.toml from live PyPI to exercise the
# resolver, verifies it still matches the committed lock (ignoring the volatile
# generated_at timestamp), then RESTORES the committed lock so your git tree
# stays clean. A semantic difference is reported as "lock drift" (non-fatal) so
# you can see the committed reference has aged. Pass --keep-lock to leave the
# regenerated lock in place instead of restoring it.
#
# Steps 5 and 7 open a real window and BLOCK until you close it — that IS the
# visual check. Between examples the script pauses for Enter.
#
# Usage:
#   ./verify-linux-examples.sh                  # default set (dice-roller, notes)
#   ./verify-linux-examples.sh dice-roller      # only the named example(s)
#   ./verify-linux-examples.sh desktop-viewer   # macOS-focused; opt-in by name only
#   ./verify-linux-examples.sh --no-pause       # don't wait for Enter between examples
#   ./verify-linux-examples.sh --no-gui         # skip the two GUI launches (run + AppImage)
#   ./verify-linux-examples.sh --keep-lock      # keep the regenerated lock (don't restore committed)
#   ./verify-linux-examples.sh -h               # this help
#
# Headless/CI: wrap in xvfb with software GL, e.g.
#   LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a ./verify-linux-examples.sh --no-pause
#
set -u

EXAMPLES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$EXAMPLES_DIR/.." && pwd)"
PLATFORM="linux"

# Use the repo virtualenv's kivyforge if present.
if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.venv/bin/activate"
fi

if ! command -v kivyforge >/dev/null 2>&1; then
    echo "error: 'kivyforge' not found on PATH (activate the kivyforge venv first)" >&2
    exit 1
fi

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "error: this script builds Linux AppImages and must run on a Linux host." >&2
    echo "       (current host: $(uname -s))" >&2
    exit 1
fi

PAUSE=1
GUI=1
KEEP_LOCK=0
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-pause)  PAUSE=0 ;;
        --no-gui)    GUI=0 ;;
        --keep-lock) KEEP_LOCK=1 ;;
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

# The resolution chain honours KIVYFORGE_PLATFORM so lock/clean/doctor target
# Linux without needing an explicit -p on every verb.
export KIVYFORGE_PLATFORM="$PLATFORM"
LOCK="pylock.${PLATFORM}.toml"

# desktop-viewer is intentionally excluded from the default set: it builds and
# packages on Linux, but its UX is macOS-specific (Command-key shortcuts + a
# native osascript open panel), so it can't be meaningfully exercised here. Run
# it explicitly by name if you just want to smoke-test its Linux build/package.
DEFAULT_EXAMPLES=(dice-roller notes)
if [[ ${#ARGS[@]} -gt 0 ]]; then
    EXAMPLES=("${ARGS[@]}")
else
    EXAMPLES=("${DEFAULT_EXAMPLES[@]}")
fi

PASSED=()
FAILED=()
DRIFTED=()

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

# The lockfile's generated_at timestamp changes every run, so compare locks with
# it stripped (the toolchain's own "semantic_equal" ignores the same field).
_lock_body() { grep -v '^generated_at ' "$1"; }

verify_lock_step() {
    # Regenerate the lock (exercise the resolver), confirm it still matches the
    # committed reference, then restore the committed lock unless --keep-lock.
    # Sets DRIFT_THIS=1 when the regenerated lock differs semantically.
    DRIFT_THIS=0
    local backup=""
    if [[ -f "$LOCK" ]]; then
        backup="$(mktemp)"
        cp "$LOCK" "$backup"
    fi

    # --update forces a real re-resolution; a bare `lock` is a no-op when the
    # committed lock is already in sync, which would not exercise the resolver.
    if ! run_step "lock" kivyforge lock -p linux --update; then
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

launch_appimage() {
    # Find and run the freshly packaged .AppImage. Falls back to
    # extract-and-run when the host has no FUSE (/dev/fuse), which is common in
    # containers and CI.
    local appimage
    appimage="$(ls -t dist/linux/*.AppImage 2>/dev/null | head -n1)"
    if [[ -z "$appimage" ]]; then
        echo "!!! AppImage: no .AppImage found in dist/linux/"
        return 1
    fi
    chmod +x "$appimage"
    echo
    echo ">>> AppImage: launching $appimage"
    if [[ -e /dev/fuse ]]; then
        "$appimage"
    else
        echo "    (/dev/fuse absent — using APPIMAGE_EXTRACT_AND_RUN=1)"
        APPIMAGE_EXTRACT_AND_RUN=1 "$appimage"
    fi
}

for ex in "${EXAMPLES[@]}"; do
    echo
    echo "============================================================"
    echo "  $ex  ($PLATFORM)"
    echo "============================================================"

    dir="$EXAMPLES_DIR/desktop/$ex"
    if [[ ! -d "$dir" ]]; then
        echo "!!! $ex: directory not found under examples/desktop/"
        FAILED+=("$ex")
        continue
    fi

    pushd "$dir" >/dev/null || { FAILED+=("$ex"); continue; }

    ok=1
    DRIFT_THIS=0
    # 1. doctor — pre-flight; a warning shouldn't abort the run, so this is
    #    informational only (its result is shown, not gating).
    run_step "doctor" kivyforge doctor -p linux || \
        echo "    (doctor reported issues — continuing so you can inspect them)"

    # 2. clean
    [[ $ok -eq 1 ]] && { run_step "clean" kivyforge clean || ok=0; }
    # 3. lock (regenerate + verify against committed, then restore)
    [[ $ok -eq 1 ]] && { verify_lock_step || ok=0; }
    [[ $DRIFT_THIS -eq 1 ]] && DRIFTED+=("$ex")
    # 4. build
    [[ $ok -eq 1 ]] && { run_step "build" kivyforge build -p linux || ok=0; }
    # 5. run (GUI, blocks until you close the window)
    if [[ $ok -eq 1 && $GUI -eq 1 ]]; then
        run_step "run" kivyforge run -p linux || ok=0
    elif [[ $GUI -eq 0 ]]; then
        echo ">>> run: skipped (--no-gui)"
    fi
    # 6. package (produces the .AppImage in dist/linux/)
    [[ $ok -eq 1 ]] && { run_step "package" kivyforge package -p linux || ok=0; }
    # 7. run the packaged AppImage (GUI, blocks)
    if [[ $ok -eq 1 && $GUI -eq 1 ]]; then
        launch_appimage || ok=0
    elif [[ $GUI -eq 0 ]]; then
        echo ">>> AppImage: skipped (--no-gui)"
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
        read -r -p "Verified '$ex'? Press Enter for the next example... " _
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
    echo "  ^ these committed pylock.linux.toml files no longer match a fresh"
    echo "    resolve; re-lock and recommit them when you're ready."
fi

[[ ${#FAILED[@]} -eq 0 ]]
