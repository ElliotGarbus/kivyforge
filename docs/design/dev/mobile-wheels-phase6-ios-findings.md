# Mobile wheels repo — Phase 6 findings, iOS half (macOS)

The iOS half of Phase 6 of
[`.cursor/plans/mobile-wheels-repo.plan.md`](../../../.cursor/plans/mobile-wheels-repo.plan.md):
repoint the iOS examples at the `kivy-mobile-wheels` index, re-lock, and
re-run the on-device gate. Run on the Mac, 2026-07-26, after Phase 4
(releases + CI-ported recipes) and Phase 5 (Pages index, landed concurrently
on the Windows machine — confirmed live before starting, see below).

## Pre-check: index is live

```
curl -fsSL https://elliotgarbus.github.io/kivy-mobile-wheels/simple/
```

Returned `kivy` and `pyobjus` project links; each project page listed all 3
slices with `#sha256=` fragments pointing at the `kivy-ios-3.0.0.dev0` /
`pyobjus-ios-1.2.4` Release assets. Confirmed live before touching any
example.

## Examples repointed

`examples/mobile/{hello-kivy, pyobjus-ball, pyobjus-deviceinfo}`: replaced

```toml
find_links = ["../../wheels/ios"]
```

with

```toml
extra_index_urls = ["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]
```

in each `[tool.kivy.ios]` table.

## Re-lock result

All three: `kivyforge lock -p ios --update` succeeded, 3 packages pinned
each.

**hello-kivy** (lock is committed — full diff):

```diff
 [[packages.wheels]]
 name = "kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphoneos.whl"
-path = "../../wheels/ios/kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphoneos.whl"
+url = "https://github.com/ElliotGarbus/kivy-mobile-wheels/releases/download/kivy-ios-3.0.0.dev0/kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphoneos.whl"
 hashes = { sha256 = "9bd343eb6493a010dbf5665bcbb8410f410f4739be2532366fab88e9ae9ae8a1" }
```

(same shape for the other two Kivy slices) plus the expected
`generated_at` / `pyproject_sha256` bump. **No sha256 changed for any
wheel** — only `path` → `url`.

**pyobjus-ball / pyobjus-deviceinfo**: their `pylock.ios.toml` is
`.gitignore`d in both examples (`pylock.*.toml`, regenerated on demand), so
there is no committed diff to show, but the same verification ran against
the working copy (see below) before it was discarded by the gitignore rule.
Both also picked up the iOS marker-fix dependency-edge shrink for Kivy (36 →
5 names) as a side effect, since their existing lock predated that fix
(2026-07-03) — unrelated to this phase, not a regression.

**Verified independently of the diff** (via `tomllib`, not by eyeballing the
diff) for all three examples:

| Example | Package set unchanged | Every wheel's sha256 unchanged |
|---|---|---|
| hello-kivy | yes (`Kivy`, `filetype`, `more-itertools`) | yes |
| pyobjus-ball | yes (`Kivy`, `filetype`, `pyobjus`) | yes |
| pyobjus-deviceinfo | yes (`Kivy`, `filetype`, `pyobjus`) | yes |

Only the source shape changed (`path` → `url` + `sha256`), exactly as the
repo's own README promises: *"kivyforge lock then resolves these wheels
exactly like any PyPI package... At install time kivyforge is unaffected
either way — the lock pins exact URLs and hashes."*

## On-device gate

All three built and ran on the iOS simulator (iPhone Air, iOS 26.5) with
wheels fetched from the new index rather than the local vendored path.

- **hello-kivy** — builds, launches, renders **"Hello Kivy"**. Identical to
  the pre-Phase-6 result in
  [`ios-validation-findings.md`](ios-validation-findings.md).
- **pyobjus-ball** — builds, launches, renders the bouncing-ball screen with
  "Accelerometer unavailable — drag to steer" (expected simulator fallback,
  not a defect) and an incrementing bounce counter — confirms the pyobjus
  wheel loads and its Objective-C bridge runs.
- **pyobjus-deviceinfo** — builds, launches, renders a live device-info panel
  ("Source: pyobjus -> UIDevice / NSProcessInfo") with real simulator values
  (model, OS version, memory, CPU core count, thermal state) — confirms
  pyobjus's ObjC calls work end-to-end with the wheel sourced from the
  index, not just that it imports.

**One methodology note, not a regression:** an early attempt at capturing
`kivyforge run`'s output with shell-level `&` backgrounding (rather than the
tool's own backgrounding) caused the launched process to be reaped before it
reached "Launching …", which showed up as the simulator bouncing back to the
home screen. Re-running the identical command through proper backgrounding
reached "Launching …" and rendered correctly on the first attempt — this was
an artifact of how the process was invoked, not a switch-related issue
(confirmed separately by launching the already-installed app directly via
`xcrun simctl launch`, which also rendered correctly).

## Not done in this phase

`examples/wheels/ios/*.whl` (the vendored wheels) are now unused by these
three examples but were not deleted — Phase 6 as scoped is about repointing
and re-validating, not cleanup. Removing them (and the `find_links`
convention they supported) is a reasonable follow-up once nothing else in
the repo still depends on the local path.

## Status

iOS half of Phase 6 complete: all three iOS examples resolve against
`kivy-mobile-wheels`' live Pages index, re-locked cleanly with unchanged
package sets and wheel hashes, and all three render correctly on the
simulator. The Android half of Phase 6 (`hello-android`,
`pyjnius-deviceinfo`; Android emulator + Pixel 8a) is out of scope here — it
runs on the Windows machine per the plan's hardware split.
