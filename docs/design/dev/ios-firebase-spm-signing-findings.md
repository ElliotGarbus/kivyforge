# Findings — Firebase SPM signing, and why the earlier fix was insufficient

Run 2026-09-21 on the Mac, prompted directly by a user request ("lets try
firebase") to verify commit `56ca1730` ("iOS: propagate signing settings to
the project level, fixing SPM packages") against the real package the
original bug report used, rather than only the hermetic tests added with it.

**Headline: the earlier fix does not actually fix the reported bug.** It is
harmless and correct as far as it goes, but reproducing the real Firebase
package proves it is not sufficient — a second, previously-undiscovered
mechanism was needed. That second fix is what actually resolves the bug and
is the one that matters; details below.

## Environment

| | |
|---|---|
| macOS | 26.6.2 (build 25G83) |
| Xcode | 26.6 (build 17F113) |
| kivyforge | 3.0.0.dev0, at commit `56ca1730` |
| Example | `examples/mobile/hello-kivy`, with a temporary `[tool.kivy.ios.native.swift_packages]` entry for `Firebase` (`https://github.com/firebase/firebase-ios-sdk`, `products = ["FirebaseCore"]`) — not committed, matching the example-repo lock policy |
| Package resolved | `firebase-ios-sdk` 11.15.0 (`from = "11.0.0"`), pulling in 13 further packages (GoogleUtilities, GoogleAppMeasurement, grpc-binary, abseil-cpp-binary, nanopb, etc.) |
| Team | a real Apple Development team (`R5PKSQLUZY`), via `KIVYFORGE_TEAM_ID` |

Baseline: `pytest -q` (92.80% coverage), `ruff check`/`ruff format --check`,
and `pyright` (0 errors) all clean before and after this work.

## Step 1 — does the already-shipped fix actually work?

`kivyforge lock -p ios --update` resolved and pinned Firebase correctly.
`kivyforge build -p ios --device` with `KIVYFORGE_TEAM_ID=R5PKSQLUZY` set —
i.e. exactly the fixed code path from commit `56ca1730` — reproduced the
*exact* error from the original report:

```
.../firebase-ios-sdk/Package.swift: error: Signing for "Firebase_FirebaseCore"
  requires a development team. Select a development team in the Signing &
  Capabilities editor. (in target 'Firebase_FirebaseCore' from project 'Firebase')
```

...plus the same error for three `GoogleUtilities_*` resource-bundle targets.
Confirmed via `pbxproj` that `DEVELOPMENT_TEAM=R5PKSQLUZY` *was* present, as
designed, in both the app target's and the project's own build
configurations. The fix landed exactly as coded — and the bug it was meant
to fix still reproduced.

## Step 2 — a second hypothesis: `PBXProject.attributes.TargetAttributes`

Xcode's "Signing & Capabilities" tab writes to a different place than the
"Build Settings" tab: `PBXProject.attributes.TargetAttributes[<target
id>].DevelopmentTeam`/`.ProvisioningStyle`, not `XCBuildConfiguration.buildSettings`.
Inspecting the generated project showed `TargetAttributes = {}` — completely
empty; kivyforge had never written this at all.

Patched it directly (via `pbxproj`) and rebuilt with plain `xcodebuild`
(reusing the already-resolved package checkouts). **Still failed, identically.**
This mechanism was not it either — `TargetAttributes` governs the *consuming*
project's own Signing & Capabilities UI state, not the signing resolution
applied to a synthesized Swift Package sub-project's targets.

## Step 3 — the real mechanism: `DEVELOPMENT_TEAM` as an `xcodebuild` argument

`CODE_SIGN_IDENTITY` was already being passed as an `xcodebuild`
command-line override (`build_command`/`archive_command` in
`kivyforge/platforms/ios/xcode/commands.py`), separately from whatever is
baked into the `.pbxproj`. Passing `DEVELOPMENT_TEAM=<team>` the same way —

```
xcodebuild ... "CODE_SIGN_IDENTITY=Apple Development" "DEVELOPMENT_TEAM=R5PKSQLUZY" \
  -allowProvisioningUpdates build
```

— **worked immediately**: every one of the previously-failing package
targets (`Firebase_FirebaseCore`, `Firebase_FirebaseCoreInternal`, three
`GoogleUtilities_*` bundles) built and signed without error. The remaining
failure at that point (`The file "FirebaseCore" couldn't be opened`) was an
unrelated mistake in the test's own package declaration — `FirebaseCore` is
a static-library product, not an embeddable `.framework`, so the test's
`embed = true` was wrong; `embed = false` (still `link = true`) fixed it.

**Conclusion:** Xcode builds a Swift Package's own targets as a separate,
synthesized sub-project that reads neither the consuming project's baked
`buildSettings` nor its `TargetAttributes` — only command-line-level build
setting overrides propagate to it, the same way Xcode's own IDE (which
always builds via its own equivalent of command-line overrides layered on
top of the project) manages to get this right silently.

## Fix shipped this session

- `build_command()` and `archive_command()` in
  `kivyforge/platforms/ios/xcode/commands.py` now accept `team_id` and pass
  it as `DEVELOPMENT_TEAM=<team_id>` on the `xcodebuild` command line,
  alongside the existing `CODE_SIGN_IDENTITY` override — for `--device`
  builds and `--release` archives (not `--simulator`, which is unsigned).
- `cli.py`'s `_xcodebuild_step7` (used by both `build` and `package`) and
  `ios_run`'s own build call now thread the already-resolved `team_id`
  through to these functions. `ios_run` had the identical gap independently
  (it computed `resolved_team_id` for `prepare_build` but never passed it to
  its own `build_command` call, and was also missing `signing_identity` and
  `allow_provisioning_updates` entirely) — fixed the same way for
  consistency, though it was not the path the original report exercised.
- The earlier commit's project-level `buildSettings` fix is **kept**: it is
  correct and harmless for the app's own target (matches what Xcode's UI
  does), just not sufficient on its own for a package with a signable
  target. `CHANGELOG.md`'s entry for `56ca1730` has been corrected to
  describe the actual, verified fix rather than the original, incomplete
  claim.
- Added `TestBuildCommand`/`TestArchiveExport` regression tests in
  `tests/platforms/ios/xcode/test_commands.py` asserting `team_id` produces
  `DEVELOPMENT_TEAM=...` on device/archive commands, is absent by default,
  and is ignored for `--simulator`.

## Verification

- Real end-to-end repro: `kivyforge build -p ios --device` with the fixed
  code, the real `firebase-ios-sdk` package (`FirebaseCore` product,
  `link = true`, `embed = false`), and `KIVYFORGE_TEAM_ID` set — succeeded:
  `Built hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphoneos/hello-kivy.app`.
- `codesign -dv` on the resulting `.app` confirms it's signed with the
  expected `Apple Development` identity.
- Regression check: rebuilt with the identical project but *without* the
  `DEVELOPMENT_TEAM` command-line override (project-level `buildSettings`
  fix still in place) — the original error reproduced, 5 instances, proving
  the command-line override is the load-bearing piece.
- `pytest -q` (92.80%), `ruff check`, `ruff format --check`, `pyright` (0
  errors) all clean.
- Cleanup: `examples/mobile/hello-kivy/pyproject.toml` and `pylock.ios.toml`
  restored byte-for-byte to their committed state; `hello-kivy-ios/`
  (gitignored) removed. `git status` clean before committing this fix.

## Summary

| Hypothesis | Result |
|---|---|
| Project-level `buildSettings.DEVELOPMENT_TEAM` (commit `56ca1730`) | Insufficient — reproduced the bug against real Firebase |
| `PBXProject.attributes.TargetAttributes[...].DevelopmentTeam` | Insufficient — reproduced the bug identically |
| `DEVELOPMENT_TEAM=<team>` as an `xcodebuild` command-line override | **Fixed it** — real device build with Firebase succeeds and is properly signed |

The lesson for this codebase: a Swift Package's own targets are built by
Xcode as an independent sub-project, invisible to and uninfluenced by
anything written into the consuming project's `.pbxproj`. Any signing
setting that needs to reach package targets must go out as an `xcodebuild`
argument, matching how `CODE_SIGN_IDENTITY` was already handled — a pattern
worth remembering before adding another `.pbxproj`-only "fix" for a
package-graph signing failure in the future.

## Follow-up (same day) — a second, independent Firebase footgun: `embed` defaults to `true`

A second user report against the same underlying `kivyforge` version, this
time on `FirebaseAuth`:

```
Copy .../test-kivyforge.app/Frameworks/FirebaseAuth-product /.../Debug-iphoneos/FirebaseAuth-product
error: The file "FirebaseAuth-product" couldn't be opened because there is no such file.
```

This is **not** a signing issue and the fix above does not touch it.
Reproduced with the real `FirebaseAuth` product and the *default* `embed`
setting (unset in `pyproject.toml`, which `[tool.kivy.ios.native.swift_packages]`
defaults to `true`):

```
Copy .../hello-kivy.app/Frameworks/FirebaseAuth /.../Debug-iphoneos/FirebaseAuth
error: The file "FirebaseAuth" couldn't be opened because there is no such file.
```

Same error class (Xcode's exact spelling — with or without a `-product`
suffix — is not meaningful). Root cause: a Swift Package **product** is
`automatic`, `static`, or `dynamic`; `library`-type products with no explicit
`type:` (the common case, including every Firebase product) are `automatic`,
which Xcode resolves to **static** for a standalone consuming target — there
is no `.framework` file for the Embed Frameworks / Copy Files phase to copy.
`kivyforge` has no way to know this ahead of `xcodebuild` (it does not run
`swift package dump-package`), so `embed = true`'s default silently fails at
`xcodebuild build` for any static product, which in practice means most
third-party SPM packages, not just Firebase's.

Confirmed the fix: adding `embed = false` (keeping the `link = true`
default) and re-locking — the identical project builds and succeeds. No
code fix was made for this (there is no reliable way for kivyforge to
detect a product's declared library type without adding a
`dump-package`-based lock-time check, which is a real feature, not a small
one); `docs/design/platforms/ios/06-swift-packages.md`'s `embed` field
documentation was rewritten with a prominent warning and a worked Firebase
example, since the *existing* default was only ever validated against one
real remote package (`Sentry`, the doc's own worked example, which is
presumably genuinely dynamic) and silently does the wrong thing for the
common static case.

**Possible follow-up (not implemented):** run `swift package dump-package`
against each resolved package at `kivyforge lock` time and fail with an
actionable `KF-ERROR` when `embed = true` (default or explicit) is paired
with a product whose declared type is not `dynamic`, catching this at `lock`
time with a clear message instead of at a confusing `xcodebuild` failure.
Flipping the *global* default to `false` was considered and rejected: the
doc's own worked example (`Sentry`) and `keychain-spm`'s local shim
(`KeychainBridge`, deliberately declared `type: .dynamic` in its own
`Package.swift` specifically to use this default) both rely on `embed = true`
working, and a wrong default in that direction fails silently at runtime
(`dyld: Library not loaded`) rather than loudly at build time — arguably a
worse failure mode to default into.
