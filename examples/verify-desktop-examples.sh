#!/usr/bin/env bash
#
# verify-desktop-examples.sh — walk each desktop example through the full
# lifecycle for a desktop platform (macOS or Linux), one at a time, so you can
# visually verify every operation and its result. This is the "full loop"
# companion to run-examples.sh (the quick clean/lock/build/run dev loop),
# covering both desktop backends by detecting the host platform and making the
# platform-dependent choices.
#
# Platform is auto-detected from the host (macOS -> macos, Linux -> linux) and
# can be overridden with -p. Examples that lack a [tool.kivy.<platform>] overlay
# are skipped (e.g. desktop-viewer is macOS-only), so the same invocation is
# safe on either host.
#
# For each example it runs, in order:
#   0. native   — ./build_native.sh, when present   (compile vendored binaries)
#   1. doctor   — kivyforge doctor -p <platform>     (pre-flight; non-gating)
#   2. clean    — kivyforge clean                    (remove build/ + dist/)
#   3. lock     — kivyforge lock  -p <platform>      (regenerate + verify the lock)
#   4. build    — kivyforge build -p <platform>      (assemble the bundle)
#   5. run      — kivyforge run   -p <platform>      (launch the dev build; GUI)
#   6. package  — kivyforge package -p <platform>    (produce the distributable)
#   7. artifact — launch the packaged distributable  (GUI)
#
# The two platforms differ only where they must:
#   - build/run/package targets: .app (macOS) vs AppDir/AppImage (Linux).
#   - packaged artifact (step 7): macOS signs the .app in place under
#     build/macos/ and it is opened with `open` (LaunchServices, non-blocking);
#     Linux produces dist/linux/<app>-<ver>-<arch>.AppImage and runs it (blocks).
#
# The lock step regenerates pylock.<platform>.toml from live PyPI to exercise the
# resolver, verifies it still matches the committed lock (ignoring the volatile
# generated_at timestamp), then RESTORES the committed lock so your git tree
# stays clean. A semantic difference is reported as "lock drift" (non-fatal).
# Examples with no committed lock (e.g. hello-native, whose lock is gitignored)
# simply keep the freshly generated one. Pass --keep-lock to leave regenerated
# locks in place.
#
# GUI steps open a real window. On Linux `run` and the AppImage BLOCK until you
# close the window (that IS the visual check). On macOS `run` blocks
# (foreground), while the packaged `open` returns immediately and the app stays
# up until you quit it. Between examples the script pauses for Enter.
#
# Usage:
#   ./verify-desktop-examples.sh                  # host platform, default set
#   ./verify-desktop-examples.sh -p macos         # force macOS
#   ./verify-desktop-examples.sh -p linux         # force Linux
#   ./verify-desktop-examples.sh dice-roller      # only the named example(s)
#   ./verify-desktop-examples.sh --no-pause       # don't wait for Enter between examples
#   ./verify-desktop-examples.sh --no-gui         # skip the GUI launches (run + artifact)
#   ./verify-desktop-examples.sh --keep-lock      # keep regenerated locks (don't restore)
#   ./verify-desktop-examples.sh -h               # this help
#
# Headless/CI (Linux): wrap in xvfb with software GL, e.g.
#   LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a ./verify-desktop-examples.sh -p linux --no-pause
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
GUI=1
KEEP_LOCK=0
PLATFORM=""
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-pause)  PAUSE=0 ;;
        --no-gui)    GUI=0 ;;
        --keep-lock) KEEP_LOCK=1 ;;
        -p|--platform)
            shift
            [[ $# -gt 0 ]] || { echo "error: $0 -p needs a platform" >&2; exit 2; }
            PLATFORM="$1"
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

# Default the platform to the host; macOS -> macos, Linux -> linux.
HOST="$(uname -s)"
if [[ -z "$PLATFORM" ]]; then
    case "$HOST" in
        Darwin) PLATFORM="macos" ;;
        Linux)  PLATFORM="linux" ;;
        *) echo "error: unsupported host '$HOST'; pass -p macos|linux." >&2; exit 2 ;;
    esac
fi

case "$PLATFORM" in
    macos)
        if [[ "$HOST" != "Darwin" ]]; then
            echo "error: -p macos builds .app bundles and must run on macOS " \
                 "(host: $HOST)." >&2
            exit 1
        fi
        DEFAULT_EXAMPLES=(dice-roller notes desktop-viewer hello-native)
        ;;
    linux)
        if [[ "$HOST" != "Linux" ]]; then
            echo "error: -p linux builds AppImages and must run on Linux " \
                 "(host: $HOST)." >&2
            exit 1
        fi
        DEFAULT_EXAMPLES=(dice-roller notes hello-native)
        ;;
    *)
        echo "error: unknown platform '$PLATFORM' (expected macos or linux)." >&2
        exit 2
        ;;
esac

# The resolution chain honours KIVYFORGE_PLATFORM so lock/clean/doctor target
# this platform without needing an explicit -p on every verb.
export KIVYFORGE_PLATFORM="$PLATFORM"
LOCK="pylock.${PLATFORM}.toml"

if [[ ${#ARGS[@]} -gt 0 ]]; then
    EXAMPLES=("${ARGS[@]}")
else
    EXAMPLES=("${DEFAULT_EXAMPLES[@]}")
fi

PASSED=()
FAILED=()
SKIPPED=()
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
    if ! run_step "lock" kivyforge lock -p "$PLATFORM" --update; then
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
        echo "!!! artifact: no .AppImage found in dist/linux/"
        return 1
    fi
    chmod +x "$appimage"
    echo
    echo ">>> artifact: launching $appimage"
    if [[ -e /dev/fuse ]]; then
        "$appimage"
    else
        echo "    (/dev/fuse absent — using APPIMAGE_EXTRACT_AND_RUN=1)"
        APPIMAGE_EXTRACT_AND_RUN=1 "$appimage"
    fi
}

launch_macos_app() {
    # macOS `package` signs the .app in place (no separate dist/ artifact); open
    # it via LaunchServices — the realistic double-click path (Dock, Gatekeeper).
    # `open` returns immediately, so the app stays up until you quit it.
    local apps=()
    shopt -s nullglob
    apps=(build/macos/*.app)
    shopt -u nullglob
    if [[ ${#apps[@]} -eq 0 ]]; then
        echo "!!! artifact: no .app found in build/macos/"
        return 1
    fi
    echo
    echo ">>> artifact: opening ${apps[0]} (non-blocking; quit it when done)"
    open "${apps[0]}"
}

launch_package_artifact() {
    case "$PLATFORM" in
        linux) launch_appimage ;;
        macos) launch_macos_app ;;
    esac
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

    # Skip examples that have no overlay for this platform (e.g. desktop-viewer
    # is macOS-only) so a mixed default set is safe on Linux.
    if ! grep -Eq "^\[tool\.kivy\.${PLATFORM}(\]|\.)" "$dir/pyproject.toml"; then
        echo ">>> $ex: no [tool.kivy.$PLATFORM] overlay — skipping"
        SKIPPED+=("$ex")
        continue
    fi

    pushd "$dir" >/dev/null || { FAILED+=("$ex"); continue; }

    ok=1
    DRIFT_THIS=0
    # 0. native pre-step — some examples (hello-native) ship a build_native.sh
    #    that compiles vendored [tool.kivy.*.native.binaries] before locking.
    if [[ -x "./build_native.sh" ]]; then
        run_step "native" ./build_native.sh || ok=0
    fi
    # 1. doctor — pre-flight; informational only (result shown, not gating).
    [[ $ok -eq 1 ]] && { run_step "doctor" kivyforge doctor -p "$PLATFORM" || \
        echo "    (doctor reported issues — continuing so you can inspect them)"; }
    # 2. clean
    [[ $ok -eq 1 ]] && { run_step "clean" kivyforge clean || ok=0; }
    # 3. lock (regenerate + verify against committed, then restore)
    [[ $ok -eq 1 ]] && { verify_lock_step || ok=0; }
    [[ $DRIFT_THIS -eq 1 ]] && DRIFTED+=("$ex")
    # 4. build
    [[ $ok -eq 1 ]] && { run_step "build" kivyforge build -p "$PLATFORM" || ok=0; }
    # 5. run (GUI, blocks until you close the window)
    if [[ $ok -eq 1 && $GUI -eq 1 ]]; then
        run_step "run" kivyforge run -p "$PLATFORM" || ok=0
    elif [[ $GUI -eq 0 ]]; then
        echo ">>> run: skipped (--no-gui)"
    fi
    # 6. package (macOS: signs .app in place; Linux: writes dist/linux/*.AppImage)
    [[ $ok -eq 1 ]] && { run_step "package" kivyforge package -p "$PLATFORM" || ok=0; }
    # 7. launch the packaged artifact (GUI)
    if [[ $ok -eq 1 && $GUI -eq 1 ]]; then
        launch_package_artifact || ok=0
    elif [[ $GUI -eq 0 ]]; then
        echo ">>> artifact: skipped (--no-gui)"
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
echo "  Summary ($PLATFORM)"
echo "============================================================"
echo "passed (${#PASSED[@]}): ${PASSED[*]:-none}"
echo "failed (${#FAILED[@]}): ${FAILED[*]:-none}"
[[ ${#SKIPPED[@]} -gt 0 ]] && echo "skipped (${#SKIPPED[@]}): ${SKIPPED[*]} (no [tool.kivy.$PLATFORM] overlay)"
if [[ ${#DRIFTED[@]} -gt 0 ]]; then
    echo "lock drift (${#DRIFTED[@]}): ${DRIFTED[*]}"
    echo "  ^ these committed pylock.$PLATFORM.toml files no longer match a fresh"
    echo "    resolve; re-lock and recommit them when you're ready."
fi

[[ ${#FAILED[@]} -eq 0 ]]
