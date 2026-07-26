# Mobile wheels repo — Phase 0 inventory (macOS)

Phase 0 of [`.cursor/plans/mobile-wheels-repo.plan.md`](../../../.cursor/plans/mobile-wheels-repo.plan.md):
inventory the existing `examples/wheels/ios/` wheels *before* rebuilding
anything. Run on the Mac, 2026-07-26.

## Result: all 6 wheels are usable as-is — no rebuild needed for the first Release

| File | sha256 | Size | Already pinned in |
|---|---|---|---|
| `kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphoneos.whl` | `9bd343eb6493a010dbf5665bcbb8410f410f4739be2532366fab88e9ae9ae8a1` | 19M | `examples/mobile/hello-kivy/pylock.ios.toml` |
| `kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl` | `c5dd880917ca53d52bfb9867d22636d2aba5651e22e8c21ec7756ccdc308fe91` | 24M | `examples/mobile/hello-kivy/pylock.ios.toml` |
| `kivy-3.0.0.dev0-cp315-cp315-ios_13_0_x86_64_iphonesimulator.whl` | `1fde7d1afa462efab3c598cd7fb31dcbdc27e65270348444a7bb07f01dd6f31d` | 24M | `examples/mobile/hello-kivy/pylock.ios.toml` |
| `pyobjus-1.2.4-cp315-cp315-ios_13_0_arm64_iphoneos.whl` | `f8833074f6493cc9fa25259180ca8aa36c961b0901d5f0c58546612e5a208ac7` | 280K | `examples/mobile/pyobjus-ball`, `pyobjus-deviceinfo` |
| `pyobjus-1.2.4-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl` | `edbcb6866c2696eb01815789765dcb2fc56032de468e448ec936370f907e1405` | 284K | `examples/mobile/pyobjus-ball`, `pyobjus-deviceinfo` |
| `pyobjus-1.2.4-cp315-cp315-ios_13_0_x86_64_iphonesimulator.whl` | `ddc92fa36049d816aa13a5efef37927e2bedea459c692c628254bbe5e93633ef` | 300K | `examples/mobile/pyobjus-ball`, `pyobjus-deviceinfo` |

Every sha256 above matches the hash already recorded in the corresponding
example's committed lock file exactly — computed independently via
`shasum -a 256`, not read from the locks. These 6 files can become the first
Release's assets without a rebuild.

## Bonus: exact build provenance recovered

`scripts/build_ios_wheels.sh` and `scripts/build_pyobjus_ios_wheels.sh` cache
their upstream checkouts under `.build/ios-wheels/{kivy,pyobjus}/`. Those
checkouts were untouched since the wheels were built (checkout mtimes match
the wheel mtimes, June 29), so `git log -1` on each gives the exact commit
that produced the vendored wheels — not inferred, read directly:

| Recipe | Repo | Commit | Date | Message |
|---|---|---|---|---|
| iOS Kivy 3.0/SDL3 | `kivy/kivy` | `a933f859b4d0add7267798ffba5abb1a456da7f4` | 2026-06-22 | "Update actions/checkout action to v7 (#9333)" |
| iOS pyobjus | `kivy/pyobjus` | `0c229e75248c14652b6764db5730eeb30bab95ed` | 2025-12-29 | "Centralize CI/CD deps to a single requirements file, add `twine` as dependency (#139)" |

These are ready to drop directly into `recipes/PINNED_REFS.toml`'s
`[ios.kivy_3_0_sdl3]` and `[ios.pyobjus]` entries once Phase 1 (repo
scaffolding) creates that manifest — no need to re-resolve `git ls-remote`
for the *first* pin, since these commits are what's actually already built
and verified running on-device (see
[`ios-validation-findings.md`](ios-validation-findings.md)).

## Status / next step

Phase 0 is complete. Phase 4 (port the build scripts into the new repo's CI)
and the iOS half of Phase 6 remain blocked on Phase 1 (repo scaffolding,
including resolving the repo name — an explicitly open item in the plan),
which has not run on either machine yet.
