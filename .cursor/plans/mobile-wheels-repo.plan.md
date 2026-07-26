# Mobile wheels repo: plan (not started — pick up next session)

**Status:** planning only. No repo created, no CI written, no wheels built or
published under this plan yet. `gh` is authenticated as `ElliotGarbus` locally,
so repo creation can happen directly from a terminal next session — no manual
GitHub UI step needed.

## Why this exists

kivyforge consumes prebuilt Android and iOS wheels for packages that don't
publish mobile wheels of their own (Kivy, pyjnius, pyobjus). Today those wheels
live as loose local files on whichever machine built them (my WSL box for
Android, the user's Mac for iOS), gitignored out of the kivyforge repo, pinned
into lock files by local `path =`. That's fragile (single machine, no backup,
no audit trail) and doesn't match the shape a real PyPI-hosted wheel will
eventually have (`url` + `sha256`).

This is a **bridge**: a personally-owned GitHub repo that builds these wheels
reproducibly in CI, hosts them on GitHub Releases, and serves a PEP 503 static
index over GitHub Pages — so `kivyforge lock` resolves them exactly like any
PyPI package via `extra_index_urls` (already-existing kivyforge config, zero
new kivyforge code required). Retire this the day Kivy/pyjnius/pyobjus publish
`android_*`/`ios_*` wheels on PyPI themselves.

## Decisions locked in this conversation

| Decision | Answer |
|---|---|
| Scope | Android **and** iOS |
| Android Kivy/SDL | Kivy 2.3.1 / SDL2 (already built+verified) **and** Kivy 3.0.dev / SDL3 (not yet built — see risks) |
| iOS Kivy/SDL | Kivy 3.0.dev / SDL3 only — kivyforge's iOS design drops SDL2 entirely (`kivy 3.x drops SDL2; these stay on kivy-ios 2.x`, `docs/design/platforms/ios/07-recipe-triage.md:21`). No Kivy-2.3.1-on-iOS wheel is in scope. |
| Java-bridge wheel | pyjnius, Android — **already built and verified**, first-party cibuildwheel recipe exists (`docs/design/dev/android-wheel-build-recipe.md`) |
| ObjC-bridge wheel | **pyobjus**, iOS (not real PyObjC — confirmed by user; pyobjus is Kivy's own bridge, already referenced in `examples/mobile/pyobjus-*`) |
| Ownership | Personal (`ElliotGarbus`), not the Kivy org, not yet |
| Lifetime | Bridge. README must say so and name the retirement condition (PyPI mobile wheels from upstream) |
| Hosting | GitHub Releases (binaries) + GitHub Pages (PEP 503 static simple index) — see mechanism below |

## What already exists to build on (found this session, not previously known)

This is the single biggest thing that changes the plan: **iOS is much further
along than assumed.** Two working build scripts already live in the kivyforge
repo root:

- **`scripts/build_ios_wheels.sh`** — builds Kivy cp315 iOS wheels. Explicitly
  "mirrors kivy/kivy `.github/workflows/ios_wheels.yml`": clones `kivy/kivy`
  master, runs Kivy's own `tools/build_ios_dependencies.sh` (builds SDL3 +
  ANGLE + ThorVG xcframeworks), cibuildwheel with `CIBW_PLATFORM=ios`,
  3 slices (`arm64_iphoneos arm64_iphonesimulator x86_64_iphonesimulator`),
  `cp315-*` only, then `tools/add-ios-frameworks.py` grafts the xcframeworks
  into the wheel. This is the (previously undocumented, as far as I could
  find) provenance of the Kivy 3.0 iOS wheel `hello-kivy` already locks
  against.
- **`scripts/build_pyobjus_ios_wheels.sh`** — same shape, clones `kivy/pyobjus`
  master, builds libffi via pyobjus's own `.ci/build_ios_dependencies.sh`,
  cibuildwheel, same 3 slices, `cp315-*`. Its own header comment says
  **"pyobjus has no iOS CI yet, so this exact cibuildwheel-iOS path is not
  upstream-validated"** — treat the first CI run as the real test, not a
  formality.
- Both scripts already anticipate a CI variant: the local-run guard ("cibuildwheel
  refuses to sudo-install outside CI") implies a CI environment is expected to
  `sudo installer` the CPython 3.15 macOS framework automatically rather than
  stopping to ask.
- The macOS validation run (`docs/design/dev/ios-validation-findings.md`,
  Step 3) found **`find_links (../../wheels/ios, 6 wheels)`** on the user's
  Mac — almost certainly the 3 Kivy slices + 3 pyobjus slices already built
  locally by these scripts, just never hashed, backed up, or published
  anywhere. **First action next session: inventory those 6 files (name +
  sha256) before rebuilding anything** — they may be usable as-is for the
  first Release.

Android has no equivalent committed scripts — the SDL2 + Kivy 2.3.1 + pyjnius
recipe exists only as prose (`docs/design/dev/android-wheel-build-recipe.md`)
plus my own WSL scratchpad shell scripts (`~/kivywheel/*.sh`, never committed
anywhere). Porting those into real, committed scripts — mirroring the shape of
`build_ios_wheels.sh` — is part of the Android phase below.

## Real open risk: Android Kivy 3.0 / SDL3

This is the **only** wheel target in scope with no existing proof it works at
all. The Android compatibility matrix already flags it: *"tier-1
`SDL_GetAndroidJNIEnv` path is identical by construction to the SDL2 path, but
not yet exercised"* (Pending). Unlike SDL2 (no Android binary, built 4
libraries from source per the verified recipe), SDL3 publishes an official
prebuilt `SDL3-devel-<ver>-android.zip`, which should be cheaper — but that
convenience is unverified for the two things that actually matter here:

- **16 KB page alignment.** The SDL2 recipe needed an explicit
  `-Wl,-z,max-page-size=16384` because NDK r27 doesn't default to it. Whether
  SDL3's official prebuilt zip already ships 16 KB-aligned `.so`s, or needs the
  same re-link/patch step, is unknown until checked.
- **Kivy 3's actual build-time env var contract for SDL3 on Android.** The
  proven Android recipe's `KIVY_SDL2_PATH` workaround (cibuildwheel overriding
  `PKG_CONFIG_LIBDIR`) was reverse-engineered from Kivy 2.3.1's `setup.py`.
  Kivy 3's `setup.py` almost certainly has a different (or renamed) variable
  for SDL3 discovery on Android — needs reading, not assuming.

Budget this phase as real investigation, not a mechanical port. It also has a
kivyforge-side dependency once the wheel exists: `templates/sdl3/` doesn't
exist yet and `render_bootstrap(sdl=3)` currently raises `RenderError` — that's
kivyforge work, not this repo's, but it's what makes the wheel usable
end-to-end. Flag as a follow-up, don't fold into this repo's scope.

## Decision: pin every non-tagged recipe to an exact commit

Confirmed. Every recipe that clones a git ref instead of downloading a
tagged/versioned release gets pinned to an exact commit SHA, recorded in the
repo, never resolved silently at build time. This is the same "fail loud,
don't float" principle already applied to the pip marker shim this session —
worth being consistent about.

**Which recipes actually need this** (re-checked while updating this section —
pyjnius turns out to have the identical problem, missed in the first pass):

- iOS Kivy 3.0/SDL3 — clones `kivy/kivy` at `KIVY_REF` (currently `master`)
- iOS pyobjus — clones `kivy/pyobjus` at `PYOBJUS_REF` (currently `master`)
- **Android pyjnius** — built from `ElliotGarbus/pyjnius@spike/android-universal-wheel`,
  a **branch name**, not a commit. Same floating-ref risk, just not phrased as
  `REF=master` so it was easy to miss. Needs pinning too, and needs re-checking
  at pin time whether that branch is still the right source or has since been
  superseded/merged upstream.
- Android Kivy 2.3.1/SDL2 and the four SDL2.x source tarballs need **no**
  change — they're already pinned by construction (versioned PyPI sdist /
  release tarball + recorded SHA-256, not a git ref). Same will be true of
  Android Kivy 3.0/SDL3 *if* it ends up building from a tagged Kivy release
  by the time Phase 3 runs; if Kivy 3.0 is still unreleased, it needs a commit
  pin like the others.

**Mechanism:** a single manifest, `recipes/PINNED_REFS.toml`, one entry per
git-ref-based recipe:

```toml
# Exact upstream commits each recipe builds from. Bumping any of these is a
# deliberate, reviewed commit to this file — never resolved automatically
# at build time, and never silently defaulted to a branch HEAD.
[android.pyjnius]
repo = "https://github.com/ElliotGarbus/pyjnius"
ref = "spike/android-universal-wheel"   # branch this commit was taken from, for context only
commit = "<resolved sha, filled at Phase 1/2>"

[ios.kivy_3_0_sdl3]
repo = "https://github.com/kivy/kivy"
ref = "master"
commit = "<resolved sha, filled at Phase 1/4>"

[ios.pyobjus]
repo = "https://github.com/kivy/pyobjus"
ref = "master"
commit = "<resolved sha, filled at Phase 1/4>"
note = "master deliberately avoids upstream PR #105 (ObjC protocol loading rework, flagged DO NOT MERGE YET). Re-check this note is still true before ever bumping this pin."
```

- Each recipe script stops defaulting `KIVY_REF`/`PYOBJUS_REF` (etc.) to
  `master`; it reads the commit from this manifest, and the variable becomes
  **required** — no `:-master}` fallback. A missing pin should fail the build,
  not quietly float.
- Initial pins are resolved once during Phase 1 (`git ls-remote <repo> <ref>`
  for each entry) and committed — routine maintenance after that, same as
  bumping any other pinned dependency.
- The publish workflow reads this manifest and includes the exact commits in
  each Release's notes, mirroring the SHA-256 provenance discipline the
  Android recipe already uses for source tarballs.

## Decision: SDL glue is captured as build provenance, not a distributed asset

Confirmed. The SDL2 Java glue (`org/libsdl/app/*.java`) is **not** published as
a GitHub Release asset alongside the wheels. Nobody `pip install`s a `.java`
file, so it doesn't belong on the distribution path that exists for things pip
consumes — putting it there would create a second copy that itself needs
keeping honest against the tarball it came from, the same "two things that can
silently drift apart" shape that caused this session's black-screen bug.

Instead it's captured as **provenance of the recipe that built the matching
`libSDL2.so`**, at the moment that recipe runs:

- The Android SDL2 recipe script already downloads and SHA-verifies the
  official source tarball. That same tarball contains
  `android-project/app/src/main/java/org/libsdl/app/*.java` — the exact glue
  that has to match. The recipe extracts it (+ `LICENSE-SDL.txt`, + a generated
  `SDL_REVISION.txt`) into `recipes/android/sdl-glue/<sdl-version>/`, **checked
  in as part of the same commit** that bumps or adds that SDL version. Same
  verified tarball, same commit — no window where the wheel and the captured
  glue could trace back to different sources.
- CI assertion in the Android workflow: re-extract fresh from the pinned
  tarball and diff against what's checked in. Catches a hand-edit or a
  forgotten version bump mechanically, before it ever reaches a device.
- **kivyforge-side follow-up (separate, small, later — not this repo's
  scope):** a one-line sync check comparing kivyforge's own vendored
  `platforms/android/bootstrap/templates/sdl2/` against this repo's
  `recipes/android/sdl-glue/<version>/` at the pinned commit. That turns "does
  our vendored copy match what we're actually shipping" from something
  discovered on-device into something checkable on demand.
- Same pattern extends to Android SDL3 glue once Phase 3 exists. iOS needs
  none of this — Kivy's iOS wheel bundles its own xcframeworks internally via
  `add-ios-frameworks.py`; there's no separate kivyforge-vendored Java
  equivalent to keep in sync there.

## Hosting mechanism

- **Binaries:** GitHub Release assets on the new repo. Public repo → free
  bandwidth, no size games (limit is 2 GB/asset).
- **Index:** PEP 503 static `simple/<package>/index.html` per package, each
  entry `<a href="<release-asset-url>#sha256=...">filename.whl</a>`, generated
  from the Release assets (via `gh release list`/REST API) and deployed to
  GitHub Pages. A CI job regenerates it on every `release: published` event.
  This is a pure static-file generator — no server, no auth, no moving parts
  beyond "list current release assets, emit HTML, push to Pages branch."
- **kivyforge-side change: none.** `[tool.kivy.<platform>].extra_index_urls`
  already exists and is passed straight to pip. Once the index is live, the
  migration for each example project is deleting the `find_links =
  ["../../wheels/..."]` line and adding the new index URL — not a lock-format
  change, since vendored-wheel path pins and PyPI-style `url`+`sha256` pins are
  both already-supported lock shapes.
- The SDL glue is deliberately **not** part of this distribution path — see
  the dedicated decision above.

## Proposed repo layout

```
kivy-mobile-wheels/                  # name proposed, trivially renameable — confirm or override
├── README.md                        # bridge framing + retirement condition, stated explicitly
├── recipes/
│   ├── PINNED_REFS.toml             # exact commit per git-ref-based recipe — see pinning decision above
│   ├── android/
│   │   ├── sdl2.sh                  # ported from android-wheel-build-recipe.md + my WSL scratchpad
│   │   ├── kivy-2.3.1-sdl2.sh       # ported, already verified hashes to check CI against as a regression test
│   │   ├── kivy-3.0-sdl3.sh         # NEW — the real investigation item
│   │   └── pyjnius.sh               # ported; reads its commit from PINNED_REFS.toml, not a branch name
│   └── ios/
│       ├── kivy-3.0-sdl3.sh         # ported from kivyforge's scripts/build_ios_wheels.sh; reads PINNED_REFS.toml
│       └── pyobjus.sh               # ported from kivyforge's scripts/build_pyobjus_ios_wheels.sh; reads PINNED_REFS.toml
├── .github/workflows/
│   ├── build-android.yml            # cibuildwheel --platform android matrix, ubuntu runner
│   ├── build-ios.yml                # cibuildwheel --platform ios matrix, macos runner (free on public repos)
│   └── publish-index.yml            # on release:published — regenerate PEP 503 index, deploy to Pages
└── index-gen/
    └── generate_index.py            # PEP 503 static index generator
```

`recipes/android/sdl-glue/<sdl-version>/` (the extracted, verified glue — see
the SDL-glue decision above) lives under `recipes/android/`, not as a
top-level directory: it's provenance for that recipe, not a separate concern.

## Where each phase runs

Not a preference — a hardware split. cibuildwheel's iOS target is a hard
macOS+Xcode requirement (code signing, the iOS SDK; no Linux/Docker path
around it), so the iOS phases can only run on the Mac, full stop. Android
isn't the Windows-machine's exclusive turf the same way — it's Linux/POSIX,
and this box already has WSL set up and proven this session (kivyforge
installed, a real `lock -p android` run from inside it). The deeper reason to
keep the split rather than move everything to the Mac: **on-device validation
hardware is fixed per machine, not per toolchain.** The Android emulator and
the Pixel 8a are wired up here via `adb` on Windows; the iOS simulator lives
on the Mac. Moving the whole project to the Mac would mean re-establishing
Android device testing there for no gain, since iOS builds still couldn't run
from wherever Android testing *isn't*.

| Phase | Runs on | Why |
|---|---|---|
| 0 — inventory existing iOS wheels | **Mac** | the 6 files are on the Mac's disk |
| 1 — repo scaffolding, `PINNED_REFS.toml` | Windows (this session) | plain git/text/`gh` work, no toolchain needed |
| 2 — Android proven recipes | Windows, via WSL | POSIX-only build, proven working here this session |
| 3 — Android Kivy 3.0/SDL3 | Windows, via WSL | same POSIX requirement as Phase 2 |
| 4 — iOS: port existing scripts | **Mac** | cibuildwheel iOS = macOS + Xcode, no alternative |
| 5 — index generator + Pages wiring | Windows (this session) | pure YAML/Python, no device or toolchain dependency |
| 6 — repoint examples + re-lock + re-validate | **split**: Android half on Windows (emulator + Pixel 8a already attached here); iOS half on the Mac (simulator) | — |

Mac-only phases get dispatched as a self-contained prompt (the same pattern
that already worked for `docs/design/dev/ios-validation-prompt.md` this
session) rather than by switching this session to the Mac.

## Phases

**Phase 0 — inventory before rebuilding anything**
Read the 6 existing wheel files already sitting in `examples/wheels/ios/` on
the Mac (names + sha256). If they're usable, they become the first Release's
assets without a rebuild; if not, note why.

**Phase 1 — repo scaffolding**
Create the repo (`gh repo create`, public, personal), README with bridge
framing, empty workflow skeletons, layout above. Includes resolving and
committing the initial `PINNED_REFS.toml`: `git ls-remote` each of
`ElliotGarbus/pyjnius@spike/android-universal-wheel`, `kivy/kivy@master`,
`kivy/pyobjus@master`, and recording the SHA each currently resolves to —
before any of them are built from in this repo.

**Phase 2 — Android: port proven recipes (low risk)**
Formalize `android-wheel-build-recipe.md` + my WSL scratchpad into committed
scripts: SDL2 4-library build (already pinned via source-tarball SHA-256, no
change needed) — extending it to also extract the matching
`org/libsdl/app/*.java` glue into `recipes/android/sdl-glue/<version>/` in the
same commit (see SDL-glue decision above) — Kivy 2.3.1/SDL2 cibuildwheel
(same), pyjnius cibuildwheel (reads its commit from `PINNED_REFS.toml`,
replacing the bare branch-name checkout it uses today). CI job includes the
glue-diff assertion (re-extract from the pinned tarball, compare to what's
checked in). First real regression check: rebuilt wheels' sha256 should either
match the already-verified hashes exactly (bit-reproducible) or, more likely,
differ — in which case re-run `kivyforge lock -p android --update` against the
new hashes and re-run the on-device contract smoke test before trusting them,
exactly as was done this session.

**Phase 3 — Android: Kivy 3.0 / SDL3 (real investigation)**
Confirm SDL3 prebuilt zip's alignment, find Kivy 3's actual Android/SDL3
`setup.py` contract, build from the pinned commit (add a
`[android.kivy_3_0_sdl3]` entry to the manifest if Kivy 3.0 is still
unreleased at this point — a tagged release would need no pin, same as 2.3.1),
verify 16 KB alignment + flat `.libs/` + unchanged sonames (same checklist as
the SDL2 wheel), publish.

**Phase 4 — iOS: port existing scripts**
Adapt `build_ios_wheels.sh` and `build_pyobjus_ios_wheels.sh` into a macOS
GitHub Actions workflow, each reading its commit from `PINNED_REFS.toml`
instead of defaulting `KIVY_REF`/`PYOBJUS_REF` to `master`. First CI run of
the pyobjus path is the actual validation it's never had.

**Phase 5 — index generator + Pages wiring**
PEP 503 generator, `release:published` trigger, confirm `pip download
--index-url <pages-url>/simple/ kivy==2.3.1` (or equivalent dry-run) resolves
correctly before touching any kivyforge example.

**Phase 6 — point kivyforge examples at the index**
Swap `find_links` for `extra_index_urls` in `hello-android`, `hello-kivy`,
`pyobjus-*`, `pyjnius-deviceinfo`; re-lock; re-run the on-device gates (Android
emulator + Pixel 8a; iOS simulator) to confirm nothing regressed from the
switch itself.

## Open items to confirm next session (not blocking, but unresolved)

1. Repo name — proposed `kivy-mobile-wheels`, easy to rename later.

## Explicit non-goals

- Not touching kivyforge's own code in this repo. Two follow-ups this plan
  produces but does not do:
  - The `templates/sdl3/` gap for Android SDL3 (`render_bootstrap(sdl=3)`
    currently raises `RenderError`) — needed once Phase 3's wheel exists.
  - The kivyforge-side sync check comparing
    `platforms/android/bootstrap/templates/sdl2/` against this repo's
    `recipes/android/sdl-glue/<version>/` (see SDL-glue decision above).
- Not moving ownership to the Kivy org yet — personal, by decision above.
- Not attempting PyPI Trusted Publishing yet — the recipes are written so that
  migration is straightforward later, not implemented now.
