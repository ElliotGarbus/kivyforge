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

## Addendum (2026-07-27): the other three iOS examples, and cleanup

Phase 6 as originally scoped in the plan only named `hello-kivy` and
`pyobjus-*` for the iOS side. That left `keychain-spm`, `mobile-geometry`,
and `svg-explorer` still on local `find_links = ["../../wheels/ios"]` — a
gap that `example-lock-policy-followup.md` incorrectly assumed was already
closed ("every mobile example now resolves from the index"). It wasn't;
`rg wheels/ios` still turned up `path = "../../wheels/ios/..."` entries in
all three examples' locks after the first pass above. Closed that gap here
rather than leave the tree in a mixed state.

Same treatment as the first three: swapped `find_links` for
`extra_index_urls` (plus the now-stale "Kivy 3.0 (pre-release) is vendored
under examples/wheels/ios" header comment, fixed in all four examples that
had it, including `hello-kivy`, which was missed in the first pass), ran
`kivyforge lock -p ios --update`, and verified programmatically:

| Example | Package set unchanged | Every Kivy/pyobjus wheel's sha256 unchanged |
|---|---|---|
| keychain-spm | yes (`Kivy`, `filetype`, `pyobjus`) | yes |
| mobile-geometry | yes (`Kivy`, `filetype`) | yes |
| svg-explorer | yes (`Kivy`, `certifi`, `charset-normalizer`, `filetype`, `idna`, `requests`, `urllib3`) | yes |

`svg-explorer` picked up newer PyPI releases of `certifi` (2026.6.17 →
2026.7.22) and `charset-normalizer` (3.4.7 → 3.4.9) — normal upstream drift
in `requests`' transitive deps from `--update`, unrelated to the wheel
source switch; the Kivy wheels' hashes were untouched.

On-device gate, all three built + ran on the simulator with wheels from the
index:

- **keychain-spm** — renders the Keychain demo UI ("Backend: iOS Keychain
  (KeychainAccess via @objc shim)") — this example also exercises Swift
  Package Manager resolution (`KeychainAccess`), unaffected by the Python
  wheel source change.
- **mobile-geometry** — renders the safe-area/DPI/scale readout overlay.
- **svg-explorer** — renders the SVG star with pinch/drag/twist controls —
  also confirms `requests` (from the index-repointed Kivy dependency graph,
  not excluded here unlike the other examples) still resolves correctly.

All 6 iOS mobile examples (`hello-kivy`, `pyobjus-ball`,
`pyobjus-deviceinfo`, `keychain-spm`, `mobile-geometry`, `svg-explorer`) now
resolve their Kivy/pyobjus wheels from the `kivy-mobile-wheels` index.
`examples/wheels/ios/` (the vendored `.whl` files plus its `.gitignore` /
`.gitkeep`) was deleted — nothing in the example tree references it anymore.
`examples/wheels/android/` (a sibling, unrelated to this phase) was left in
place.

Two remaining references to `examples/wheels/ios/` are intentionally kept:
`scripts/build_ios_wheels.sh` / `scripts/build_pyobjus_ios_wheels.sh` still
default their output there (now-superseded by the `kivy-mobile-wheels` CI
from Phase 4, but left as-is — deleting/updating the build scripts wasn't
part of this request); and the generic error-hint strings in
`kivyforge/lock/find_links.py` and
`kivyforge/platforms/ios/lock/builder.py` that mention
`examples/wheels/ios/` as an illustrative convention for library users, not
tied to this repo's example tree.

## Status

iOS half of Phase 6 complete: all six iOS examples resolve against
`kivy-mobile-wheels`' live Pages index, re-locked cleanly with unchanged
package sets and wheel hashes, and all six render correctly on the
simulator. `examples/wheels/ios/` has been removed. The Android half of
Phase 6 (`hello-android`, `pyjnius-deviceinfo`, `qr-maven`; Android emulator
+ Pixel 8a) ran on the Windows machine per the plan's hardware split and
landed separately (see `example-lock-policy-followup.md`).
