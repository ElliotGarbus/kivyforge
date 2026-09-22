# Findings — `KIVYFORGE_REQUIRES_SDL` validation on real Xcode

Run 2026-09-21 on the Mac, per
[`ios-requires-sdl-validation-prompt.md`](ios-requires-sdl-validation-prompt.md).
Scope: only the `KIVYFORGE_REQUIRES_SDL` compile-time guard, as instructed —
`KIVYFORGE_HEADLESS_UIKIT` was not touched.

## Environment

| | |
|---|---|
| macOS | 26.6.2 (build 25G83) |
| Xcode | 26.6 (build 17F113) |
| Swift | 6.3.3 (swiftlang-6.3.3.1.3, clang-2100.1.1.101) |
| kivyforge | 3.0.0.dev0, at commit `e754ee11` ("Add a validation prompt for
  KIVYFORGE_REQUIRES_SDL on real Xcode"); target fix commit `fd33ea36` ("iOS:
  fail the build at compile time when a Kivy app is missing SDL3") |
| Simulator | iOS 26.5 runtime |
| Examples | `examples/mobile/hello-kivy` (Kivy app, has SDL3), `examples/mobile/hello-world` (no dependencies, no SDL3) |

Baseline: `pytest -q` (92.79% coverage) and `pyright` (0 errors) both clean
before this run.

## Step 1 — baseline: a real Kivy build gets the flag and still succeeds

```
kivyforge doctor -p ios   → all PASS/expected WARN (no final CPython 3.15,
                             xcframework privacy manifests) — unchanged from
                             every prior run of this example.
kivyforge build  -p ios --simulator  → succeeded, "Built .../hello-kivy.app"
```

```
$ grep -A2 'GCC_PREPROCESSOR_DEFINITIONS' hello-kivy-ios/hello-kivy.xcodeproj/project.pbxproj
				GCC_PREPROCESSOR_DEFINITIONS = "$(inherited) KIVYFORGE_REQUIRES_SDL=1";
				GCC_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER = NO;
				HEADER_SEARCH_PATHS = "... SDL3.framework/Headers ...";
--
				GCC_PREPROCESSOR_DEFINITIONS = "$(inherited) KIVYFORGE_REQUIRES_SDL=1";
				GCC_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER = NO;
				HEADER_SEARCH_PATHS = "... SDL3.framework/Headers ...";
```

**Result: PASS.** `KIVYFORGE_REQUIRES_SDL=1` is present, alongside
`$(inherited)`, on both the Debug and Release configurations, and the build
succeeds normally.

## Step 2 — the actual proof: break SDL3 visibility, expect a compile failure

`Frameworks/SDL3.xcframework/ios-arm64_x86_64-simulator/SDL3.framework/Headers`
was renamed to `Headers.bak` directly on the already-generated project (no
`pyproject.toml` edit, no re-run of `kivyforge build`), then built directly
with `xcodebuild`:

```
xcodebuild -project hello-kivy.xcodeproj -scheme hello-kivy \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' build
→ exit 65, ** BUILD FAILED **
```

The literal `#error` text, verbatim from `/tmp/requires-sdl-build.log`, fired
for **both** simulator-slice compiles (arm64 and x86_64) as the first and
only substantive error — nothing else preceded it:

```
/Users/.../hello-kivy-ios/kivyforge_bootstrap.m:38:2: error: "Kivy app selected (KIVYFORGE_REQUIRES_SDL) but SDL3 headers were not found. Check that SDL3.xcframework is embedded and HEADER_SEARCH_PATHS includes it."
   38 | #error "Kivy app selected (KIVYFORGE_REQUIRES_SDL) but SDL3 headers were not found. Check that SDL3.xcframework is embedded and HEADER_SEARCH_PATHS includes it."
```

(repeated once per arch; `** BUILD FAILED **` on line 165 of the log.)

**Result: PASS.** The guard fires exactly as designed, with exactly the
message the template promises, and nothing else masks or precedes it.

### Restore, and an unrelated wrinkle in the restore-verification step

`Headers.bak` was renamed back to `Headers`. Re-running the *exact* command
the prompt specifies for the "confirm healthy again" check —

```
xcodebuild -project hello-kivy.xcodeproj -scheme hello-kivy \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' build
```

— now compiles cleanly (the `#error` guard is silent, as expected) but then
**fails later, in a run-script phase, for a reason that has nothing to do
with this change**:

```
rsync(94637): error: .../Python.xcframework/ios-arm64_x86_64-simulator/lib-arm64 x86_64/: (l)stat: No such file or directory
** BUILD FAILED **
```

Reproduced identically on a second run, so it's not a fluke. Root cause: a
bare `xcodebuild ... -destination 'generic/platform=iOS Simulator' build`
(with no `ARCHS=` override) builds a **universal** arm64+x86_64 binary for
one destination, and python.org's own `install_stdlib` script layers its
per-arch libs under a directory literally named `lib-$ARCHS` — which for a
multi-arch build resolves to the single, invalid path `lib-arm64 x86_64`
(note the space) rather than iterating `lib-arm64` and `lib-x86_64`
separately. **This is not new and not caused by this change** —
`kivyforge/platforms/ios/xcode/commands.py` already documents and works
around exactly this, in a comment that predates this session:

```python
# python.org's install_stdlib uses lib-$ARCHS; a universal simulator build
# (arm64 x86_64) produces an invalid path. Pin a single arch for CLI builds.
if target == "simulator":
    cmd += [f"ARCHS={arch or default_simulator_arch()}", "ONLY_ACTIVE_ARCH=NO"]
```

`kivyforge build` always passes this pin; the prompt's Step 2 restore-check
command does not, because it calls `xcodebuild` directly rather than through
`kivyforge`. The failure case in Step 2 above never hit this, because the
`#error` aborts compilation before the run-script phase is ever reached —
only the *restore* check reaches far enough to trip it.

Verified the restore is actually healthy via the real path a user exercises
(`kivyforge build -p ios --simulator`, which pins `ARCHS`): succeeded,
`Built hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/hello-kivy.app`.
`git status` clean afterward — nothing generated was committed.

**Conclusion:** the guard's restore path is healthy; the prompt's suggested
raw-`xcodebuild` restore command is not a reliable way to verify it, for a
reason unrelated to `KIVYFORGE_REQUIRES_SDL` and already known/worked-around
elsewhere in the codebase. No code change made for this — it isn't a new
defect, just a gap in the validation recipe.

## Step 3 — regression check: a non-Kivy app never gets the flag

`hello-world` has no dependencies (`kivyforge lock -p ios` on it: "Wrote
pylock.ios.toml (0 packages pinned)" — no lock existed yet, so it was
generated fresh; not committed, matching the non-gate-example lock policy).

```
kivyforge build -p ios --simulator   → succeeded, "Built .../hello-world.app"
grep 'GCC_PREPROCESSOR_DEFINITIONS' hello-world-ios/hello-world.xcodeproj/project.pbxproj
→ (no output; grep exit 1 — the key is entirely absent, not present-but-empty)
```

**Result: PASS.** A dependency-free app builds via the headless path exactly
as before and never gets the SDL3 macro.

## Cleanup

`git status --short` at the repo root: clean, before and after. Nothing
generated (`hello-kivy-ios/`, `hello-world-ios/`, either example's
`pylock.ios.toml`) is tracked or was committed.

## Summary

| Check | Result |
|---|---|
| Kivy app gets `KIVYFORGE_REQUIRES_SDL=1`, builds normally | PASS |
| Guard fires with the exact `#error` text when SDL3 headers are missing | PASS |
| Guard is silent again once headers are restored (verified via `kivyforge build`) | PASS |
| Non-Kivy app never gets the macro | PASS |
| Unrelated finding | Bare `xcodebuild -destination 'generic/platform=iOS Simulator'` (no `ARCHS=` pin) hits the pre-existing, already-documented `lib-$ARCHS` limitation in the run-script phase — not a `KIVYFORGE_REQUIRES_SDL` defect |

`KIVYFORGE_REQUIRES_SDL` is validated against real Xcode: it fires exactly
when it should, stays silent exactly when it should, and the earlier
hermetic-only coverage (`test_buildsettings.py`, `test_plist_sources.py`) now
has a real-compile counterpart.
