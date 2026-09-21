# Agent prompt — validate `KIVYFORGE_REQUIRES_SDL` on the Mac

> **Run this on the Mac**, from the repo root of `main`. Written 2026-09-22
> from the Windows host, where none of it can run — this needs a real
> `xcodebuild` compile, which only hermetic template/settings tests stood in
> for so far.
>
> Point the agent at this file, or copy the "Prompt" section.
>
> Scope: **only** the `KIVYFORGE_REQUIRES_SDL` compile-time guard. The other
> idea from PR #1 (`KIVYFORGE_HEADLESS_UIKIT`) is a separate, not-yet-agreed
> follow-up — do not touch it here.

## Background — what changed and why this needs a real compile

`kivyforge_bootstrap.m` gained a compile-time guard:

```c
#if defined(KIVYFORGE_REQUIRES_SDL) && !__has_include(<SDL3/SDL_main.h>)
#error "Kivy app selected (KIVYFORGE_REQUIRES_SDL) but SDL3 headers were not found. Check that SDL3.xcframework is embedded and HEADER_SEARCH_PATHS includes it."
#endif
```

`kivyforge/platforms/ios/buildsettings.py`'s `managed_settings()` sets
`GCC_PREPROCESSOR_DEFINITIONS = "$(inherited) KIVYFORGE_REQUIRES_SDL=1"`
whenever `SDL3.xcframework` is staged (`_sdl3_staged()`, the same check
`HEADER_SEARCH_PATHS` already used) — so a Kivy app that somehow loses its
SDL3 headers after project generation (a broken vendoring step, a manually
edited `HEADER_SEARCH_PATHS`) should now fail to **compile**, with the error
above, instead of silently building the headless (windowless) fallback path.

**Everything about this has only been hermetically tested so far**
(`tests/platforms/ios/test_buildsettings.py`, `test_plist_sources.py`): that
the Python side writes the right build setting, and that the `#error` text
exists in the template. Nobody has actually asked `clang` to fail on this,
or confirmed a real Kivy build still succeeds with the flag present. That's
what this prompt is for. Credit for the idea: PR #1 (kengoon).

---

## Prompt

You are validating `KIVYFORGE_REQUIRES_SDL` against real Xcode. The
environment is already set up. Prove the guard fires when it should and
stays silent when it shouldn't — don't just re-read the diff.

### Step 0 — environment and pull

```bash
git pull                      # you need the commit titled "iOS: fail the
                               # build at compile time when a Kivy app is
                               # missing SDL3" or later, on main
xcodebuild -version; swift --version
.venv/bin/kivyforge --version
```

### Step 1 — baseline: a real Kivy build gets the flag and still succeeds

```bash
cd examples/mobile/hello-kivy
../../../.venv/bin/kivyforge doctor -p ios
../../../.venv/bin/kivyforge build  -p ios --simulator
```

Expected: builds successfully, same as every prior run of this example.

Then confirm the flag actually landed in the generated project (not just
that the build happened to pass):

```bash
grep -A2 'GCC_PREPROCESSOR_DEFINITIONS' hello-kivy-ios/hello-kivy.xcodeproj/project.pbxproj
```

Expected: `KIVYFORGE_REQUIRES_SDL=1` present (alongside `$(inherited)`), on
both the Debug and Release configurations.

### Step 2 — the actual proof: break SDL3 visibility, expect a compile failure

Don't touch `pyproject.toml` or re-run `kivyforge build` for this step —
that would just re-stage a working `SDL3.xcframework` and prove nothing.
Instead, simulate a broken vendoring step directly on the already-generated
project, exactly the scenario the guard exists for:

```bash
cd hello-kivy-ios
SLICE=Frameworks/SDL3.xcframework/ios-arm64_x86_64-simulator/SDL3.framework
mv "$SLICE/Headers" "$SLICE/Headers.bak"

xcodebuild -project hello-kivy.xcodeproj -scheme hello-kivy \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  build 2>&1 | tee /tmp/requires-sdl-build.log
```

Expected: **the build fails**, and `/tmp/requires-sdl-build.log` contains the
exact `#error` text: *"Kivy app selected (KIVYFORGE_REQUIRES_SDL) but SDL3
headers were not found..."* — not some other, unrelated compile error (if
it's a different failure, e.g. a linker error instead of the `#error`
tripping first, that's a real finding: capture it in full).

Restore and confirm the build is healthy again:

```bash
mv "$SLICE/Headers.bak" "$SLICE/Headers"
xcodebuild -project hello-kivy.xcodeproj -scheme hello-kivy \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  build 2>&1 | tail -20
cd ..
git status                                  # must be clean — nothing here should be committed
```

### Step 3 — regression check: a non-Kivy app never gets the flag

`hello-world` (`examples/mobile/hello-world`) has no dependencies at all —
no SDL3.xcframework is ever staged for it, so it must not get the macro and
must keep building via the headless path exactly as before.

```bash
cd ../hello-world
../../../.venv/bin/kivyforge build -p ios --simulator
grep 'GCC_PREPROCESSOR_DEFINITIONS' hello-world-ios/hello-world.xcodeproj/project.pbxproj
```

Expected: builds successfully, and the grep finds nothing (the key should be
entirely absent from this project, not present-but-empty).

### Step 4 — report

Write findings to `docs/design/dev/ios-requires-sdl-validation-findings.md`:
an environment table (Xcode/Swift versions), then Steps 1–3's actual output
(the `#error` log excerpt from Step 2 is the important artifact — include it
verbatim). Then update `docs/design/dev/roadmap.md`'s `entry_point`/PR #1
item (or add a short note near it) with the real result — search for
"KIVYFORGE_REQUIRES_SDL" or "PR #1" to find the right spot.

### Rules of engagement

- Record what you **observed**, including the literal build log excerpt for
  the failure case — "it failed as expected" without the actual error text
  is not evidence.
- Everything in Step 2 is temporary. Confirm `git status` is clean before
  moving on to Step 3, and again at the end.
- Do not touch `KIVYFORGE_HEADLESS_UIKIT` or propose implementing it here —
  that's a separate, not-yet-agreed follow-up.
- Commit only the findings doc (and any roadmap update) on `main`. **Do not
  push without asking.**
