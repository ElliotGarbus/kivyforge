# Test matrix and test plan

**Created 2026-09-13** (roadmap item 2), **revised 2026-09-13** after review.
This is the answer to "which host × target × tier combinations have actually
been exercised, and when." Nothing else in the repo answers it, and roadmap
item 1 is what that cost: `strip_source` had shipped for two releases having
never once run on a mobile target, and the way it was finally noticed was a
person opening a staged bundle and looking for `main.py`.

Three rules for keeping this file honest:

1. **Coverage claims name the thing that produces them** — a CI job, a local
   script, or a dated line in the results log. "Should work" is not coverage,
   and neither is "there are unit tests for it".
2. **The gap list is the deliverable, not the coverage list.** A matrix that
   only records what passes is how item 1 stayed invisible.
3. **No counts, no inventories that live somewhere else.** Exact test counts and
   duplicated tables go stale silently, which is the same failure as an
   unlogged test. Point at the producer instead. The first revision of this file
   broke this rule twice within a day, and the review caught both.

---

## 1. What can be built where

Derived from each backend's `check_host_capability()` and the arch sets in
`kivyforge/config/model.py`, not from intent.

The host gates are **OS-only**. No backend gates on host CPU, and Windows
documents that as deliberate (`platforms/windows/__init__.py`: "Do NOT add a
host==target check"). Android has no gate at all — it consumes prebuilt wheels
and drives the cross-platform Android SDK/NDK, so host adequacy (JDK, SDK, NDK)
is doctor's problem rather than a capability error.

| Target (arch) | Windows host | macOS host | Linux host | Gate |
|---|---|---|---|---|
| Windows `amd64` | native | ✗ | ✗ | `Windows` only |
| macOS `arm64` | ✗ | native | ✗ | `Darwin` only |
| Linux `x86_64` | ✗ (WSL2 is a Linux host) | ✗ | native | `Linux` only |
| Linux `aarch64` | ✗ (WSL2 is a Linux host) | ✗ | cross | `Linux` only |
| Android `arm64_v8a` | cross | cross | cross | none |
| Android `x86_64` | cross | cross | cross | none |
| iOS device `arm64` | ✗ | native-only | ✗ | `Darwin` only |
| iOS simulator `arm64` | ✗ | native-only | ✗ | `Darwin` only |

Eight target cells, not five platforms — Android, iOS, and Linux each carry
two, and they are genuinely different builds.

**The arch sets are narrower than the gates.** `VALID_WINDOWS_ARCHS` is
`{amd64}`, `VALID_MACOS_ARCHS` is `{arm64}`, `VALID_LINUX_ARCHS` is
`{x86_64, aarch64}`. So although the Windows host gate permits cross-arch
builds by design, config rejects `arm64` today: win-arm64 is still an additive
change to that frozenset. Linux `aarch64` landed 2026-09-17 as a Raspberry Pi
*target* (cross-only from x86_64; item 4) — T2+T3 on WSL2, T4/T5 on a Pi 5.
See [`aarch64-pi-target-findings.md`](aarch64-pi-target-findings.md).

**The consequence for planning: from the Windows dev box, Windows and Android
are reachable directly, and Linux is reachable through WSL2.** macOS and both
iOS cells need a Mac. Item 4's Linux-host gate is closed. Of the open roadmap
items, item 8's iOS half wants a Mac — and everything iOS in §6 is Mac-blocked
independently of which item it belongs to.

---

## 2. Tiers

Each tier is a different cost/confidence trade. The split matters because only
T5 is genuinely un-automatable — T2, T3, and T4 are all commonly *assumed* to
need hardware and do not.

| Tier | What it proves | Needs |
|---|---|---|
| T0 unit | logic, hermetic — no toolchain, no network | nothing |
| T1 generation | generated Gradle/Xcode/AppDir/onedir trees are what the config asked for | nothing |
| T2 toolchain | real `gradle` / `xcodebuild` / `clang` / MSVC / `appimagetool` consume our output without complaint | the toolchain |
| T3 artifact assertions | the produced artifact is *correct* — post-build file inspection | a build, no device |
| T4 launch smoke | the app reaches its first frame | emulator/simulator |
| T5 hardware | real device behaviour | a device, a human |

T0 and T1 blur in practice and the matrix below does not try to separate them;
both are "the hermetic suite".

### How a tier is actually selected — markers for T0/T1, jobs for T2+

This distinction matters more than it looks, and stating it wrongly would
recreate the very hole this file exists to close. The markers in
`tests/conftest.py` are **not** a way to ask "what does CI run":

```
pytest -m "not integration"    # the hermetic suite: T0+T1
pytest -m integration          # T2+ *that pytest can reach on its own*
```

CI does not use those expressions at all. `unit_tests`, `windows_tests`, and
`macos_integration` all run **unfiltered** `pytest`; what makes them different
tiers is the host and the toolchain present, not a `-m` flag.

**T2 and T3 are jobs, not markers.** The real shape is *a job builds, then
pytest inspects the path it produced*:

```
kivyforge build -p android --debug --abi x86_64      # the T2 step
pytest tests/platforms/android/test_apk_artifact.py \
       --android-apk <path> --android-abi x86_64     # the T3 step
```

So `pytest -m integration` on a dev box **skips** the APK assertions — there is
no `--android-apk` to give it — and reports green. Anyone concluding "I ran
`-m integration` and it passed, so T3 is covered" has reproduced item 1's
mistake in a new place. The `--android-apk` / `--android-abi` /
`--android-stripped` options are the T3 entry point, and they are named here
rather than buried in §5.1 for exactly that reason.

**The `--<platform>-project` options are the other half of that entry point.**
`--android-project`, `--macos-project` and `--windows-project` hand a check the
project's `pyproject.toml`, which is what any *comparison against config*
needs: the merged-manifest check, the `Info.plist` check and both signature
checks are comparisons rather than self-consistency checks, so without the
project they have only one side. Leaving one off is the cheapest way to get a
green run that compared nothing — which is why the merged-manifest driver
*fails* rather than skips when given a manifest and no project.

**Three env vars exist because a self-skipping test is indistinguishable from a
passing one:**

- `KIVYFORGE_REQUIRE_SYMLINKS=1` — `requires_symlinks` tests must run, not skip.
  Set on `windows_tests`.
- `KIVYFORGE_REQUIRE_TOOLCHAIN=1` — a missing toolchain becomes a failure
  instead of a skip (`skip_missing_toolchain()`). Set on the three jobs whose
  entire purpose is a toolchain they are known to have.
**There used to be a third, `KIVYFORGE_DEVICE_TESTS`, for a `requires_device`
marker. Both were removed 2026-09-23 (§5.7):** no test ever carried the
marker, so the variable enabled nothing while implying device coverage
existed behind a flag. T5 is a checklist (§6) and a log (§7), not a
selectable suite. If ADB-driven tests are ever written, the marker returns
*with* them.

---

## 3. Coverage today

### 3.1 The jobs, and the host each one is

CI jobs are in `.github/workflows/kivyforge.yml`. **The host of a coverage cell
is the runner of the job named in it**, which is why this table comes first —
"Android T3" is a *Linux-host* Android build, and that is load-bearing given
§4's first bullet.

| Job | Host | Python | Serves |
|---|---|---|---|
| `lint` | ubuntu | `3.x` | ruff, cross-cutting |
| `package` | ubuntu | `3.x` | build + `twine check`, cross-cutting |
| `sdl_glue_sync` | ubuntu | `3.x` | vendored SDL Java glue vs. kivy-mobile-wheels |
| `unit_tests` | ubuntu | 3.13, 3.14 | hermetic, all targets |
| `windows_tests` | windows | 3.13, 3.14 | hermetic incl. `requires_windows` + symlinks |
| `windows_launcher` | windows | `3.x` | Windows T2/T3 (MSVC, byte-compare) |
| `revendor_launcher` / `revendor_verify` | windows | `3.x` | launcher reproducibility |
| `windows_signing` | windows | `3.x` | Windows T2 (`signtool`, self-signed) |
| `android_gradle` | ubuntu | **3.14** | Android T2 + T3, **both ABIs** (matrix: `arm64_v8a`, `x86_64`) |
| `android_emulator` | ubuntu | **3.14** | Android **T4** (`run --smoke --release` on an x86_64 AVD) |
| `android_windows_host` | **windows** | **3.14** | Android T2 + T3 from a *Windows* host (§5.2's resolver path) |
| `linux_appimage` | ubuntu | **3.13** | Linux T2 + T3 (`package` + AppImage assertions) |
| `windows_onedir` | windows | **3.13** | Windows T2 + T3 (`package` + onedir assertions + built-launcher signature) |
| `macos_app` | macos | **3.13** | macOS T2 + T3 (`package`, ad-hoc signed, + `.app` assertions) |
| `macos_integration` | macos | **3.13** | macOS T2 (two `clang` tests) |
| `ios_simulator` | macos | **3.13** | iOS T2 + T3 + T4 (`build`/`run --simulator`, plus the `.app` artifact pass) |

**Seven jobs pin an exact minor, for two different reasons.** `android_gradle`
and `android_emulator` *must*: the T3 magic-number check compares the APK's
`.pyc` headers against the *runner's* `importlib.util.MAGIC_NUMBER`, so the
runner's Python is part of the test definition (`test_apk_artifact.py` fails
naming the runner if they diverge), and `android_emulator`'s `--release` leg
byte-compiles with it. Both pin 3.14, the minor those projects ship.

`linux_appimage`, `windows_onedir`, `macos_app`, `macos_integration` and
`ios_simulator` pin 3.13 for the other reason: **each is the sole CI proof of
its platform**, so none should test whichever minor the image happens to ship
(§5.8). Their own magic checks need no pin — each desktop driver asks the
artifact's **own staged interpreter** what magic it accepts, and iOS never
byte-compiles at all on this path. Worth keeping straight: "pin it like
Android does" is the wrong reason to pin one of these, and briefly cost
`ios_simulator` its pin on the argument that no magic number was at stake
— true, and beside the point.

**Five jobs still float, and that is correct.** `lint`, `package`,
`sdl_glue_sync`, `windows_launcher`, `windows_signing` and the two
`revendor_*` jobs stay on `3.x`. None is the sole proof of a *platform*: they
are cross-cutting checks, or they exercise a C toolchain and a signing tool
whose behaviour does not turn on the Python minor. Pinning them would give up
the early warning that floating buys, for nothing.

**Every job that *is* the sole proof of a platform now pins** —
`android_gradle`, `android_emulator`, `linux_appimage`, `windows_onedir`,
`macos_app`, `macos_integration`, `ios_simulator`. That is §5.8's rule applied
mechanically, which is the point of stating it that way: "is this the only job
proving platform X?" needs no per-job judgment, whereas "does the host
interpreter affect the artifact?" needs to know each platform's byte-compile
path before you can answer.

Local scripts are producers too, and rule 1 means they count only when a run is
logged in §7: `examples/verify-windows-examples.ps1` (a real Windows
build/run/package loop), `examples/verify-desktop-examples.sh`,
`examples/verify-android.ps1`, `examples/verify-ios-device.sh`, and
`examples/run-examples.sh`. **`examples/verify-ios-device.sh` got its first
logged run 2026-09-14** (§7) — the other four still have none. They remain the
cheapest untapped coverage in the repo — `verify-windows-examples.ps1` in
particular covers the Windows column that no CI job reaches (§5.3 — Linux's
and macOS's equivalent gaps closed 2026-09-22, Windows' has not).

### 3.2 Per-target coverage

**Last proven** distinguishes standing coverage from one-off evidence: *every
push* means a CI job re-proves the row continuously, and a date means the only
evidence is a single logged run in §7 that nothing re-runs.

| Target | T0/T1 | T2 toolchain | T3 artifact | T4 launch | T5 hardware | Last proven |
|---|---|---|---|---|---|---|
| Windows `amd64` | `windows_tests` | `windows_onedir` — real `package -p windows` on every push (since 2026-09-22); plus `windows_launcher` (MSVC) and `windows_signing` (self-signed `signtool`) | `windows_onedir` — full onedir T3 pass, **plus `signtool verify /pa` on the built launcher** after signing it with a throwaway cert; `windows_launcher`'s vendored byte-compare continues alongside | **partial** — launcher against a stub `python.exe`; no Kivy app launched | see §6 | every push |
| macOS `arm64` | `unit_tests` (minus mac-only), `macos_integration` | `macos_app` — real `package -p macos` (ad-hoc signed) on every push (since 2026-09-22); previously local-only Developer-ID sign + notarize + staple + `strip_source` on `examples/desktop/dice-roller` remains the only *notarized*, non-ad-hoc evidence | `macos_app` — full T3 pass, including the `Info.plist`-vs-config comparison, on every push (since 2026-09-22); the notarized-`dice-roller.app` run (2026-09-14) remains the only evidence with a real Developer ID | **local** — a stripped, re-notarized `dice-roller.app` launched and rendered for the first time, after fixing the launcher (§7, 2026-09-14) | see §6 | every push (T0/T1/T2/T3); 2026-09-14 (T2-Developer-ID, T4) |
| Linux `x86_64` | `unit_tests` | `linux_appimage` — real `appimagetool` on every push (since 2026-09-22); previously local only | `linux_appimage` — full T3 pass over the packaged AppImage on every push | **local only** — stripped AppImage reaches first frame (llvmpipe) | see §6 | every push (T0/T1/T2/T3); 2026-09-13 (T4) |
| Linux `aarch64` | `unit_tests` | **local only** — cross `package` on x86_64 WSL2, host `appimagetool` + target type2 runtime | **local only** — T3 driver extracts via `unsquashfs` (the aarch64 type2 ELF cannot `--appimage-extract` here); ELF leak check caught a planted host `.so` | **local** — stripped AppImage reaches main loop on Pi 5 (labwc, Broadcom V3D) | **manual** — Pi 5 only; Pi 4 untested | 2026-09-17 |
| Android `arm64_v8a` | `unit_tests` | `android_gradle` (matrix leg, since 2026-09-23) | `android_gradle` — debug **and** stripped release APK on every push, same three checks as x86_64 | none — the emulator is x86_64, so T4 for this ABI stays a device run | **manual** | every push (T2/T3); 2026-09-13 (T5, Pixel 8a) |
| Android `x86_64` | `unit_tests` | `android_gradle` (AGP, NDK, CMake, `javac`) | `android_gradle` — debug **and** stripped release APK shape, plus the merged release manifest vs. config and `apksigner verify` on the signed release APK (both since 2026-09-21) | `android_emulator` — `run --smoke --release` on an API-35 x86_64 AVD on every push (since 2026-09-23); previously local-only and last run 2026-07-27 | n/a | every push (T2/T3/T4; T2+T3 also from a **Windows** host via `android_windows_host` since 2026-09-23) |
| iOS device `arm64` | `unit_tests` | **local** — `build -p ios --device`, `package -p ios --export-method development`, real iPhone14,3 | **none** | **local** — installed, launched, `hello-kivy` rendered on device | **manual** — first physical run, 2026-09-14 | 2026-09-14 |
| iOS simulator `arm64` | `unit_tests` | `ios_simulator` — real `build -p ios --simulator` on every push (since 2026-09-23); previously local-only, 6 examples | `ios_simulator` — real T3 pass since 2026-09-23 (spec'd in [`ios-t3-checks-prompt.md`](ios-t3-checks-prompt.md), findings in [`ios-t3-checks-findings.md`](ios-t3-checks-findings.md)): required entries, a whole-bundle Mach-O arch sweep (100+ per-extension-module `Frameworks/*.framework`, hoisted there by `install_python`), `Info.plist` vs. config, and `codesign --verify`. **No stripped/`.pyc`-magic check** — iOS `strip_source` still cannot be exercised honestly (every example pins a CPython 3.15 pre-release; §7 2026-09-14/2026-09-23) | `ios_simulator` — `run -p ios --simulator --no-build` install+launch, plus a screenshot artifact, on every push (since 2026-09-23); previously local only, all 6 examples render | n/a | every push (T2/T3/T4, `hello-kivy` only); 2026-09-14 (regression re-check on all 6, local; no drift since 2026-07-27) |

Legend for how a cell was proven, because "covered" hides the difference:
**CI** = re-proven every push; **local** = a first-party run on a maintainer's
machine, logged in §7, not re-run automatically; **manual** = a human with
hardware; **inherited** = argued from a different cell rather than executed.

### Reading the partials

**Windows T0/T1 is `windows_tests`, not `unit_tests`.** `unit_tests` runs on
ubuntu, where every `requires_windows` test skips — so naming it as a producer
of Windows coverage is the same category error as counting a skip as a pass.

`windows_launcher` rebuilds `launcher-amd64.exe` from source and byte-compares
it against the vendored copy, which is a strong T3 — but **of one vendored
binary, not of a built app**. `test_launcher_exe.py` runs the real launcher
against a compiled stub `python.exe`, proving spawn/argv/exit-code/env and
process-tree teardown; a genuine T4 for the launcher that says nothing about a
Kivy app.

**Corrected 2026-09-23:** this paragraph used to end "No CI job runs
`kivyforge build -p windows`." `windows_onedir` has done so on every push
since 2026-09-22, via `package`, and the §3.1 table two paragraphs above
already said as much — exactly the stale-sentence failure the rules at the top
of this file exist to prevent. What the *launcher* jobs above prove is still
narrower than a built app, which is why they are described as partials.

**macOS's CI now has two jobs, and one of them is the real thing.** Until
2026-09-22, `macos_integration` ran `pytest -q` and nothing else — its entire
marginal value over `unit_tests` was the two `TestLauncherCompile` tests that
`clang` makes runnable — and no CI job ran `kivyforge build -p macos`.
`macos_app` closes that: `doctor`, `lock --check` against a committed lock,
`package -p macos` (ad-hoc signed — no certificate needed), then the full T3
pass over the produced `.app`, on `tests/fixtures/apps/macos-gate` every push
(§5.3). Outside CI the maintainer has separately been building,
Developer-ID-signing, and notarizing `dice-roller` by hand since July 2026 (five
`notarytool` submissions, all `Accepted` — §7); that remains the only evidence
with a *real* Developer ID and notarization, which `macos_app`'s ad-hoc floor
does not exercise. So `codesign`, `lipo`, and `hdiutil` are no longer mock-only
**or** local-only for the ad-hoc case — they run every push — while the
Developer-ID/notarization path stays local-only, a narrower and more honest
remaining gap than "no CI job runs the build at all".

**Linux's CI column filled in the same way, one day earlier.** `linux_appimage`
runs `kivyforge build -p linux` (via `package`) every push, closing what this
paragraph used to say was untested in CI. The 2026-09-13 local run (§7) remains
the only evidence of the *defect it found* — a bug in a since-fixed code
path — and of `aarch64` cross-compilation, which `linux_appimage` does not
attempt (native `x86_64` only; §5.3/§4 own the cross case).

**Android is the strongest column, and the only one with real T3.**
`android_gradle` is the real thing — AGP, the pinned NDK, CMake, and `javac` all
consume generated files, and the release path runs `lintRelease` plus the
merged-manifest policy pass against a throwaway keystore. Both the debug APK and
the **stripped release APK** go through `tests/artifact_checks.py` (§5.1).

**Android `arm64_v8a` was marked *inherited* rather than covered — resolved
2026-09-23.** For most of this file's life `android_gradle` built `x86_64`
only, so the shipping ABI was never built in CI. The stray-ABI check partly
compensated, but the arch assertions are precisely the ABI-specific ones, so
claiming `x86_64`'s T3 covered `arm64_v8a` was an argument, not a run — and
rule 1 says label that as such, which is why it read *inherited* for so long.
`android_gradle` is now a two-leg matrix and runs the full T3 pass on both
ABIs directly. T4 for `arm64_v8a` is still a device run, since the emulator
is x86_64.

**iOS's simulator coverage is real, local, and was missing from this file until
2026-09-14** — the same fault as §3.3's Android T4, found the same way. The
2026-07-25 and 2026-07-27 runs did not merely go green on a macOS host: they ran
`kivyforge build -p ios --simulator` and `run -p ios --simulator` for real, and
all six iOS examples build, launch and render on an iPhone Air simulator with
screenshots to prove it. So `xcodebuild` and `simctl` **have** executed, and the
claim that "no iOS toolchain has ever run" — which this file asserted, and which
its 2026-09-13 revision *introduced* while relabelling the log row from a summary
line instead of reading the findings — was wrong.

The old claim that iOS was blocked on the `Python.xcframework` and wheels being
published is also stale: all six examples now resolve from the
`kivy-mobile-wheels` index. **As of 2026-09-23 that blocker's own removal has
finally been acted on**: `ios_simulator` runs `build -p ios --simulator` (T2)
and `run -p ios --simulator --no-build` (T4) against `hello-kivy` every push,
with a screenshot uploaded for a human to glance at. Only `hello-kivy`, not all
six — a small fixture-app footprint is the deliberate choice item 5 itself made
(full-example builds stay a local/nightly cost, not a per-push one), the same
choice `android_gradle`/`linux_appimage`/`macos_app` already made for their
platforms.

**iOS got its first physical-device run 2026-09-14.** `build -p ios --device`,
`run -p ios --device`, and `package -p ios --export-method development` all
succeeded against a real iPhone14,3, and `hello-kivy` rendered on-screen —
detail in [`macos-ios-validation-findings.md`](macos-ios-validation-findings.md)
Step 6. That run also found and fixed a real bug: `--team-id` /
`KIVYFORGE_TEAM_ID` was resolved and validated by `preflight_signing()` but
never reached the generated Xcode project's `DEVELOPMENT_TEAM` setting, so an
override could pass the CLI's own check and still fail to build — the
simulator path never signs at all, so this was unreachable from any coverage
this file previously counted. Fixed in `buildsettings.py` /`generator.py` /
`materialize.py` / `cli.py`, with two new regression tests.

What remained genuinely unproven for iOS as of that run: **no CI** (the device
and simulator runs above were local and unrepeated — fixed 2026-09-23 by
`ios_simulator`, for the simulator leg), **no T3** (nothing inspected the
built `.app` or `.ipa` the way `--macos-app` inspects a macOS bundle — also
fixed 2026-09-23, by `ios_app_problems`/`--ios-app`, wired into the same job),
and **`strip_source`**, which is not merely unrun but currently *unrunnable*,
and remains so — no checker exists for it, deliberately (§5.1):
`package -p ios` degrades to shipping source because there is no final CPython
3.15 yet, and **every iOS example in this repo pins `3.15.0b4`** — so this is a
structural gap general to the whole platform, not a gap in any one example or
test.

**macOS as a *target* is no longer the empty half, and as of 2026-09-22 it is
CI-shaped too.** The maintainer has been building, signing, and notarizing
`dice-roller` by hand since July 2026, and 2026-09-14 turned that into logged
evidence (§7) plus an automated T3 check (§5.1) that passed against the real
artifact. `macos_app` (§5.3) is exactly the job this paragraph used to ask
for: it runs `kivyforge build -p macos` (via `package`, ad-hoc signed — no
certificate needed) every push and points the T3 driver at the result, on a
dedicated `macos-gate` fixture rather than on `dice-roller`. What the CI job
does *not* cover is the Developer-ID/notarization path — that stays the
human-remembered, local-only evidence described above, since ad-hoc signing
is a deliberately different, secret-free tier.

### 3.3 Relationship to the Android compatibility matrix

[`platforms/android/08-compatibility-matrix.md`](../platforms/android/08-compatibility-matrix.md)
is the **other** matrix, and the two answer different questions. It tracks
*which runtime combination* (CPython × Kivy × SDL × contract) is validated; this
file tracks *which host × target × tier* is exercised. They overlap in exactly
one place — Android T4 — and the first revision of this file got that overlap
wrong, marking Android T4 as flatly `none` while the compatibility matrix
recorded `kivyforge run --smoke` green on an x86_64 API-31 emulator for two
separate runtime combinations.

Both were defensible readings of "coverage" and that is the problem: `none` was
CI-scoped, `Validated` was first-party-scoped. Fixed here by the **local** label
and by logging those runs in §7, where under this file's own rules they belonged
all along. When the two files disagree in future, the compatibility matrix owns
the runtime dimension and this one owns host × tier.

**Superseded 2026-09-23 for Android `x86_64`.** That overlap was a labelling problem only while Android T4 lived outside CI. `android_emulator` now runs `run --smoke --release` on an AVD on every push, so that cell is plain CI coverage and needs no **local** qualifier. The label still applies to Android `arm64_v8a` T4 and to the iOS device, both of which remain hardware runs.

---

## 4. Host-dependent behaviour

The same target builds through different code on different hosts, so "Android
passes" is not host-independent. Each of these has bitten:

- **Byte-compile takes a different path per host.** `select_compiler()` uses the
  staged interpreter when the build is native and searches the host via
  `find_interpreter()` otherwise. A Windows host building Windows `amd64` takes
  the first path; the same host building Android takes the second. Item 1 was
  precisely a bug in the second path — and since `android_gradle` runs on
  ubuntu, CI's Android T3 there does not take it. **Partly addressed
  2026-09-23** (§5.2): `android_windows_host` now builds and inspects a
  release APK on `windows-latest` every push. But read that section before
  treating this as closed — its own log line shows CI resolving via
  `find_interpreter`'s "interpreter already running" fast path, *before* the
  Windows candidate list is built, because `setup-python` makes the runner the
  same 3.14 the project ships. **So the `py`-launcher search item 1 actually
  broke is still covered only by the dated local measurement in §7 and by
  `tests/bundle/test_pycompile.py`**, not by anything standing.
- **Windows needs Developer Mode for symlinks.** Covered by
  `requires_symlinks` + `KIVYFORGE_REQUIRE_SYMLINKS`.
- **Windows has a path-length ceiling** that deep staging trees can hit, and the
  launcher declares no `longPathAware` manifest. **No test.** (§5.6)
- **Windows redirected streams are cp1252.** Guarded statically by
  `tests/test_message_encoding.py`, which parses `kivyforge/` for strings that
  can reach a stream and cannot encode — the model for the kind of cheap policy
  test this matrix should have more of.
- **macOS and Windows are case-insensitive; Linux is not.** Staging collisions
  appear on one host and not another. **No test.** (§5.6)
- **WSL2 is a Linux host** and is how Linux work happens from the Windows dev
  box. It is not identical to a bare Linux host: `/mnt/c` is a different
  filesystem with different case and permission behaviour, and WSLg supplies a
  display, which makes Linux T4 locally reachable. **Nothing records which
  Linux results came from WSL2 versus a real Linux host** — §7 must say which.
- **Windows launcher reproducibility is pinned to an exact MSVC toolset**
  (`vendor/TOOLSET.txt`), so the runner image is part of the test definition —
  hence `revendor_launcher`/`revendor_verify` existing at all.

---

## 5. The gap list, in priority order

**Rewritten 2026-09-23, because the list it used to prioritise is done.** This
section used to weigh "CI-cost order" against "what the Windows dev box can
prove this week", and offered §5.2, §5.3, §5.4 and §5.6 as the reachable
ones. §5.2, §5.3, §5.4, §5.5, §5.7, §5.8, §5.9 and §5.10 have all since
closed, so that trade no longer decides anything.

What is actually left, in value order — **all of it test coverage**; no
product gap remains on this list:

1. **§5.2's remaining sliver** — the Windows `py`-launcher *search*, still
   local-measurement-only. CI builds an APK on Windows now, but its resolver
   takes the "interpreter already running" fast path, so the candidate search
   item 1 broke is covered by one dated measurement and the unit tests.
2. **§5.6** — now with a real reproduction (the terminfo collision) and still
   no test; `longPathAware` remains a suspicion.
3. **The hardware checklist** — roadmap item 5's "done when" has two halves,
   and this is the second: §6 is prose, not something runnable that records a
   dated result. Not a §5 subsection, which is part of why it keeps being
   skipped over.

**§5.5's product half closed 2026-09-23** — it was item 1 here. `run
--release` now reaches `strip_source` on Linux, macOS and Windows, not only
Android; see §5.5's closure note. The gap was wider than this list said:
it named Linux, but macOS and Windows `run` hardcoded the same
`release=False`.

**§5.1's iOS box closed 2026-09-23**, while this very list was being written
— `ios_app_problems` landed and iOS stopped being the one platform without a
T3. Left recorded here rather than silently deleted, because a list of "what
is left" that goes stale within the hour is the same failure this file's rules
name, and it went stale in the good direction.

The sections below keep their original numbering and their closure notes, so
the reasoning that produced each one survives even where the gap does not.

### 5.1 T3 artifact assertions — highest value available

Every one of these is a file read. No device, no human, no toolchain beyond the
build itself. **A T3 pass would have caught item 1 on the day it shipped**,
which is the whole argument.

**Done for Android, 2026-09-13.** `tests/artifact_checks.py` holds the checks as
pure functions returning problem lists (so one run reports every fault, and so
they are unit-testable against synthetic zips without a build — see
`tests/test_artifact_checks.py`). `tests/platforms/android/test_apk_artifact.py`
points them at a real file via `--android-apk`, and `android_gradle` runs it
twice: once on the debug APK, once on the stripped release APK.

- [x] **`.pyc`-only when `strip_source` is on**, `app/main.pyc` in the legacy
      sourceless layout, and no `__pycache__` — the mixed case is the dangerous
      one, since a `.pyc` beside its `.py` is silently ignored and the bundle
      ships every source file the setting was meant to remove.
- [x] **`.pyc` magic number matches the shipped runtime** — item 1's actual bug.
      The expected magic comes from the running interpreter, and the *target*
      minor is read out of the APK's own `libpython3.X.so`, so an APK can never
      be checked against the wrong runtime and pass. When the runner's Python
      does not match, the failure names the runner rather than the artifact.
- [x] **ELF class and machine per ABI**, plus a stray-ABI check. Constants are
      imported from `platforms/android/elf.py` so they cannot drift from the
      build's.
- [x] **No shared object stranded in the payload** — extension modules must be
      hoisted to `lib/<abi>/`, since Android's loader will not open a `.so` from
      the unpacked assets tree. A leftover is an on-device `ImportError`.
- [x] **Exactly one CPython runtime** in the APK.
- [x] **macOS check *functions* and driver — done 2026-09-14. In CI since
      2026-09-22** via `macos_app` (§5.3), mirroring `linux_appimage`'s shape.
      `tests/artifact_checks.py::macos_app_problems` (required entries, Mach-O
      arch via a new pure-Python `machotools.read_macho_cpu_type`, payload
      stripping scoped to `app/`+`lib/` only per the settled stdlib-exclusion
      design, `.pyc` magic, `Info.plist`), hermetic-tested in
      `tests/test_artifact_checks.py`, and wired to a real bundle via
      `tests/platforms/macos/test_app_artifact.py --macos-app`. Ran against the
      real notarized `dice-roller.app` (2026-09-14) — passed. The `--macos-project`
      `Info.plist`-vs-config comparison (added 2026-09-21) had never run against
      a real bundle until the `macos-gate` fixture (§5.3) exercised it
      2026-09-22 — see that row.
- [x] **Linux check functions — done 2026-09-13, and they caught a shipped bug.
      In CI since 2026-09-22** via `linux_appimage` (§5.3), the first desktop
      build job in the repo — so this is the one desktop platform whose T3 pass
      is standing coverage rather than a logged one-off.
      `linux_appdir_problems` / `linux_appimage_file_problems` in
      `tests/artifact_checks.py`, 36 hermetic tests on synthetic AppDirs, driver
      behind `--linux-appimage` / `--linux-appdir`. Three things worth carrying
      to the Windows equivalent: the payload is `usr/app` + `usr/lib` **only**
      (the build byte-compiles nothing else, so a stripped AppImage legitimately
      ships ~1000 stdlib `.py` and a tree-wide sweep would report every one as a
      fault — the same stdlib-exclusion the macOS check scopes around); the
      expected `.pyc` magic is asked of the artifact's *own* staged interpreter,
      which a desktop bundle can answer and an APK cannot; and the ELF sweep
      covers the whole tree, because `doctor.check_linux_native_binaries` looks
      only under `usr/bin` and SKIPs unless native binaries are declared.
- [x] **A launcher-entry check on macOS — the defect it predicted was real,
      fixed 2026-09-14.** The Linux checker asserts that whatever `AppRun`
      promises to execute actually exists, and that is the check that caught
      the shipped `strip_source` launch failure in §7. `macos_app_problems` had
      no equivalent, and `macos/launcher.py` built the same `"%s/%s.py"` exec
      path Linux's did, naming a `main.py` that `strip_source` had already
      deleted — confirmed by actually running the notarized `dice-roller.app`
      directly (not via Finder/`open`, which swallow stderr): exit 2, `can't
      open file '.../Resources/app/main.py'`. Fixed the same way as Linux: the
      launcher now `execv`s `python3 -P -m <entry>`, which loads a sourceless
      `.pyc` exactly as happily as a `.py`. **Decision on the static check
      itself: skipped, deliberately.** A Mach-O launcher is opaque in a way a
      shell `AppRun` is not, so a static macOS equivalent (§5's original
      wording) would only assert an entry module exists — a weaker check,
      post-fix, than the regression test that pins the launcher's own argv
      (`test_the_launcher_never_names_a_source_file` in
      `test_plist_launcher.py`). The real-clang argv test plus the actual
      launch in §7 hold the line; a static conftest-driven check would be
      ceremony on top of them.
- [x] **iOS check functions and driver — done 2026-09-23. In CI the same day**
      via `ios_simulator` (§3.1/§3.3), closing the one platform that had no T3
      tier at all. `tests/artifact_checks.py::ios_app_problems` (required
      entries; a whole-bundle Mach-O arch sweep via the existing
      `machotools.read_macho_cpu_type` — no separate iOS Mach-O reader;
      `Info.plist` vs. config via `ios_expected_plist`, mirroring
      `macos_expected_plist`'s "call the production builder, drop the
      build-time key" shape), hermetic-tested in `tests/test_artifact_checks.py`,
      wired to a real bundle via `tests/platforms/ios/test_app_artifact.py`
      (`--ios-app`/`--ios-arch`/`--ios-project`) plus a `codesign --verify`
      test reusing macOS's `codesign_verify` wrapper directly (the tool is the
      same regardless of which bundle it signs). Findings in
      [`ios-t3-checks-findings.md`](ios-t3-checks-findings.md), including the
      Step 0 layout dump: an iOS `.app` is flat (no `Contents/`), and every
      compiled extension module — 120+ of them for `hello-kivy` alone — is
      hoisted by python-apple-support's `install_python` into its own
      `Frameworks/<name>.framework/`, leaving a plain-text `.fwork` stub
      behind. **Scope is capped by something external, and still is**: iOS
      `strip_source` is unreachable while every example pins `3.15.0b4` (§7,
      2026-09-14), and python.org still ships no final-release iOS
      `Python.xcframework` as of 2026-09-23 — confirmed against a real build
      the day this closed (`kivyforge doctor -p ios` still warns "no final
      CPython 3.15 found") — so the stripping and `.pyc`-magic checks, the
      ones that caught item 1 and the two launcher defects elsewhere, are not
      written; `ios_app_problems` takes no `stripped` parameter at all rather
      than carrying one nothing exercises. Revisit when a final 3.15 iOS
      xcframework ships.
- [x] **Windows check functions — done 2026-09-17. In CI since 2026-09-22**
      via `windows_onedir` (§5.3), completing the desktop set — all three
      desktop targets now run their T3 pass on every push rather than as a
      logged one-off. `windows_onedir_problems`
      in `tests/artifact_checks.py`, mirroring `linux_appdir_problems`'s shape
      (required entries, payload stripping scoped to `app`/`python/Lib/
      site-packages`, a PE-arch sweep of the whole tree via the new
      `platforms/windows/petools.py` reader, `.pyc` magic), hermetic tests in
      `tests/test_artifact_checks.py`, `--windows-onedir`/`--windows-arch`/
      `--windows-stripped` in `conftest.py`, and
      `tests/platforms/windows/test_onedir_artifact.py` (mirrors the macOS
      driver). Windows is the one desktop target immune to the AppRun-shaped
      launcher defect above: its bootstrap uses `runpy.run_module`, which
      resolves through the import system. **Found a real false-positive on the
      first real-bundle run** (see §7): pip's vendored `distlib` ships six
      prebuilt multi-arch launcher *templates* (`t32.exe`, `t64-arm.exe`, etc.)
      inside every installed pip, including the one staged into
      `python/Lib/site-packages` — flagged by the PE-arch sweep as "leaked"
      foreign-arch binaries. Fixed by excluding known distlib launcher-stub
      filenames from the sweep, with a hermetic regression test
      (`test_distlibs_own_launcher_templates_are_not_a_fault`) pinning the
      exclusion so a future broadening of the sweep's scope cannot silently
      reintroduce it.
- [x] **Merged `AndroidManifest.xml` and `Info.plist` contain what config asked
      for — done 2026-09-21.** `android_manifest_problems` in
      `tests/artifact_checks.py`, driven by
      `tests/platforms/android/test_merged_manifest.py`
      (`--android-merged-manifest` + `--android-project`) and **run in
      `android_gradle` after `kivyforge package`** — the manifest that job
      exported for the policy lint and then discarded on success is now
      asserted on every run. Four things worth carrying forward:
      - **Presence, never equality.** A real merged manifest carries
        androidx.startup's `InitializationProvider`, profileinstaller's
        receiver and the synthesized `DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`
        pair, none of which any `pyproject.toml` mentions. A set-equality
        assertion fails on every real build, and a check that always fails gets
        deleted rather than fixed. Same shape as the distlib false positive in
        the Windows box below.
      - **The highest-value keys are the ones AGP injects**, not the ones
        kivyforge generates: `package`, `versionCode`, `versionName`,
        `minSdkVersion`, `targetSdkVersion` all come from `build.gradle`'s
        `defaultConfig` and reach the artifact only through the merge, so no
        generation test can reach them at all.
      - **Expectations are imported, not restated.** The check calls the
        generator's own `effective_permissions`/`effective_features`/
        `screen_orientation`/`service_class_name` (the first two extracted from
        `generate_manifest` for this) rather than keeping a second copy of the
        auto-add and implied-feature rules — the same reasoning as the ELF/PE
        constants. It therefore cannot catch a generator that is *consistently*
        wrong; the hermetic generation tests own that, this owns the merge.
      - **It found a real bug on its first run.** `_attr_str` escaped a
        passthrough attribute value and `_attrs`' `quoteattr` escaped it again,
        so `android:description = "Rock & Roll"` shipped the literal text
        `Rock &amp; Roll`. Fixed in `generate/manifest.py`; regression pinned in
        `test_generate.py`.

      **The macOS `Info.plist` half is now genuinely wired, which it was not.**
      This file previously credited `macos_app_problems` with asserting
      "structure/optional-exact-match" — but its `bundle_id`/`executable`
      expectations had been optional since 2026-09-14 and **no driver ever
      passed one**, so the comparison had never run. An expectation nothing
      supplies is a check that never runs, which is this tier's own failure
      mode. `bundle_id` is replaced by an `expected_plist` dict covering every
      key config decides, produced by calling the *production*
      `build_info_plist` and dropping the two keys a config-only caller cannot
      know (`CFBundleExecutable`, `CFBundleIconFile`), and supplied by
      `test_app_artifact.py` from a new `--macos-project`. **Ran against a
      real bundle 2026-09-22** — the `macos-gate` fixture, both locally and in
      the new `macos_app` CI job (§5.3, §7) — closing the "needs the Mac"
      caveat this bullet used to end on.
- [x] **macOS code signature verifies** — `codesign --verify`, via
      `machotools.codesign_verify`, exercised in
      `test_app_artifact.py::test_the_app_is_codesigned` against the real
      notarized `dice-roller.app`.
- [x] **Signatures verify — done 2026-09-21**, closing the box for all three
      signable platforms (macOS was done 2026-09-14, above).
      - **Android:** `tests/platforms/android/test_apk_signature.py`, run in
        `android_gradle` against the release APK the throwaway keystore signed.
        It verifies at the project's own **`min_sdk`**, not apksigner's default,
        because the question worth answering is not "is this signature
        well-formed" but "will every platform version this project claims to
        support accept it" — a v1-only signature installs fine on API 23 and is
        what the platform ignores from 24 up, which is exactly why
        `[tool.kivy.android.signing].v1_signing` defaults off. The v1 scheme is
        therefore checked *against that setting* rather than against a fixed
        expectation. Release-only on purpose: a debug APK's signature is
        Gradle's, not the project's.
      - **Windows:** `tests/platforms/windows/test_authenticode.py`, both
        halves. `--windows-signed-exe` takes any signed PE, and
        **`windows_signing` now routes its own signed launcher through it**
        instead of a bare `signtool verify /pa` that read only the exit code —
        which is what first put the report parser under CI. **The built-app
        half closed 2026-09-22** with `windows_onedir` (§5.3): it packages the
        `windows-gate` fixture unsigned, signs the launcher *inside that
        bundle* through `SigntoolSigner`, and verifies it — so `signtool
        verify /pa` now runs against an artifact `kivyforge package`
        produced, which is what this box originally asked for.
        The signing is a separate job step rather than something `package`
        did, because Windows has no ad-hoc floor like macOS's: signtool needs
        a real certificate, and a per-run thumbprint in the fixture's
        `pyproject.toml` would change `pyproject_sha256` and break the same
        job's `lock --check`. The `--windows-onedir` + `--windows-project`
        driver path remains for a project that *does* configure signing; it
        is still local-only, since no CI fixture configures one.
      - **Read the counts, not the exit code or the word "verified."** A
        signed-but-untrusted binary prints a full certificate chain, "The
        signature is timestamped" and the word "verified" — every marker of a
        pass except `Number of files successfully Verified` and the `SignTool
        Error` lines. A real revoked-certificate case is what established that,
        and is now a fixture.
      - **Both parsers live in `artifact_checks.py`; both *spawns* live in the
        platform drivers.** Signature verification is the one thing in this
        tier that genuinely needs a tool, so the split keeps every function in
        `artifact_checks.py` hermetic, which is the property the
        no-toolchain rule was protecting.

### 5.2 Android T3 from a Windows host — **done 2026-09-23**

`android_windows_host` on `windows-latest`: `package -p android --abi x86_64`
(release, so `byte_compile`/`strip_source` actually apply) followed by the same
three T3 checks `android_gradle` runs. Both the "cheapest form" this section
asked for and the "middle form" — the local run is logged in §7.

**Release only, unlike `android_gradle`'s debug+release.** `byte_compile` and
`strip_source` are release-only tri-states, so the release path is the only one
that invokes `find_interpreter` at all; a debug build here would spend Gradle
time on Windows and exercise nothing this job exists for.

**The job logs which interpreter the resolver picked**, because that is the
thing under test and the answer differs by host. Measured on the dev box:
`find_interpreter("3.14.6")` returns `("py", "-3.14")` — the PEP 397 launcher,
resolving to CPython 3.14.7 **final**, 64-bit. That is the Windows-only
mechanism item 1's bug lived in. On a hosted runner `setup-python` puts 3.14 on
PATH while the launcher generally does not know about a hostedtoolcache
install, so `("python",)` is the likely winner there instead.

**The log line earned its place immediately: the first green run printed
`resolver picked: ()`, which is neither answer predicted above.** `()` means
"use the interpreter already running" — `find_interpreter` returns at its
`sys.version_info[:2] == target and is_final_release()` fast path, *before*
the `os.name == "nt"` candidate list is even built. Because `setup-python`
makes the runner 3.14 and the project ships 3.14, CI takes the identical
branch `android_gradle` takes on ubuntu.

**So state the coverage as it actually is.** `android_windows_host` proves
plenty that ubuntu does not — the NDK and Gradle toolchain on Windows, Windows
path handling through staging, byte-compilation on a Windows host, and the
full T3 pass over the APK it produced. What it does **not** reach is the
Windows *candidate search* itself: the `py` launcher, versioned executables,
and pre-release rejection. That remains covered only by the dated local run
in §7 (`('py', '-3.14')` → CPython 3.14.7 final) and by the unit tests in
`tests/bundle/test_pycompile.py`.

Closing that last sliver in CI would take forcing the search rather than the
fast path — e.g. an extra step invoking the resolver under a *different*
minor than the project ships, so the candidate loop has to run. Cheap, and
not done here; noted so it is a choice rather than an oversight.

One clarification worth leaving here, since it reads like a bug and is not:
`find_interpreter` returns `()` for "use the interpreter I am already running",
and `None` for "no match". A `()` in that output is a success.

### 5.3 A desktop build job — **decided and built 2026-09-22**

**Decision: a dedicated CI fixture with a committed lock, under test control
rather than in `examples/`.** `tests/fixtures/apps/linux-gate/` commits its
`pylock.linux.toml`; the `linux_appimage` job builds it on `ubuntu-latest` and
runs the Linux T3 pass over the AppImage. That closes the blocker this section
had been describing since 2026-09-13, and with it the first desktop build job
in the repo's history — before it, **no CI job ran `kivyforge build` or
`package` for any desktop target at all**.

**Why not either option this section originally posed.** The choice was framed
as "a Linux gate example, or lock-at-CI-time", and the recommendation below
leaned lock-at-CI-time. Both were answering the wrong question, because both
assumed the project being built has to be an *example*.

- **Against lock-at-CI-time for the gate.** Re-resolving on every push means
  the build inputs change when nobody touched the repo: a Kivy release, a bad
  transitive dep, a PyPI hiccup. The job goes red, someone investigates, and
  the answer is "the world changed". A gate that goes red for reasons you did
  not cause is one people learn to ignore — which costs more than the coverage
  it was buying.
- **Against a gate *example*.** The policy in
  [`common/03-lockfile-concept.md`](../common/03-lockfile-concept.md) is right
  about `examples/**`: `pyproject_sha256` hashes the whole `pyproject.toml`, so
  an overlay edit regenerates the lock and churns the diff with nothing pinned
  having changed. `dice-roller` carries macOS signing identity plus iOS and
  Windows overlays, so it is precisely the file that argument was written
  about. Item 4's Pi 5 gate arguably qualifies it for the evidence exemption;
  the churn makes it a poor choice anyway.

**Why a fixture escapes both objections.** The churn argument is about files
maintainers edit for cosmetic reasons, and nobody edits a fixture's overlay to
change an icon — it has no audience. The policy's other objection, that a
committed lock "can go silently stale", is about a lock kept for *reference*,
checked in and never built from; this one is downloaded, hash-verified and
built on every push, so a wheel or runtime that moves at its URL fails the very
next run. Nothing about it is silent, and no scheduled re-lock job is needed to
notice — that was considered and dropped as solving a problem that does not
arise here.

Roadmap item 5 had already committed to this shape independently ("a small
fixture-app set rather than testing against the full 11 examples"), so the lock
question largely dissolves once the fixture exists. `tests/` is pruned from the
sdist, so none of it ships.

**The fixture depends on Kivy on purpose.** A dependency-free app would make
the job green while inspecting almost nothing: payload stripping is scoped to
`usr/app` + `usr/lib`, and the ELF-arch sweep needs staged third-party binaries
to walk. Confirmed rather than assumed — a deliberate wrong-arch run reports
`usr/lib/Kivy.libs/libSDL2-*.so` and `kivy/_clock.cpython-313-x86_64-linux-gnu.so`
among others, none of which exist in a bare bundle.

**Two things this job covers that nothing else did.** It gates on
`kivyforge doctor -p linux` without a `continue-on-error` waiver (§5.9's
complaint about `android_gradle` has no Linux equivalent, and a headless runner
only costs a WARN), and it runs `kivyforge lock -p linux --check`, which is
meaningful **only** against a committed lock — against a gitignored one it can
only ever report "out of date", so nothing in CI had ever exercised that verb
against a real lock.

**macOS followed the identical shape the same day (2026-09-22), and it turned
out to need no signing story at all.** The "macOS additionally needs a signing
story" caveat this paragraph originally carried was wrong: `macos_package()`
(`kivyforge/platforms/macos/cli.py`) already falls back to an **ad-hoc**
signature — no certificate, keychain, or secret — whenever
`[tool.kivy.macos.signing]` is unset, exactly the CI-runner-safe floor
`linux_appimage` sits on. `tests/fixtures/apps/macos-gate/` commits its
`pylock.macos.toml` the same way; the `macos_app` job runs `doctor -p macos`
(every signing check `SKIP`s rather than `FAIL`s — nothing to waive), `lock -p
macos --check`, `package -p macos`, then the full T3 pass including
`--macos-project`. Proven locally first, on this Mac, before the job was
written: `doctor` clean, `lock --check` "up to date", `package` produced a
57-Mach-O ad-hoc-signed `.app` in ~4s, and the T3 driver 2 passed against it —
the **first real-bundle run of the `--macos-project` `Info.plist` comparison**
(added 2026-09-21, never previously exercised against anything but synthetic
trees; §5.1). **Negative controls**, both against the same real bundle: forcing
`--macos-arch x86_64` reported 11 arm64 binaries as foreign, by name
(`Contents/MacOS/macos-gate`, the staged `python3.13`, `libpython3.13.dylib`,
…); editing the built `Info.plist`'s `CFBundleIdentifier` directly (leaving the
committed fixture untouched) was caught by *both* checks independently — the
plist comparison flagged the mismatch, and rewriting a sealed resource
post-signing invalidated `codesign --verify` too. Rebuilt clean afterward;
`git status` clean before committing.

**Windows closed the set on 2026-09-22.** `tests/fixtures/apps/windows-gate`
(committed `pylock.windows.toml`, 7 packages — Kivy plus `kivy_deps.{sdl2,
glew,angle}` and `pywin32`, which is what gives the PE-arch sweep real DLLs to
walk) and the `windows_onedir` job: doctor (gating — the signtool and
certificate checks SKIP rather than FAIL when signing is unconfigured), `lock
--check`, `package -p windows`, the T3 onedir pass, and then the one step
neither of the other two desktop jobs can do.

**Windows is where the fixture pattern and the signature check meet**, and it
needed a different shape from macOS. macOS has an ad-hoc floor, so
`macos_app`'s artifact is signed by `package` itself; Windows has none —
signtool needs a real certificate. Putting a throwaway cert's thumbprint in
the fixture's `pyproject.toml` would change `pyproject_sha256` and break the
`lock --check` step in the same job. So the job packages **unsigned**, then
signs the *built launcher* through kivyforge's own `SigntoolSigner` (the
recipe `windows_signing` already proves) and verifies it through
`test_authenticode.py`. That is §5.1's "on a *built app* rather than on the
vendored launcher", finally satisfied.

All three desktop targets now have a build job. ~~What is left is §5.4's
Android emulator T4 and the iOS simulator job waiting on published wheels.~~
The iOS half is also done, one day later than this section's own "2026-09-22"
heading suggests: `ios_simulator` landed 2026-09-23 (§3.1, §3.2) — the wheels
it was supposedly still waiting on had actually been published since
2026-07-27 (§3.2 above), so this was unbuilt work, not a live blocker, by the
time this very paragraph was last edited. §5.4's Android emulator T4 followed
the same day — it did need the extra work this paragraph predicted, since a
real iOS simulator ships in the `macos-latest` image while an Android AVD has
to be created and booted, behind a `/dev/kvm` udev rule. **Both mobile targets
now have T4 in CI**, which was the last tier missing anywhere.

<details>
<summary>The original framing, kept because the reasoning it records is still
the reason the desktop examples stay gitignored</summary>

#### A desktop build job — and the lock blocker is real for *all three*

**Corrected 2026-09-13.** The first revision claimed the four
`examples/desktop/*` projects commit `pylock.windows.toml`. **They commit no
lock at all** — every one of them gitignores `pylock.*.toml`. The only committed
locks in the repo are `examples/mobile/hello-android/pylock.android.toml`,
`examples/mobile/hello-sdl3/pylock.android.toml`, and
`examples/mobile/hello-kivy/pylock.ios.toml`.

That changes the planning conclusion, not just a detail. A **Windows** build job
has the same blocker as Linux and macOS, so "Linux is cheapest" was resting on a
Windows lock that does not exist.

**And this is less open than it looks — there is already a policy, and it is not
here.** [`common/03-lockfile-concept.md`](../common/03-lockfile-concept.md)
§"Example-repo lock policy" owns this: `examples/**/pylock.*.toml` is gitignored
*deliberately*, because `pyproject_sha256` covers the whole `pyproject.toml`, so
any overlay edit churns a lock that pinned nothing new, and a lock kept for
reference value goes stale silently. The carve-out is **on-device gate
examples** — `hello-android`, `hello-sdl3`, `hello-kivy` — whose locks are
committed because they are *evidence*, recording the exact wheel hashes that
passed a specific validated run.

So "the examples must gain committed locks" was the wrong framing twice over: the
desktop examples' gitignore is a decision, not an oversight, and flipping it
would contravene a documented policy this file failed to cite. What actually
remains is narrower:

- **give Linux a gate example** whose committed lock backs a real validated run,
  which is exactly the exemption the three mobile gates hold; or
- **lock at CI time** for desktop jobs, accepting a resolver run and drift as a
  named failure mode.

**The second looks stronger for desktop, which reverses this file's earlier
lean.** The mobile gates earn committed locks because their wheels come from a
bridge index that is rebuilt and not bit-reproducible — the lock is the only
thing tying a result to the binaries that produced it. Desktop wheels come from
PyPI, which is immutable, so a committed desktop lock buys much less evidence
while taking on the churn and staleness the policy objects to. A committed Linux
lock becomes worth revisiting when item 4 gives Linux a real on-device Pi gate,
because then it *is* evidence and qualifies on the documented grounds. Recorded
as a recommendation, not a decision.

With that settled, `ubuntu-latest` is still the cheapest *CI* desktop job — no
signing identity, no Mac, and it fills the emptiest column. But from this dev
box a Windows build needs no other OS and
`examples/verify-windows-examples.ps1` already exists to drive it (§3.1), so the
cheapest *evidence* and the cheapest *job* are different targets.

</details>

### 5.4 T4 on an Android emulator, in CI — **done 2026-09-23**

`android_emulator` boots an API-35 `google_apis` x86_64 AVD on `ubuntu-latest`
and runs `kivyforge run --smoke --release`. **T4 now runs in CI**, which was
the last tier missing and the last thing standing between item 5 and its own
"done when".

**`--release`, not plain `--smoke`.** The release variant is byte-compiled,
stripped and R8-processed, so this is the tier that would have caught roadmap
item 1 — a stripped bundle the device refuses to import — without a human
holding a phone. A debug smoke run exercises the load model but not the
stripping, which is the part with the history. `android/06` calls this exact
shape the "required release gate"; CI now demonstrates it rather than only
prescribing it.

**The "needs a self-hosted runner" assumption was stale.** `android/06`'s
gate table said `run --smoke` is "not hosted CI" because an emulator implies
a self-hosted machine. Hosted `ubuntu-latest` exposes `/dev/kvm` — to the
`kvm` group, hence the udev rule the job applies — so an x86_64 AVD boots
fast enough to gate on. That row is corrected.

**Rehearsed locally before the job was written**, on the AVD this box already
had: `run --smoke --release --serial emulator-5554` against API 35 x86_64,
`Contract smoke test PASSED`, Gradle 1m25s and 2m10s end to end. That is also
the first logged smoke run since 2026-07-27 and the first on the release
variant on an emulator — see §7.

Physical-device runs remain manual, and remain what
[08-compatibility-matrix](../platforms/android/08-compatibility-matrix.md)'s
**Validated** rows cite. What changed is that a regression no longer waits for
someone to run one by hand.

### 5.5 `kivyforge run` cannot reach release stripping at all — **done 2026-09-23**

This is a **product** hole, not only a test gap, which is why §5.4's predecessor
understated it. `android_run()` calls `android_build(..., debug=True)`
unconditionally and then looks for `_debug_output(...)`, so there is no flag that
makes `run` produce a release build. Since Android applies
`byte_compile`/`strip_source` in **release only**, the command developers use
most can never exercise stripping — and any test written against `run` today
would be testing the branch that was already fine. Fix the command first, then
cover it.

**This is not Android-only, and on 2026-09-13 it stopped being hypothetical.**
`linux_run()` calls `linux_build(...)`, which hardcodes `release=False`, so
`package` is the only Linux verb that reaches `strip_source` — and `package`
emits a distributable nobody launches while iterating. That gap is exactly where
the `AppRun` defect in §7 lived: shipped, reproducible in one command, and
invisible to every path a developer actually uses. The cost of this hole is now
measured, not argued.

**Closed in two halves.** Android got `run --release` on 2026-09-22. The
desktop half landed 2026-09-23, and it was **wider than this section said**:
the text above names Linux, but `macos_run` and `windows_run` hardcoded the
same `release=False` (`windows_build` in its body, `macos_run` by never
passing the parameter `macos_build` already had). All three now take
`--release`, threaded through `Platform.run` to the bundler — the same
`release=True` build `package` does, into the `build/<platform>/` tree `run`
always launches. Two refusals rather than silent drops: `--release
--no-build` (nothing records which flavor the existing build was, so
accepting it would claim a stripped build that may not exist), and `run -p
ios --release` (an iOS release is an archive + `.ipa`, not a simulator
install).

**Validated end to end on two of the three**, each with a negative control,
because a check that passes a stripped build proves nothing unless it also
fails an unstripped one (§7, 2026-09-23):

- **Windows** (`windows-gate`, local): `run --release` printed the
  byte-compile step "(.pyc only)", the app launched and stayed up, and the
  existing T3 driver with `--windows-stripped` passed against the tree `run`
  left behind. Plain `run` then printed no byte-compile step, and the same
  assertion **failed** on `app/main.py` plus 1,194 `.py` files in
  site-packages.
- **Linux** (`linux-gate`, WSL2 on ext4): the same shape. `run --release`
  passed the stripped T3; plain `run` failed it with 336 `.py` files and no
  `.pyc`. The app's own startup traceback showed the difference too: release
  frames name `usr/lib/kivy/...` with no source text, plain frames print it.
- **macOS: hermetic only.** Same code path as the other two, exercised by the
  unit tests; no Mac run was made for this change.

Hermetic coverage: `release` reaching the bundler through the real CLI in
both directions on all three platforms (so an inverted default cannot pass),
the `--no-build` refusal, the iOS refusal, and desktop forwarding in the
shared verb. Re-hardcoding `release=False` fails the three `True` legs.
**Not in CI:** `run` launches a GUI app and blocks on it, and the build it
performs is the one `package` already runs under T3 in `linux_appimage`,
`macos_app` and `windows_onedir`. What was new here is the wiring from `run`
to that build, and that is what the unit tests pin.

### 5.6 Host-dependent cases with no test at all

From §4, the ones with no producer of any kind: Windows path-length /
`longPathAware`, and case-insensitive staging collisions — though the second
now has a **reproduction** rather than only a suspicion, logged 2026-09-22 in
§7: staging the embedded runtime onto a case-insensitive filesystem fails on
the terminfo database, which ships `hp70092` beside `hp70092A`. Observed on
WSL2 writing to `/mnt/c`. Still no automated producer; what changed is that
the failure mode is now known to be real and to have a concrete trigger. Both are cheap policy
or generation tests rather than toolchain work — the model is
`tests/test_message_encoding.py`, which turned a host-specific footgun into a
static check over the source tree.

### 5.7 Wire `requires_device`, or remove it — **removed 2026-09-23**

Removed, which was the second of the two options this section offered. No test
ever carried the marker, so `KIVYFORGE_DEVICE_TESTS=1` enabled nothing while
implying that device coverage existed behind a flag — a silent skip with extra
steps, and one that would have kept reporting success after real device tests
were added and broken.

Wiring it instead would have meant writing ADB-driven tests speculatively, from
a host with no device attached, which is how you get tests that pass because
they assert nothing. Real device runs stay manual and logged in §7, where the
2026-09-13 Pixel 8a session and the 2026-09-21 iPhone runs already are.

`tests/conftest.py` records the reasoning next to the two surviving markers: if
ADB-driven tests are ever written, the marker comes back **with** them rather
than ahead of them.

### 5.8 Pin the floating jobs — **done 2026-09-23**

**The rule, stated so it can be applied without re-deriving it: a job that is
the sole CI proof of a platform pins an exact minor.** Nothing about
byte-compilation, nothing about magic numbers — those are `android_gradle`'s
separate and stronger reason. This rule is about *host drift*: an unpinned
sole-platform-proof tests whichever minor the runner image happens to ship,
so a break on one minor versus another is invisible, and the interpreter can
change under us the way the MSVC toolset did three times (§7).

All seven such jobs now pin — `android_gradle` and `android_emulator` (3.14,
which they *must*, for the magic number), and `linux_appimage`,
`windows_onedir`, `macos_app`, `macos_integration` and `ios_simulator` (3.13,
for the rule above).

**`ios_simulator` is worth recording, because it is where the two reasons got
confused.** It landed unpinned, with a comment arguing that plain
`build`/`run` never byte-compiles so the host minor "has nothing to match".
That is correct and it is beside the point: it answers `android_gradle`'s
argument, not this one. Every step of that job runs kivyforge itself under
the host interpreter, and it is the only job exercising the iOS code paths
against a real Xcode — exactly the invisibility this section was written
about. Pinned 2026-09-23.

**Deliberately still floating:** `lint`, `package`, `sdl_glue_sync`,
`windows_launcher`, `windows_signing` and the two `revendor_*` jobs. None is
the sole proof of a platform — they are cross-cutting, or they exercise a C
toolchain and a signing tool that do not turn on the Python minor — and
pinning them would trade away the early warning floating buys. §3.1 states
the split so "finish pinning the rest" does not read as leftover work.

### 5.9 Let doctor fail the Android job — **done 2026-09-23**

The `continue-on-error: true` is gone; `android_gradle`'s doctor step now
gates, like the three desktop jobs'.

**The waiver turned out to be unnecessary rather than needing the allow-list
this section proposed.** Its stated reason was that doctor reports the
known-interim 4 KB-aligned Kivy wheel as a FAIL — true in general, but not at
that point in the job: `_check_16k_alignment` runs only
`if project_dir.is_dir()`, meaning the *generated* project, which the `build`
step below has not created yet. The check is not passing there; it is not
registered.

Confirmed against a real run rather than inferred: the 2026-09-23
`android_gradle` doctor step reports **0 FAIL and 2 WARN** (no device
attached, no AVD), and doctor's exit code is
`worst_status(results) is not Status.FAIL`, so WARNs never gated anyway. What
the waiver actually bought was that the job which exists to prove the Android
toolchain ignored *every* diagnostic doctor produced — the thing this section
objected to.

The workflow comment records the condition under which this reverses: if a
future change stages jniLibs before the doctor step, the interim-wheel FAIL
becomes reachable and the allow-list originally proposed here is the fix, not
the blanket waiver.

### 5.10 Byte-compile the embedded stdlib at build time — **closed 2026-09-17**

Both pieces landed together, as this section required. The staged stdlib is
byte-compiled during staging on all three desktop targets (sources kept —
`site-packages` is left to the payload compile under its own strip setting), and
the compile subprocess now runs with `PYTHONDONTWRITEBYTECODE=1` so its own
imports stop seeding the artifact with an arbitrary subset of caches.

**Re-measured on Windows** (§7, 2026-09-17): `import kivy` in a real packaged
`dice-roller` bundle costs **66 ms compiled against 276 ms source-only** — 4.2×,
~210 ms off every launch.

**Re-measured on Linux** the same day (§7): **34 ms compiled against 214 ms
source-only** — 6.3×, ~180 ms off every launch, on the host that had the most
to gain because an AppImage can never cache at runtime. The AppImage itself
carries the same 633/633 stdlib pair.

**Re-measured on macOS** the same day (§7), which also owns the question no
other host can answer — the compile runs before `codesign`, so a bundle that
writes into itself afterward would invalidate its own signature. It doesn't:
`codesign --verify --deep --strict` passes both before and after a real launch
(`Contents/MacOS/*` run directly, reaching "Start application main loop"), and
the `.pyc` count (969) is identical before and after — `PYTHONDONTWRITEBYTECODE`
in the launcher holds under the shipped, compiled stdlib exactly as it did
under the source-only one on 2026-09-14. The stdlib ships 633 `.py` **and** 633
`.pyc` (sources kept), the app payload stays `.pyc`-only (0 `.py`). Timing, same
bundled interpreter, `PYTHONDONTWRITEBYTECODE=1`, min of 5: `import kivy`
**13.4 ms compiled vs 85.8 ms source-only** (deleting the stdlib
`__pycache__`, which — expectedly — also breaks the signature, so the example
was re-packaged afterward) — **6.4×, ~72 ms off every launch**. Same shape as
Windows and Linux; the ratio is largest here because this Mac's absolute
numbers are smaller across the board (Apple M5 Pro), not because the fix
behaves differently.

All three desktop hosts are now measured, independently, the same day: **4.2×
(Windows), 6.3× (Linux), 6.4× (macOS)** — a real, host-specific number in every
case, not one host's result assumed for a shared code path.

The original finding, kept because it is why the work exists:

Measured, not suspected (§7, 2026-09-15): shipping the stdlib as pure source
costs **~170 ms on every launch** — `import kivy` takes 0.21 s against 0.04 s
with a compiled stdlib, a ~5× difference that `-X importtime` attributes to
parsing `typing`, `inspect`, `enum`, `logging` and `shutil`.

Nothing was buying the fast number honestly. A `.AppImage` never could, because
its squashfs is read-only, so it has paid full parse cost on every launch since
the beginning. The folder form *did*, by writing `__pycache__` back into itself
on first run — which is exactly the self-mutation `PYTHONDONTWRITEBYTECODE` now
prevents, so as of that fix both shapes pay it permanently. The launcher change
was right, and it made this gap the load-bearing one.

Two pieces, both cross-platform, neither belonging to a single host:

1. **Compile the runtime's stdlib during staging**, so the artifact ships
   usable bytecode. macOS wants this as much as Linux — its launcher comment
   should be revisited at the same time, since the environment variable becomes
   belt-and-braces rather than the whole defence.
2. **Stop the compile step polluting its own output.** `byte_compile` shells out
   to the staged interpreter, whose own imports currently deposit 41 stdlib
   `.pyc` into `usr/python` — an arbitrary subset determined by what
   `compileall` happened to import, so the artifact is not reproducible in that
   subtree. Passing `PYTHONDONTWRITEBYTECODE=1` in the subprocess environment
   fixes it without affecting the intended output, because `compileall` writes
   through `py_compile` explicitly and ignores the variable (verified). Held
   back only because `bundle/pycompile.py` is shared with macOS, where those
   caches are sealed into the code signature today.

Do (1) and (2) together: (1) alone leaves the incidental caches, and (2) alone
makes every launch permanently slow with nothing to show for it. *(Done
2026-09-17 — both, in one change, per this paragraph.)*

---

## 6. Manual checklist

These need a human, credentials, or hardware CI cannot have. Every one of them
should produce a dated line in §7 — an unlogged manual test did not happen.

- [x] **iOS device install + launch** on real hardware — 2026-09-14, iPhone14,3,
      `build`/`run`/`package --device`, `hello-kivy` rendered on-screen. Found
      and fixed a `--team-id` propagation bug along the way (§3.2, §7). Not
      re-proven anywhere, so treat as a point-in-time result, not standing
      coverage.
- [ ] **iOS `strip_source`** — still unverified, and now known to be
      structurally unrunnable rather than merely untried: every iOS example
      pins `3.15.0b4`, and `package -p ios` requires a *final* CPython to
      byte-compile. Item 1 proved the Android half; the iOS half stays open
      until either 3.15 ships or some example is pinned to an already-final
      minor.
- [x] **Notarization** — five `notarytool` submissions since 2026-07-07, all
      `Accepted` (`dice-roller`, §7). This item was wrongly marked open; nobody
      had run `notarytool history` before 2026-09-14.
- [ ] **Authenticode with a real certificate.** `windows_signing`'s self-signed
      loop proves the `SigntoolSigner` plumbing, not timestamping against a real
      CA chain or SmartScreen behaviour.
- [x] **Raspberry Pi 5**: cross-build T2+T3 on WSL2, launch T4/T5 2026-09-17
      (item 4). Pi 4 untested. See
      [`aarch64-pi-target-findings.md`](aarch64-pi-target-findings.md).
- [ ] **Physical Android device**, both ABIs — CI can only reach `x86_64`.
- [ ] **Windows interactive matrix** that `test_launcher_exe.py` documents as out
      of scope: >260-char paths, shortcut launches, Ctrl-C, no-console-flash.
      Partly automatable as §5.6; the rest is genuinely interactive.
- [ ] **Desktop launch smoke on each desktop target** — the T5 cells the first
      revision marked `n/a`, which wrongly implied out-of-scope rather than
      unproven. `examples/verify-*` scripts (§3.1) drive most of it.
- [ ] **Store submission** — Play Console and App Store Connect.

---

## 7. Results log

Append-only. Date, target, what ran, what it proved. **Say which host**, and for
Linux say whether it was WSL2 or bare metal (§4).

| Date | Target | Tier | Host | Result |
|---|---|---|---|---|
| 2026-07-24 | Android `x86_64` | T4 (local) | — | `kivyforge run --smoke` green on an x86_64 API-31 emulator under first-party kivyforge `build`/`run` (not p4a), promoting CPython 3.14 / Kivy 2.3.1 / SDL2 to Validated. Backfilled into this log 2026-09-13 from [`08-compatibility-matrix.md`](../platforms/android/08-compatibility-matrix.md); see §3.3 for why it was missing. |
| 2026-07-25 | iOS simulator `arm64` | T2 + T4 (local) | macOS 26.5.2 / Xcode 26.6, Swift 6.3.3, pip 26.1.2 | `doctor -p ios` exit 0; the pip `default_environment` shim proven against a real resolve (`sys_platform = ios`) and its guardrail proven to refuse rather than fall back; `lock -p ios --update` including `swift package resolve` for `keychain-spm`; **`build -p ios --simulator` and `run -p ios --simulator` both exit 0**, `hello-kivy` rendering on an iPhone Air / iOS 26.5 simulator with a screenshot. Full detail in [`ios-validation-findings.md`](ios-validation-findings.md). **Twice-corrected:** logged as bare "T2", then on 2026-09-13 wrongly *demoted* to "T0/T1 — not `xcodebuild`" on the strength of its summary line, which is how this file came to assert that no iOS toolchain had ever run. Step 6 of the findings says otherwise. Read the evidence, not the abstract. |
| 2026-07-27 | iOS simulator `arm64` | T2 + T4 (local) | macOS / Xcode 26.6 | **All six** iOS examples — `hello-kivy`, `pyobjus-ball`, `pyobjus-deviceinfo`, `keychain-spm`, `mobile-geometry`, `svg-explorer` — build, launch and render on an iPhone Air / iOS 26.5 simulator, resolving from the `kivy-mobile-wheels` index after `examples/wheels/ios/` was deleted. `keychain-spm` also exercises `swift package resolve`. See [`mobile-wheels-phase6-ios-findings.md`](mobile-wheels-phase6-ios-findings.md). Backfilled here 2026-09-14. |
| 2026-07-27 | Android `x86_64` | T4 (local) | — | Same `run --smoke` gate green for Kivy 3.0.0.dev0 / SDL3 via the `hello-sdl3` example, on the emulator and a Pixel 8a. Backfilled 2026-09-13. |
| 2026-09-13 | Android `arm64_v8a` (Pixel 8a) | T3 + T5 | Windows | `strip_source` release build verified end to end. Installed payload: 0 `.py`, 1036 `.pyc`, 0 `__pycache__`, `app/main.pyc` sourceless. Header magic 3627 (3.14 final). Kivy imports from `.pyc`, GL comes up (Mali-G715, ES 3.2), app renders. **This is also the only run of the Windows-host byte-compile path** (§5.2) — done by hand, not re-proven. |
| 2026-09-13 | Android `arm64_v8a` (Pixel 8a) | T5 | Windows | Device-state gotchas worth not rediscovering: a locked screen or a raised notification shade both hold focus and SDL never gets a surface, so the app looks hung at `Window: Provider: sdl3`. `wm dismiss-keyguard`, `cmd statusbar collapse`, `svc power stayon true`. |
| 2026-09-13 | Android `x86_64` (CI) | T3 | ubuntu | Artifact assertions added to `android_gradle` for the debug and stripped release APKs. Validated locally against the two real `arm64-v8a` APKs from item 1 first: the stripped one passes under CPython 3.14 and is correctly rejected under 3.13 (magic 3627 vs 3571), and claiming the wrong ABI is caught across all 120 shared objects. |
| 2026-09-13 | Windows `amd64` (CI) | T2 | windows | `windows_launcher` went red: byte mismatch at the same size with the pinned toolset (MSVC 14.51.36231 + SDK 10.0.26100.0) reported as *used*, i.e. a serviced compiler inside an unchanged version string — the drift `/EMITTOOLVERSIONINFO:NO` cannot cover. Last green was 2026-08-12; the hosted image rolled. Fixed by `revendor_launcher`, which changed the binary and `SHA256SUMS` but **not** `TOOLSET.txt`. Third occurrence. |
| 2026-09-13 | Linux `x86_64` | T0/T1 | **WSL2** (Ubuntu, Python 3.14.4) | Editable install plus `doctor -p linux` green on the `dice-roller` example, including the new byte-compile check reporting the native path ("the staged runtime compiles its own payload"). WSLg provides `wayland, x11`, so Linux T4 is locally reachable. No build or AppImage yet — this is environment readiness, not target coverage. |
| 2026-09-13 | Linux `x86_64` | T2 | **WSL2** (Ubuntu, Python 3.14.4) | **First execution of `appimagetool` in this project's history.** `kivyforge package -p linux` on `dice-roller` built the AppDir and wrapped it (appimagetool 1.9.1, fetched not installed — no sudo) into a 118 MB type-2 AppImage in ~21 s. The lock was generated locally per the §5.3 policy, not committed. |
| 2026-09-13 | Linux `x86_64` | T3 | **WSL2** (Ubuntu, Python 3.14.4) | Linux artifact assertions landed (`linux_appdir_problems`, `linux_appimage_file_problems`; 36 hermetic tests, driver behind `--linux-appimage`). Pointed at the real stripped release AppImage they **failed, correctly**, on a bug that had shipped: see the T2→T4 row below. Re-run green after the fix, and clean against the unstripped `build` AppDir. **Caveat that limits this row:** a Linux `x86_64` build on a Linux host is *native*, so `select_compiler()` took the staged-interpreter path and **never called `find_interpreter()`** — the search path where item 1's bug actually lived (§5.2) remains uncovered by this run. |
| 2026-09-13 | Linux `x86_64` | T3 → product fix | **WSL2** (Ubuntu, Python 3.14.4) | **Every default `kivyforge package -p linux` produced an AppImage that could not start.** `strip_source` defaults to release-only, `package` is the only verb that sets `release=True`, and `AppRun` was rendered from a template hardcoding `exec .../usr/app/<entry>.py` — the file the same build had just byte-compiled and deleted. Exit 2 before Python started; reproduced on the real artifact, not inferred. Invisible because `build` and `run` both hardcode `release=False` (the Linux instance of §5.5), so no path a developer uses while iterating ever reaches stripping. Fixed by running the entry point as a module: `-P -m <entry>`. `-P` is load-bearing — bare `-m` would put the launch directory on `sys.path`, which exec'ing a script never did. |
| 2026-09-13 | Linux `x86_64` | T4 (local) | **WSL2** (Ubuntu, Python 3.14.4) | Post-fix stripped release AppImage launches: SDL2 window, Kivy reaches `Start application main loop`, rendering a payload of 0 `.py` / 336 `.pyc` / 0 `__pycache__` with `usr/app/main.pyc` sourceless. `.pyc` magic 3571 — the AppDir's own staged CPython 3.13.14, *not* the 3.14.4 running pytest, which is why the checks derive expected magic from the shipped runtime rather than the runner. GL is **llvmpipe software rendering under WSLg**, so this proves the payload imports and the app reaches first frame; it is not evidence about a real GPU driver. |
| 2026-09-14 | macOS `arm64` (`dice-roller`) | T2 + T3 (local) | macOS 26.6.2, Xcode 26.6 | Real Developer-ID-signed, notarized, stapled `.app` inspected directly: `codesign --verify --deep --strict` valid, `stapler validate` and `spctl -a -t exec` both accept it (source=Notarized Developer ID), `lipo` confirms `arm64`-only. `notarytool history` (once a keychain profile existed) showed **five `Accepted` submissions since 2026-07-07** — corrects §6's "Notarization" item, which had been marked open on the strength of nobody having checked. `strip_source` confirmed correctly scoped: `app/`+`lib/` fully `.pyc`-only, embedded stdlib deliberately untouched, all 336 shipped `.pyc` files match the *bundled* interpreter's magic (3.13.14), not the host's (3.14.7). Full detail: [`macos-ios-validation-findings.md`](macos-ios-validation-findings.md). |
| 2026-09-14 | macOS `arm64` | T3 infra | macOS 26.6.2 | Added `machotools.read_macho_cpu_type`/`cpu_type_name` (pure-Python, no `lipo` subprocess), `artifact_checks.macos_app_problems`, hermetic tests, and `tests/platforms/macos/test_app_artifact.py` (`--macos-app`, plus a `codesign_verify` check) — the macOS half of §5.1, mirroring `test_apk_artifact.py`. Run against the real `dice-roller.app` above: both tests pass. Full hermetic suite: exit 0, coverage 91.96%. |
| 2026-09-14 | iOS simulator `arm64` | T2 + T4 (local) | macOS 26.6.2, Xcode 26.6 | Regression re-check, no drift since 2026-07-27: `doctor -p ios` (2 expected `WARN`s only), `build -p ios --simulator`, `run -p ios --simulator` all exit 0; `hello-kivy` renders correctly on iPhone Air / iOS 26.5. `pylock.ios.toml` unchanged. |
| 2026-09-14 | iOS simulator `arm64` (`hello-kivy`) | `strip_source` attempt | macOS 26.6.2 | `package -p ios` degrades to shipping source: "no final CPython 3.15 found (this project ships 3.15.0b4)". Confirmed **every** iOS example in the repo pins `3.15.0b4`, so this is currently unrunnable anywhere in-repo, not just untried. Data-safety check passed: the materialized `app/` is a real copy (not a symlink), and the real working-tree `main.py` was untouched. |
| 2026-09-14 | iOS device `arm64` (iPhone14,3) | T2 + T4 + T5 | macOS 26.6.2, Xcode 26.6 | **First physical-device run in this repo.** `build -p ios --device`, `run -p ios --device` (after unlocking the phone — same failure mode `verify-ios-device.sh` documents), and `package -p ios --export-method development` all succeeded; `hello-kivy` rendered on-screen. Found and fixed a real bug: `--team-id`/`KIVYFORGE_TEAM_ID` was resolved by `preflight_signing()` but never reached the generated Xcode project's `DEVELOPMENT_TEAM`, so a correct override still failed to build. Fixed across `buildsettings.py`/`generator.py`/`materialize.py`/`cli.py`; two regression tests added; full iOS suite (494 tests) + lint green after. `hello-kivy/pylock.ios.toml` re-locked to the Kivy build (`dev202607301604`) that passed this run, per the on-device-gate lock policy (§5.3). `pyproject.toml`'s `team_id` deliberately left blank — signing used `KIVYFORGE_TEAM_ID` for this session, not a hardcoded personal team ID in a shared example. |
| 2026-09-14 | macOS `arm64` (`dice-roller`) | defect repro | macOS 26.6.2 | Confirmed [`macos-launcher-strip-source-prompt.md`](macos-launcher-strip-source-prompt.md)'s inference: ran the notarized `.app`'s `Contents/MacOS/*` directly (not via Finder/`open`, which swallow stderr) — exit 2, `.../Contents/Resources/python/bin/python3: can't open file '.../Contents/Resources/app/main.py': [Errno 2] No such file or directory`. Verbatim match to the Linux `AppRun` defect fixed 2026-09-13, same root cause: `strip_source` deletes `main.py`, the launcher still named it by path. **Every prior macOS T2/T3 pass (§7, 2026-09-14 above) had been against an artifact that could not start** — signing and notarization say nothing about launchability. |
| 2026-09-14 | macOS `arm64` (`dice-roller`) | launcher fix | macOS 26.6.2 | `kivyforge/platforms/macos/launcher.py`: `execv`s `python3 -P -m <entry>` instead of a `.py` path — same fix as the Linux `AppRun`, mirrored in C. Also set `PYTHONDONTWRITEBYTECODE=1`, a second, previously-unreachable defect the *first successful launch* immediately surfaced: importing the embedded stdlib (shipped as `.py` — stripping is scoped to `app`/`site-packages` only, by design) wrote `__pycache__` into the signed bundle, and `codesign --verify` then reported "a sealed resource is missing or invalid" — a notarized `.app` invalidating its own signature on first launch, on every launch, for every macOS app in the repo, discovered only because nothing had ever launched one before. Two regression tests added (`test_the_launcher_never_names_a_source_file`, `test_never_writes_bytecode_into_the_signed_bundle`) plus two real-clang argv/env tests. `clang -Wall` clean. Full hermetic suite + lint green. |
| 2026-09-14 | macOS `arm64` (`dice-roller`) | T2 + T3 + T4 (local) | macOS 26.6.2 | **macOS's first successful app launch, ever, in this repo.** Repackaged (re-signed, re-notarized, re-stapled) with both fixes; `Contents/Resources/app/` still `.pyc`-only. Ran `Contents/MacOS/*` directly: Kivy/SDL2 initialized, GL came up (Apple M5 Pro, OpenGL ES 2), "Start application main loop" — **rendered, visually confirmed**. `codesign --verify --deep --strict` on the bundle *after* the real launch: still "valid on disk" — the `PYTHONDONTWRITEBYTECODE` fix holds. T3 driver (`test_app_artifact.py --macos-app ... --macos-stripped`) re-run against this exact bundle: both tests pass. |

| 2026-09-15 | Linux `x86_64` (`dice-roller`) | bytecode-write measurement | **WSL2** (Ubuntu, Python 3.14.4) | Both claims in [`linux-launcher-bytecode-prompt.md`](linux-launcher-bytecode-prompt.md) confirmed from evidence. **Stripped folder AppDir** (`package -f folder`): 377 `.pyc` before, launch wrote **75 new**, every one under `usr/python` — the payload is sourceless, so nothing landed there. **Unstripped** (`build`): 3 before, launch wrote **209**, of which **100 landed in the payload itself** (`usr/app/__pycache__/main.cpython-313.pyc` plus 99 under `usr/lib`). **`.AppImage`**: immune, and proven rather than assumed — `/proc/<pid>/mounts` reports the squashfs `ro,nosuid,nodev`, and after a minute of running the live mount still held exactly the 41 stdlib `.pyc` it was built with, against the 75 the folder form gained from the same imports. The folder form is also the tree the T3 driver inspects, so **launching an artifact under test had been mutating it**. Also corrects a standing assumption: WSL2 *does* have `/dev/fuse` here, so the `.AppImage` mounted and ran directly rather than needing `--appimage-extract`. Full detail: [`linux-launcher-bytecode-findings.md`](linux-launcher-bytecode-findings.md). |
| 2026-09-15 | Linux `x86_64` (`dice-roller`) | unpredicted finding | **WSL2** (Ubuntu, Python 3.14.4) | **The build pollutes its own output before any launch.** A stripped AppDir ships 41 stdlib `.pyc` in 6 `__pycache__` dirs that no user action created: `byte_compile` shells out to the *staged* interpreter to compile the payload, and that subprocess's own imports write caches into `usr/python`. An unstripped `build`, which never invokes it, ships 3. `AppRun`'s `PYTHONDONTWRITEBYTECODE` cannot reach this — the compile subprocess needs it in its own env. The one-line fix is safe in principle (confirmed: the variable does not suppress an explicit `compileall`, which writes through `py_compile`) but is **not applied here**: `bundle/pycompile.py` is shared with macOS, where these caches are currently sealed into the code signature, and that is not a change to make from a host that cannot verify it. See §5.10. |
| 2026-09-15 | Linux `x86_64` (`dice-roller`) | launcher fix | **WSL2** (Ubuntu, Python 3.14.4) | `AppRun` now exports `PYTHONDONTWRITEBYTECODE=1`. Re-measured both shapes after the fix: stripped 377 → **377**, unstripped 3 → **3**, zero new files either way, payload `__pycache__` count **0 against 100** before — and both still reach "Start application main loop". `_linux_payload_problems` gained the unstripped-`__pycache__` case, phrased to accuse the launch rather than the build: a freshly staged AppDir has none (measured: 336 `.py`, 0 `.pyc`), so its presence means the artifact was written to afterwards. 3 tests added; full suite 2707 passed, 52 skipped, ruff clean. |
| 2026-09-15 | Linux `x86_64` (`dice-roller`) | startup cost | **WSL2** (Ubuntu, Python 3.14.4) | **The number that decides whether build-time stdlib compilation gets scheduled.** `import kivy` under the bundled 3.13.14 with `AppRun`'s environment, 5 runs each: **cold 0.20–0.22 s** (no stdlib cache and writes suppressed — which is the `.AppImage`'s permanent state, and now the folder form's too), **warm 0.04–0.05 s** after `compileall` over the stdlib. Roughly **5×, ~170 ms on every launch**. `-X importtime` attributes it to source parsing: `typing` 28 ms self, `inspect` 17 ms, `enum` 12 ms, `logging` 9.4 ms, `shutil` 8.8 ms. The fix above makes the slow number permanent for the folder form, which used to buy the fast one by mutating itself — an honest trade, but it raises the value of §5.10. Measured on a `compileall`-warmed copy in `/tmp`, discarded after. |

| 2026-09-16 | macOS `arm64` (`dice-roller`) | build/package output, local | macOS 26.6.2, Xcode 26.6 | Full suite green (92.68%) — first real run of `tests/cli/test_build.py`/`test_package.py`/`test_build_run_open.py` against the `build`/`package` output contract (`89798096`), which is `requires_symlinks` and skips on the Windows host where the four commits were authored. `build -p macos` human mode: stdout exactly `Built build/macos/Dice Roller.app`, no ANSI when piped; `--json` matches spec exactly. `package -p macos --json` exercised **both** signing tiers: with the identity checked into this example's `pyproject.toml` (real Developer ID + notarization, one `app` artifact, no warning), and with it deliberately, temporarily cleared (`KF-SIGNING-UNCONFIGURED` warning, one `app` artifact, exit 0) — restored after, `git status` clean. Full detail: [`build-package-output-mac-findings.md`](build-package-output-mac-findings.md). |
| 2026-09-16 | iOS simulator `arm64` (`hello-kivy`) | build/package output, local | macOS 26.6.2, Xcode 26.6 | **The highest-risk change in the set (iOS `build`/`run` now target `DerivedData` and assert the `.app` exists) works exactly as designed.** With `DerivedData` removed first, `build -p ios --simulator` produced and asserted `hello-kivy-ios/build/DerivedData/Build/Products/Debug-iphonesimulator/hello-kivy.app`; `--json` artifacts are `project` then `app`; `run --no-build` found and launched the same `.app`; `status --json` agrees (`"built": true` at that exact path). No `KF-ARTIFACT-MISSING` anywhere in this run. All four iOS failure-classification cases (§3d table: tool failed, tool missing, lock drift, `--release`/`package` artifact lists) matched spec exactly, using `--export-method development` for the release/package half — no distribution cert on this Mac. Full detail: [`build-package-output-mac-findings.md`](build-package-output-mac-findings.md). |
| 2026-09-16 | macOS `arm64` (`dice-roller`) | product fix | macOS 26.6.2 | **One real defect** found by the Step 4 "missing tool" repro (`PATH` stripped to the venv only): a missing `sips`/`iconutil` was reported as `KF-ERROR`/exit `1` instead of `KF-TOOLCHAIN-MISSING`/exit `3` — no traceback, but the wrong classification. Cause: `platforms/macos/icns.py` predates the four `build`/`package`-output commits and pre-checks `shutil.which()` instead of catching the real spawn's `OSError` through `spawn_failure()`, the pattern `machotools.py`/`notarize.py`/`launcher.py` already use. Fixed the same way; re-ran the repro: `KF-TOOLCHAIN-MISSING`, exit `3`, `context: {"tool": "sips"}`. Linux/Windows icon generation has no equivalent gap — both use Pillow in-process, no external tool to spawn. 2 new/updated tests in `tests/platforms/macos/test_icns.py`; full suite (92.70%) + `ruff check`/`format` clean. |
| 2026-09-16 | Linux `x86_64` (`dice-roller`) | `build`/`package` output contract (local) | **WSL2** (Ubuntu 26.04, Python 3.14.4) | Verified the output contract on the one path no CI job builds — a real `appimagetool` 1.9.1. **No defects.** Success: `build` puts only `Built build/linux/<Name>.AppDir` on stdout with staging on stderr; `package --json` emits 278 bytes of stdout that strict-parse as one document, `ok: true`, exactly one `{"path": "dist/linux/dice-roller-0.1.0-x86_64.AppImage", "kind": "appimage"}` (relative, posix, exists), `diagnostics: []`, advice off stdout, `Packaging … with appimagetool 1.9.1 …` on stderr; `-f folder --json` gives one `folder` artifact whose path contains a space and stays relative/posix. The packaged `.AppImage` launches and reaches "Start application main loop". **Failure (unwritable `dist/`, as uid 1000):** exit `5`, `KF-BUILD-TOOL-FAILED`, `context == {"tool": "appimagetool", "task": "package"}`, one-line 72-char message, and `artifacts == []` **even though Step 1's `.AppImage` was still sitting in `dist/`** — proposal §4.1b checked against the real case rather than assumed. Both of `appimagetool`'s streams reached stderr (its stdout *and* its `Permission denied`), which is precisely what the old `stderr or stdout` handling dropped, and none of it is embedded in the diagnostic. **Unusable toolchain:** exit `3`, `KF-TOOLCHAIN-UNUSABLE`, `context.errno == "EACCES"`, reached only after a full re-download, staging and byte-compile succeeded — the staged CPython lives outside `XDG_CACHE_HOME`, as predicted. Used the pre-existing `noexec` `tmpfs` at `/run/lock` instead of a `sudo` mount, which keeps the real uid rather than mapping to root. Full detail: [`build-package-output-linux-findings.md`](build-package-output-linux-findings.md). |
| 2026-09-17 | Windows `amd64` (`dice-roller`) | T2 + stdlib byte-compile measurement | Windows 11, Python 3.13.14 (bundled) | **Roadmap item 9 landed and measured on the host that had never measured it.** `package -p windows` on a real bundle: the staged stdlib ships 633 `.py` **and** 633 `.pyc` (sources deliberately kept — tracebacks, `inspect`, `linecache`), while the payload stays `.pyc`-only (0 `.py`, 1185 `.pyc`), so the strip setting still applies to exactly what it applied to before. A/B on that same bundle, bundled interpreter, `PYTHONDONTWRITEBYTECODE=1`, min of 5: `import kivy` **66 ms compiled vs 276 ms after deleting the stdlib `__pycache__`** (wall 100 ms vs 317 ms) — 4.2×, ~210 ms per launch, matching the 5× the macOS/Linux measurements predicted. §5.10 closed. **Not re-measured on macOS or Linux**: same code path, but neither host has run it. |
| 2026-09-17 | Linux `x86_64` (`dice-roller`) | stdlib byte-compile measurement | **WSL2** (Ubuntu 26.04, Python 3.14.4 host / 3.13.14 bundled) | Follow-up in [`build-package-output-linux-prompt.md`](build-package-output-linux-prompt.md). `package -p linux -f folder`: stdlib ships **633 `.py` and 633 `.pyc`** in 47 `__pycache__` dirs — the 2026-09-15 incidental subset (41 files / 6 dirs) is gone, replaced by the complete compile; payload still 0 `.py`. A/B on that AppDir, bundled interpreter, `PYTHONDONTWRITEBYTECODE=1`, min of 5: `import kivy` **34 ms compiled vs 214 ms after deleting the stdlib `__pycache__`** (wall 40 ms vs 260 ms) — 6.3×, ~180 ms per launch. Writes stayed suppressed (0 `.pyc` after the source-only runs). The `.AppImage` carries the same 633/633 pair (extracted and counted; tree discarded). AppDir restored afterwards. macOS remains the unmeasured desktop host as of this row — see the next one. |
| 2026-09-17 | macOS `arm64` (`dice-roller`) | stdlib byte-compile measurement + signing interaction | macOS 26.6.2, Xcode 26.6 | **The macOS-specific half of item 9: does compiling the stdlib before `codesign` survive a real launch?** Yes. `package -p macos` (real Developer ID, notarized, stapled): stdlib ships 633 `.py` **and** 633 `.pyc`, app payload stays `.pyc`-only (0 `.py`). `codesign --verify --deep --strict` passes before launch, and — the question no other host can ask — still passes **after** running `Contents/MacOS/*` directly to "Start application main loop", with the `.pyc` count unchanged (969 → 969): `PYTHONDONTWRITEBYTECODE` in the launcher (2026-09-14 fix) holds under a pre-compiled stdlib exactly as it did under a source-only one. Timing, bundled interpreter, min of 5: `import kivy` **13.4 ms compiled vs 85.8 ms source-only** — **6.4×, ~72 ms per launch**, same shape as Windows (4.2×, ~210 ms) and Linux (6.3×, ~180 ms), larger ratio only because this Mac's absolute numbers are smaller (Apple M5 Pro). Deleting the stdlib `__pycache__` to get the source-only number did, as expected, break the signature (`a sealed resource is missing or invalid`); the example was re-packaged (re-signed, re-notarized, re-stapled) afterward, `git status` clean. All three desktop hosts now measured. §5.10 fully closed. |
| 2026-09-17 | Linux `aarch64` (`dice-roller`) | T2 + T3 (cross, local) | **WSL2** (Ubuntu 26.04, Python 3.14.4 host / 3.13.14 on PATH) | **First aarch64 AppImage in this repo.** `archs = ["aarch64"]` (restored after; lock not committed). `lock` wrote PBS `cpython-3.13.14+20260805-aarch64-unknown-linux-gnu-install_only.tar.gz` and `Kivy-2.3.1` `manylinux_2_17_aarch64.manylinux2014_aarch64` (not a bare `linux_aarch64`). `package --json`: `dist/linux/dice-roller-0.1.0-aarch64.AppImage`, `ok: true`, `diagnostics: []`. Byte-compile used host `python3.13`, not the staged aarch64 interpreter — **this is the first Linux `find_interpreter()` path.** Doctor WARN `Native vs cross`. T3 `--linux-appimage --linux-arch aarch64 --linux-stripped` 3 passed after the driver learned to `unsquashfs` a foreign type2 ELF and to take `.pyc` magic from host CPython 3.13. Planting `libc.so.6` as `usr/lib/_host_leak.so` produced exactly one problem (`x86_64 … but aarch64 requires aarch64`); reverted. Payload 0 `.py` / 336 `.pyc`. Full detail: [`aarch64-pi-target-findings.md`](aarch64-pi-target-findings.md). |
| 2026-09-17 | Linux `aarch64` (Pi 5) | T4 + T5 | Raspberry Pi 5 Model B Rev 1.1, Debian 13.7 (trixie), labwc/Wayland, glibc 2.41 | **First on-device aarch64 AppImage run.** `scp` of the WSL2-built `dice-roller-0.1.0-aarch64.AppImage`; FUSE self-mount (`/tmp/.mount_dice-*`). SSH has no display, so `WAYLAND_DISPLAY=wayland-0` from the seat0 `rpd-labwc` session. SDL2 window, OpenGL 3.1 Mesa 26.2.2, vendor Broadcom, renderer **V3D 7.1.10.2** (not llvmpipe). Kivy 2.3.1 / bundled 3.13.14 reached "Start application main loop"; `timeout 25` then SIGTERM (exit 124). Human on the HDMI: Dice Roller rendered correctly. `Unable to connect to X server` printed and was ignored — Wayland is what served the window. Pi 4 not tested. Full detail: [`aarch64-pi-target-findings.md`](aarch64-pi-target-findings.md). |
| 2026-09-17 | Windows `amd64` (`dice-roller`) | T3 infra | Windows 11, Python 3.13.14 (bundled), CPython 3.13.1 (host, byte-compile) | Windows half of §5.1, mirroring the Android/macOS/Linux pattern: `windows_onedir_problems` (`tests/artifact_checks.py`), a new pure-Python `petools.py` PE-header reader (`read_pe_machine`, no `ctypes`/OS API), hermetic tests, `--windows-onedir`/`--windows-arch`/`--windows-stripped` in `conftest.py`, and `tests/platforms/windows/test_onedir_artifact.py`. Fresh `kivyforge package -p windows` on `dice-roller` (default `byte_compile = "release"`, host has a final CPython 3.13): staged with `.pyc only`. **First real-bundle run found a genuine false positive**, not a build defect: the PE-arch sweep flagged `python/Lib/site-packages/pip/_vendor/distlib/{t32,t64-arm,w32,w64-arm}.exe` as foreign-arch binaries leaked into the amd64 bundle — these are pip's own vendored distlib launcher *templates*, one per (bitness, console/windowed) combination, shipped by every pip install regardless of host or target arch (confirmed against this dev box's own `.venv` pip, not just the artifact). Excluded by filename from the sweep, with a hermetic regression test pinning it. Second run: `tests/platforms/windows/test_onedir_artifact.py -q --windows-onedir <dist> --windows-stripped` — 1 passed. Full suite (`python -m pytest -q`) exit 0, coverage 93.01%; `ruff check`/`format` clean; `pyright` 0 errors. §5.1's Windows box is now checked off. |
| 2026-09-21 | iOS simulator + device `arm64` (`hello-kivy`) | `entry_point`/`__main__` fix validation | macOS 26.6.2, Xcode 26.6 | **First real run of the entry_point/`__main__` unification on iOS** (Android's twin ran the same day, on a Pixel 8a — see the `entry_point` roadmap item). Unmodified `App().run()` style builds/renders "Hello Kivy" on the iOS 26.5 simulator, screenshot-confirmed. `src/main.py` temporarily edited to add the `if __name__ == "__main__":` guard — the exact idiom that silently never started on iOS before this fix — rebuilt, and rendered the identical screen, also screenshot-confirmed. Repeated `--device` on a connected iPhone 13 Pro Max with the guard still in place: install + launch both exit 0, no error; no CLI path exists to screenshot a physical device, so that leg is launch-confirmed only, not render-confirmed. Reverted (`git status` clean). **Incidental fix:** `lock -p ios --check` reported `KF-LOCK-DRIFT` with an empty diff on this exact lock, reproducibly, even though `lock --update` proved it byte-identical modulo `generated_at` — `semantic_equal()` compared raw resolver-order tuples against the writer-sorted file, a bug mirrored into the shared macOS/Linux/Windows lock builder and fixed in both. Full detail: [`ios-entry-point-main-validation-findings.md`](ios-entry-point-main-validation-findings.md). |
| 2026-09-21 | iOS device `arm64` (`hello-kivy` + real `firebase-ios-sdk`) | user-report repro + product fix | macOS 26.6.2, Xcode 26.6 | **The prior commit's fix for "Signing for ... requires a development team" (same day, commit `56ca1730`) does not actually fix it.** Reproduced the original user report with the real Firebase SPM package (`FirebaseCore` product, 11.15.0, via a temporary `swift_packages` entry — not committed) and a real device build: identical failure, with `DEVELOPMENT_TEAM` confirmed already present in the generated `.pbxproj` at both target and project level. A second hypothesis (`PBXProject.attributes.TargetAttributes`, what Xcode's Signing & Capabilities *tab* actually writes, as opposed to the Build Settings tab) also reproduced the failure identically when patched in directly. The actual fix: pass `DEVELOPMENT_TEAM=<team>` as an `xcodebuild` **command-line** override, the same way `CODE_SIGN_IDENTITY` already was — a Swift Package's own targets build as a synthesized sub-project that reads neither the consuming project's baked `buildSettings` nor its `TargetAttributes`, only command-line overrides. Verified against the real package: builds and `codesign -dv` confirms proper signing; a regression check (rebuild with the command-line override removed, everything else unchanged) reproduced the original error again, 5 instances. `build_command()`/`archive_command()` and both `cli.py` call sites (`_xcodebuild_step7`, `ios_run`) updated; `ios_run` had the identical gap independently. Full detail: [`ios-firebase-spm-signing-findings.md`](ios-firebase-spm-signing-findings.md). |
| 2026-09-21 | iOS (hermetic; no device/toolchain) | product fix — `embed` default | — | **A second, independent Firebase footgun from the same user report** (`FirebaseAuth` this time): `embed`'s old default (`true` for every entry) fails at `xcodebuild build` — `The file "FirebaseAuth" couldn't be opened because there is no such file` — for any remote package whose product is `automatic`/`static`, which is most third-party SPM packages, not just Firebase's. Considered and rejected: parsing `xcodebuild`'s error text to detect this reactively — its exact wording is explicitly not a contract (confirmed the `-product`-suffix variant is cosmetic), so a text match is one Xcode release away from silently stopping matching. Fixed proactively instead: `embed` now defaults to `false` for a `url` package and stays `true` for a `path` package (author-controlled, e.g. `keychain-spm`'s `KeychainBridge` shim, which still needs the old default). `kivyforge/config/loader.py`'s one-line change (`entry.get("embed", not url)`), doc rewrite (`06-swift-packages.md`, including flipping its own Sentry example to set `embed = true` explicitly now that it no longer gets it for free), and two new regression tests in `tests/config/test_loader.py`. Not re-verified against the real device/Firebase (that leg was already closed in the row above); this is a hermetic-only follow-up. Full detail: the "Resolution" section appended to [`ios-firebase-spm-signing-findings.md`](ios-firebase-spm-signing-findings.md). |

| 2026-09-21 | Android (merged manifest) | T3 infra + CI | Windows 11, Python 3.13.1 | §5.1's manifest-content box. `android_manifest_problems` + `test_merged_manifest.py`, wired into `android_gradle` after `kivyforge package`. **Validated against real AGP output before wiring, not after:** three merged manifests left on disk by earlier local builds (`hello-android`, `hello-sdl3`, `android-safe-area`, the last exercising the three-orientation `fullSensor` mapping) all pass clean; 15 hand mutations of one of them — dropped permission, wrong min/target SDK, wrong versionCode/versionName, wrong package, flipped orientation, lost theme, renamed launcher activity, dropped LAUNCHER category, removed `<uses-sdk>`, unresolved placeholder, malformed XML, wrong root element — are all caught; and pointing the driver at a deliberately mismatched project reports both real differences at once. **Found a real bug on the first run:** passthrough manifest attribute values were escaped twice (`_attr_str`'s `escape` plus `_attrs`' `quoteattr`), so `android:description = "Rock & Roll"` shipped as the literal `Rock &amp; Roll`. Fixed and pinned. 39 hermetic tests; full suite + `ruff` + `pyright` clean, coverage 93.20%. |
| 2026-09-21 | Android `x86_64` (CI) | T3 (signature) | ubuntu (wired), Windows 11 (validated) | §5.1's Android signature half. `test_apk_signature.py`, run in `android_gradle` against the keystore-signed release APK with `KIVYFORGE_REQUIRE_TOOLCHAIN=1` so a missing `apksigner` fails rather than skips; `build-tools;35.0.0` added to the job's `sdkmanager` line so the tool's presence is declared rather than inherited from the runner image. Validated locally against a real APK using the SDK's own `apksigner.bat` (build-tools 35.0.0): real output matches the parser's fixtures exactly (`v1: false`, `v2: true`), and the driver passes end to end. |
| 2026-09-21 | Windows `amd64` | T3 (signature) | Windows 11, SDK 10.0.22621.0 signtool | §5.1's Windows signature half, both legs. `test_authenticode.py`; `windows_signing` now verifies its own signed launcher through it rather than a bare `signtool verify /pa`. **Validated against real signtool in all three states:** a currently-valid Microsoft-signed binary passes; kivyforge's own unsigned built launcher (`dice-roller` dist copy) is rejected with all three faults reported at once; and a python.org `python.exe` whose signing certificate had since been **revoked** is rejected — that last one is why the parser reads verification *counts*, since it prints a full certificate chain, a timestamp line and the word "verified". Two real signtool quirks were only found this way and are now pinned by faithful fixtures: signtool blank-line-separates every output line, so an error's tab-indented explanation sits two lines below it and a naive continuation scan silently dropped the only human-readable half of the message; and the counts go to stdout while the errors go to stderr. The built-app leg (`--windows-onedir`) is wired but has no CI job to run it (§5.3). |

| 2026-09-22 | Android `x86_64` + Windows `amd64` (CI) | T3 | ubuntu + windows (GitHub runners) | **First CI execution of the three checks added 2026-09-21**, which the rows above could only describe as "wired". Run [35740389054](https://github.com/ElliotGarbus/kivyforge/actions/runs/35740389054), all 11 active jobs green. What makes this row worth more than "green": each step's pytest emitted `.`, not `s` — merged-manifest content `1 passed`, `apksigner verify` `1 passed` (with `KIVYFORGE_REQUIRE_TOOLCHAIN=1` visible in the step's env, so a missing tool would have failed rather than skipped), and `windows_signing`'s Authenticode step `.s` — the signed-PE leg passed, the built-app leg skipped for want of a bundle, exactly its designed shape. A green job containing a skipped assertion is the failure this tier exists to remove, so the result character is the evidence, not the job conclusion. **One correction to the row above:** the runner image already ships `build-tools 37.0.0` and `_find_apksigner` takes the newest version directory, so the explicit `build-tools;35.0.0` install guarantees a floor but is *not* what supplied the apksigner that ran. Consistent with the helper's documented "newest wins, matching AGP", but the job comment overstated it and has been corrected. |

| 2026-09-22 | Linux `x86_64` (`linux-gate` fixture) | T2 + T3 (local, then CI) | **WSL2** (Ubuntu, Python 3.14.4 host / 3.13.14 staged) | **The desktop lock question decided and the first desktop build job built** (§5.3). New fixture `tests/fixtures/apps/linux-gate` with a **committed** `pylock.linux.toml` — 48 lines, 2 packages (Kivy 2.3.1 `manylinux_2_17_x86_64` cp313 + `filetype`) and the PBS 3.13.14 runtime; small enough to read in a diff, which is the point of committing it. Proven locally before the job was written: `doctor -p linux` exit 0, `lock -p linux --check` "up to date" (exit 0 — the first exercise of that verb against a real committed desktop lock, and of the 2026-09-21 `semantic_equal` fix), `package -p linux` 22 s producing `linux-gate-1.0.0-x86_64.AppImage` with the payload `.pyc`-only, and the T3 driver 3 passed against that AppImage. **Negative control:** re-run with `--linux-arch aarch64` reports `usr/lib/Kivy.libs/libSDL2-*.so`, `kivy/_clock.cpython-313-x86_64-linux-gnu.so` and others — which is why the fixture depends on Kivy rather than being dependency-free; a bare bundle gives the ELF sweep and the `usr/lib` strip scope nothing to walk. Headless `doctor` also simulated (`env -u DISPLAY -u WAYLAND_DISPLAY`): WARN, exit 0, so the CI step gates without a waiver. |
| 2026-09-22 | Linux `x86_64` | **§5.6 case-insensitive staging collision, observed for real** | **WSL2**, building onto `/mnt/c` (NTFS, case-insensitive) | Incidental, and the first producer §5.6 has ever had. The first `package -p linux` attempt was run with the project on the Windows mount and died in staging: `shutil.Error` on `python/share/terminfo/h/hp70092A` vs `hp70092`, `terminfo/X` vs `x`, `terminfo/A` vs `a` — the embedded runtime's terminfo database contains entries differing only by case, which a case-insensitive filesystem cannot hold. **Not a kivyforge defect**, and not a CI concern (`ubuntu-latest` is ext4), but it means *no Linux build can be produced onto `/mnt/c` from WSL2*, which is worth knowing before anyone tries it again. Re-running the identical command with the project copied to ext4 succeeded in 22 s. §5.6's entry can now name a reproduction instead of a suspicion. |

| 2026-09-22 | macOS `arm64` (`macos-gate` fixture) | T2 + T3 (local, then CI) | macOS 26.6.2, Xcode 26.6 | **macOS follows `linux-gate`'s pattern the same day, and the "needs a signing story" caveat §5.3 originally carried turns out to be wrong** — `macos_package()` already falls back to an ad-hoc signature (no certificate) with no signing configured, exactly the CI-safe floor a gate needs. New fixture `tests/fixtures/apps/macos-gate` with a **committed** `pylock.macos.toml` (2 packages: Kivy 2.3.1 `macosx_10_15_universal2` cp313 + `filetype`, PBS 3.13.14 arm64 runtime). Proven locally before the CI job was written: `doctor -p macos` clean (every signing check `SKIP`, ad-hoc floor), `lock -p macos --check` "up to date", `package -p macos` ~4 s producing an ad-hoc-signed `.app` (57 Mach-O binaries signed), and the T3 driver 2 passed — **the first real-bundle run of the `--macos-project` `Info.plist`-vs-config comparison** (added 2026-09-21, hermetic-only until now; §5.1). **Negative controls**, both against the same bundle: `--macos-arch x86_64` reported all 11 shipped Mach-O binaries as foreign by name (`Contents/MacOS/macos-gate`, staged `python3.13`, `libpython3.13.dylib`, …); editing the *built* `Info.plist`'s `CFBundleIdentifier` (fixture's own config untouched) was caught by both checks independently — the plist comparison named the mismatch, and rewriting a sealed resource post-signing separately broke `codesign --verify`, confirming the seal covers `Info.plist`. Rebuilt clean afterward; `git status` clean. `macos_app` CI job added mirroring `linux_appimage`'s shape exactly (`.github/workflows/kivyforge.yml`). |

| 2026-09-22 | Windows `amd64` (`windows-gate` fixture) | T2 + T3 (local, then CI) | Windows 11, Python 3.13.1 host / 3.13.14 staged | **The desktop set completed** (§5.3): `windows_onedir` joins `linux_appimage` and `macos_app`, so all three desktop targets now build in CI. New fixture with a committed `pylock.windows.toml` — 94 lines, 7 packages (Kivy 2.3.1 `win_amd64` cp313, `kivy_deps.{sdl2,glew,angle}`, `pywin32`/`pypiwin32`, `filetype`) plus the PBS 3.13.14 runtime. Proven locally before the job was written: `doctor -p windows` exit 0 with the signtool and certificate checks **SKIP**ping on an unsigned fixture (so the step gates without a waiver, same as Linux and macOS), `lock -p windows --check` "up to date", `package -p windows` 45 s to a `.pyc`-only onedir bundle, and `test_onedir_artifact.py` 1 passed against it. **Negative control:** `--windows-arch arm64` names the SDL2 DLLs, the tcl DLLs, `vcruntime140.dll`, the `.pyd` extension modules and the launcher itself — which is why this fixture depends on Kivy rather than being dependency-free. **Partially validated, stated plainly:** the signature step's *reject* half was verified locally (the driver correctly fails the built, unsigned launcher with "No signature found"), but the sign-then-pass half was **not** run here — it needs a self-signed cert imported into the machine trust store, which is not a change to make on a dev box. It reuses `windows_signing`'s already-green recipe verbatim; first real execution is its first CI run. |

| 2026-09-22 | All desktop gates (CI) | **CI failure + fix** | ubuntu / macos / windows runners | **`macos_app` went red on `main` with `HTTP Error 403: rate limit`**, at `kivyforge lock -p macos --check`. Not a code defect and not caused by the commit that triggered it: the same job passed on the same SHA in that commit's `pull_request` run. **Root cause:** `lock --check` re-resolves live, and the PBS lookup in `lock/wheelruntime/pbs_github.py` called `api.github.com` unauthenticated — 60 requests/hour per IP, against a `fetch()` that can spend 16 of them — while `push` and `pull_request` were running the same commit concurrently and sharing runner egress. **A tension worth naming:** `lock --check` was added to these gates *because* it is meaningful only against a committed lock, but it also makes a gate depend on a live third-party API every push, which cuts against the determinism the committed lock exists to provide. **Fixed three ways:** the fetcher now honors `GH_TOKEN`/`GITHUB_TOKEN` (5000/hour) and names that remedy when it sees a 403/429; the three desktop jobs pass the token Actions already provides; and `on: push` is limited to `main`, so a branch with an open PR no longer runs the whole matrix twice. Each of the first and third alone would have prevented it. **Process note, because it is the reusable lesson:** the failure was merged past because only the `pull_request` run was checked — two runs fire per branch push with an open PR, and a divergence between them is a signal, not noise. Re-running the failed job on `main` afterwards passed with zero failing jobs, confirming the transience. |
| 2026-09-23 | iOS simulator `arm64` (`hello-kivy`) | T2 + T4 (local, then CI) | macOS 26.6.2, Xcode 26.6 | **Closes roadmap item 5's iOS bullet**, one day after all three desktop targets — the wheels it was "waiting on" had actually been published since 2026-07-27 (§3.2), so the delay was oversight, not a live blocker. Reused `examples/mobile/hello-kivy` directly rather than a new fixture, matching `android_gradle`'s choice: it is one of the three on-device-gate examples whose `pylock.ios.toml` is already committed. Proven locally before the CI job was written: `doctor -p ios` clean (2 expected `WARN`s only — byte-compile and privacy-manifest, neither iOS-simulator-specific), `lock -p ios --check` "up to date" with no `GITHUB_TOKEN` needed (iOS resolves against `kivy-mobile-wheels`' static index and python.org, not `api.github.com`, so the 2026-09-22 rate-limit fix does not apply here), `build -p ios --simulator` produced the `.app` in ~20 s, and `run -p ios --simulator --no-build` installed and launched it — with a screenshot confirming "Hello Kivy" rendered. **One real finding along the way:** `kivyforge run` invokes `simctl launch --console-pty`, which streams the app's console forever for a GUI app that keeps running — there is no "confirm launched, then exit" verb, so running it in a CI step's foreground would hang until the job timeout. Confirmed by reproducing the hang directly, then confirming the fix: background the command, wait 15 s, and treat "still running" as launch success / "exited early" as `simctl launch` having raised — verified both branches for real (the success path against a built app, the early-exit path by deleting the `.app` first and confirming the CLI's own `built app not found` message surfaces). No T3 harness exists for iOS (§5.1), so this job proves T2 + T4 only, exactly what the roadmap bullet asked for; a screenshot is uploaded every run for a human to glance at, since nothing automated reads its pixels. `git status` clean before committing (build artifacts and screenshot were never in the working tree, both gitignored/discarded). |

| 2026-09-23 | CI hygiene (all jobs) | §5.7 + §5.8 + §5.9 closed | Windows 11 (authoring); evidence from the 2026-09-23 `main` run | Three small gaps closed together, each of the same shape — a check that could not fail. **§5.9:** `android_gradle`'s doctor step no longer waives itself. The waiver was protecting against a FAIL that cannot occur *there*: `_check_16k_alignment` runs only `if project_dir.is_dir()` (the **generated** project), which the `build` step below has not created yet, so the check is not registered rather than passing. Verified against the real run — 0 FAIL, 2 WARN (no device, no AVD) — and `ok = worst_status(results) is not Status.FAIL`, so WARNs never gated. **§5.8:** `macos_integration` pinned to 3.13, the last platform proof running `3.x`; the seven remaining floaters are cross-cutting jobs or ones exercising a C toolchain, and §3.1 now says so explicitly so nobody finishes the job by pinning them too. **§5.7:** `requires_device` removed rather than wired. No test ever carried it, so `KIVYFORGE_DEVICE_TESTS=1` enabled nothing while implying device coverage existed behind a flag; wiring it would have meant writing ADB tests from a host with no device, which is how tests that assert nothing get written. Device runs stay manual and logged here. |

| 2026-09-23 | Android `x86_64` (emulator) | **T4** (local, then CI) | Windows 11 host / API-35 `google_apis` x86_64 AVD | **The last tier reaches CI** (§5.4). Rehearsed locally first on the AVD this box already had: `kivyforge run --smoke --release -p android --serial emulator-5554` on `hello-android` → `Contract smoke test PASSED`, `connectedReleaseAndroidTest` 1 test, Gradle 1m25s, 2m10s end to end. **First logged smoke run since 2026-07-27, and the first on the release variant** — so it exercises byte-compilation, stripping and R8, not just the load model. `git status` clean afterwards: the committed `pylock.android.toml` was verified, not rewritten. Then wired as `android_emulator` (`ubuntu-latest` + a `/dev/kvm` udev rule + `reactivecircus/android-emulator-runner`), pinned to CPython 3.14 for the same load-bearing reason `android_gradle` is — without a final 3.14 the release build degrades to shipping source and the job would quietly stop testing stripping. **Corrected a stale design claim in passing:** `android/06`'s gate table said `run --smoke` is "not hosted CI" because an emulator implies a self-hosted runner; hosted `ubuntu-latest` exposes `/dev/kvm`, so that is no longer true. **First CI run failed, and the emulator was not why.** The AVD booted fine; `kivyforge` then reported `missing [tool.kivy] table` — against *kivyforge's own* `pyproject.toml`, because `reactivecircus/android-emulator-runner` executes **each line of `script:` as its own `sh -c`**. The `cd "$APP_DIR"` line therefore applied to a shell that immediately exited, and the next line started back at the repo root. Fixed by making it one `&&`-chained command. Worth knowing before adding a second step to that script, and worth noting about the local rehearsal: running the command by hand proved the *command*, and could not have caught the *wiring*. |

| 2026-09-23 | iOS simulator `arm64` (`hello-kivy`) | T3 infra + CI | macOS 26.6.2, Xcode 26.6 | **Closes §5.1's last open box — the one platform with no T3 tier at all now has one, wired into CI the same day it was built.** Following [`ios-t3-checks-prompt.md`](ios-t3-checks-prompt.md): Step 0 built `hello-kivy` for the simulator and dumped the real bundle (`doctor -p ios` still warns "no final CPython 3.15 found", confirming the scope constraint is unchanged since 2026-09-14). The bundle is flat — no `Contents/` — and every one of `hello-kivy`'s 120+ compiled extension modules lives in its own `Frameworks/<name>.framework/`, hoisted there by python-apple-support's `install_python`, with a plain-text `.fwork` stub left behind at the original `app/`/`pip-deps/`/`python/lib` location. `ios_app_problems` + `ios_expected_plist` added to `tests/artifact_checks.py` (required entries, a whole-bundle Mach-O arch sweep reusing `machotools.read_macho_cpu_type`, `Info.plist` vs. config mirroring `macos_expected_plist`'s shape); 20 hermetic tests in `tests/test_artifact_checks.py`; `--ios-app`/`--ios-arch`/`--ios-project` in `conftest.py` (no `--ios-stripped` — see below); `tests/platforms/ios/test_app_artifact.py` mirroring the macOS driver, including a `codesign --verify` test that reuses `machotools.codesign_verify` directly rather than duplicating it. **Validated against the real Step 0 bundle, including negatives:** clean pass with `--ios-arch arm64 --ios-project`; claiming `--ios-arch x86_64` named all 114 real Mach-O binaries (every framework plus the root executable) as foreign-arch; editing the *built* `Info.plist`'s `CFBundleShortVersionString` (fixture's own config untouched) was caught by the comparison **and** independently broke `codesign --verify` — the signature seals `Info.plist` exactly as it does on macOS. Restored byte-for-byte afterward; both tests green again. Wired into `ios_simulator` as a new step between the T2 build and the T4 launch; confirmed locally with the exact CI command (`ls -d`-globbed path, `KIVYFORGE_REQUIRE_TOOLCHAIN=1`) that pytest prints `..`, not `.s`. **Scope decision, explicit:** no `stripped`/`.pyc`-magic check — `ios_app_problems` takes no `stripped` parameter at all, rather than one no driver would ever set `True`, because the scope constraint from Step 0 is unchanged. `pylock.ios.toml` untouched; `hello-kivy-ios/` was never in the working tree (gitignored). Full suite 3012 passed / 55 skipped, 92.88% coverage; `ruff check`/`format` and `pyright` clean. Full detail: [`ios-t3-checks-findings.md`](ios-t3-checks-findings.md). |

| 2026-09-23 | Android `x86_64` from a **Windows** host | T2 + T3 (local, then CI) | Windows 11, CPython 3.14.7 (via the `py` launcher) | **§5.2 closed — the item-1 code path finally has automated coverage.** Every Android build in CI had run on ubuntu, where `find_interpreter` reaches a versioned `python3.14` directly; item 1's bug lived in what that search does on Windows. Measured here first: `find_interpreter("3.14.6")` → `('py', '-3.14')`, the PEP 397 launcher, resolving to **CPython 3.14.7 final, 64-bit** — and `py --list` confirms the launcher knows 3.14 through 3.7, so the pre-release-rejection branch has real candidates to reject. `package -p android --abi x86_64` against a throwaway keystore produced a stripped, byte-compiled release APK, and all three T3 drivers (`test_apk_artifact` `--android-stripped`, `test_merged_manifest`, `test_apk_signature`) passed against it — run under a scratch 3.14.7 venv, because the magic assertion compares against the *runner's* MAGIC_NUMBER and this repo's dev venv is 3.13. Then wired as `android_windows_host`. **Coverage stated precisely:** CI proves the Windows branch end to end, but `setup-python` puts 3.14 on PATH while the launcher usually does not know a hostedtoolcache install, so CI likely resolves via `('python',)` rather than the launcher — the job logs which candidate won so this is answerable per run instead of assumed, and the `py`-launcher leg is *this* row. **Not a bug, noted because it reads like one:** `find_interpreter` returns `()` for "use the interpreter already running" and `None` for no match; a `()` is success. **First CI run failed before reaching any of that**, on a Windows-shell detail rather than anything Android: `sdkmanager` is `sdkmanager.bat`, and Git Bash does not apply `PATHEXT`, so a bare `sdkmanager` is "command not found" even with the SDK action having put it on PATH. That one step moved to `pwsh`; the rest of the job stays on bash because the tools it calls (`keytool`, `kivyforge`, `pytest`) are `.exe`, which bash does resolve — audited rather than assumed, and the same two were driven from bash by hand during the local leg above. **Second run green, and its resolver log line corrected this row's own premise:** CI printed `resolver picked: ()` — the "use the interpreter already running" fast path, taken *before* the Windows candidate list is built, because `setup-python` makes the runner the same 3.14 the project ships. So CI covers Windows Gradle/NDK, Windows path handling, byte-compilation on a Windows host and the full T3 pass, but **not** the `py`-launcher search — that is this row's local leg and the unit tests, nothing standing. The step was added to make that answerable rather than assumed, and on its first run it contradicted both guesses about what CI would pick, which is the argument for logging rather than reasoning about it. `package` 1m20s, T3 3 passed. |

| 2026-09-23 | Android **`arm64_v8a`** | T2 + T3 (local, then CI) | Windows 11, CPython 3.14.7 | **The ABI every real phone runs had no direct CI coverage** — all three Android jobs passed `--abi x86_64`, and §3.2 had carried arm64_v8a as "inherited, not direct" since the matrix was written. `android_gradle` is now a two-leg matrix. Proven locally first: `package -p android --abi arm64_v8a` produced a stripped release APK and `test_apk_artifact.py --android-abi arm64-v8a --android-stripped` passed against it. **Two negative controls, both fired:** claiming `x86_64` on that APK reports the missing `lib/x86_64/libmain.so` *and* the stray `arm64-v8a` objects; and passing the wheel-tag spelling to `--android-abi` gives `unknown ABI 'arm64_v8a'; expected one of ['arm64-v8a', 'x86_64']`. **That second one is the trap worth recording:** kivyforge's `--abi` takes `arm64_v8a` while the T3 driver's `--android-abi` takes `arm64-v8a`, and the two are *identical for x86_64* — which is exactly why one `$ABI` variable sufficed for as long as this job built only that ABI. The matrix now carries both spellings. It fails loudly rather than silently, so this was never a false-green risk, only a job that would not have run. |
| 2026-09-23 | Windows `amd64` (`windows-gate`) | T2 + T3 + T4 (local) | Windows 11, CPython 3.13.1 venv; fixture pins 3.13.14 | **§5.5 closed on desktop — `run --release` reaches `strip_source`.** `kivyforge run -p windows --release`: "[stage] byte-compiling the Python payload … (.pyc only)" and "byte-compiling the embedded stdlib", then `Launching Windows Gate ...`; `Windows Gate.exe` still running 8 s later, then closed by `taskkill` (so the logged "exited with status 1" is the kill, not the app). `test_onedir_artifact.py --windows-stripped` against `build/windows/Windows Gate` → `.` (asserted, not skipped). **Negative control:** plain `run -p windows` printed no byte-compile step, and the same assertion failed: `app/main.py` plus 1,194 `.py` under `python/Lib/site-packages`. |
| 2026-09-23 | Linux `x86_64` (`linux-gate`) | T2 + T3 + T4 (local) | **WSL2** (Ubuntu, Python 3.14.4, WSLg), built on ext4, not `/mnt/c` (§5.6) | Same check as the Windows row. `run -p linux --release` byte-compiled "(.pyc only)" plus the stdlib; `AppRun`'s `python3 -P -m main` still running 10 s after `Launching`. `test_appimage_artifact.py --linux-appdir … --linux-stripped` → 2 passed, 1 skipped (the AppImage-container test, which has no AppImage to inspect for a bare AppDir). **Negative control:** plain `run` failed it: 336 `.py` files, no `.pyc` at all. Kivy's non-fatal `libmtdev.so.1` traceback, printed at startup in both runs, showed the difference too: release frames had no source text. The first attempt failed on setup, not the change: the WSL venv predated the `rich` dependency and had no `pytest-cov` for the repo's `addopts`. |

### Known-unverified, stated plainly

- ~~The **macOS `Info.plist`-vs-config** comparison (§5.1): wired 2026-09-21
  and hermetically tested, but never run against a real `.app`. Needs the
  Mac~~ — **done 2026-09-22** via the `macos-gate` fixture, both locally and
  in the new `macos_app` CI job (§5.1, §5.3, §7).
- ~~The **Windows built-app signature** leg (§5.1): validated against real
  signtool, but only on binaries signed by someone else. Verifying a launcher
  that *kivyforge* signed inside a real bundle needs a code-signing cert this
  dev box does not have~~ — **done 2026-09-22** in CI: `windows_onedir` signs
  the launcher *inside* the `windows-gate` bundle it just built (a throwaway
  self-signed cert, since this dev box still has none) and verifies it,
  closing the full round trip §5.1 asked for. Not locally reproducible on this
  Mac either way.
- iOS `strip_source`: never run, on simulator or device — and, as of 2026-09-14,
  known to be currently *unrunnable* on any in-repo example, since all of them
  pin the pre-release `3.15.0b4` and `package -p ios` requires a final CPython
  to byte-compile.
- iOS on a **device**: verified 2026-09-14 (§7) — `build`, `run`, and
  `package --export-method development` all succeeded on a real iPhone, and
  found+fixed a real `--team-id` propagation bug along the way. Repeated
  2026-09-21 for the `entry_point`/`__main__` fix (build + run, exit 0, no
  error) — but that run had no CLI path to screenshot the device, so it is
  launch-confirmed, not render-confirmed the way the simulator legs of both
  dates are. Still local and by hand both times, not standing coverage.
- ~~Nothing iOS in CI: both the simulator and device coverage above are local
  and unrepeated in CI, so none of it proves a continuously-checked
  tree.~~ — **partly done 2026-09-23**: the simulator leg (`build`/`run
  --simulator` on `hello-kivy`) is now `ios_simulator`, every push (§3.1,
  §3.2, §5.3). The device leg stays local-only, permanently — no CI runner
  has a physical iPhone attached, the same reason Android's `arm64_v8a` row
  is `manual` rather than CI.
- ~~No T3 for iOS: nothing inspects a built `.app`/`.ipa` — not its
  `Info.plist`, not its Mach-O arch, not whether `strip_source` did
  anything.~~ — **done 2026-09-23** (§5.1, §7): `ios_app_problems` covers
  required entries, a whole-bundle Mach-O arch sweep, and `Info.plist` vs.
  config, wired into `ios_simulator` the same day. **Still true, and by
  design:** whether `strip_source` did anything — iOS `strip_source` remains
  unrunnable on every in-repo example (the bullet above), so there is nothing
  honest to check it against.
- ~~Any `kivyforge build` for Linux, macOS, **or Windows**: never run in
  CI~~ — **done 2026-09-22, all three**: `linux_appimage`, `macos_app`, and
  `windows_onedir` each run `kivyforge build`/`package` for their platform on
  every push (§5.3, §7). What's left for macOS specifically is the
  Developer-ID/notarization path, which stays local-only by design (§3.2) —
  the CI job uses the ad-hoc floor, deliberately, since a CI runner has no
  certificate.
- `kivyforge build -p macos` with **real Developer-ID signing +
  notarization**: still local-only, run **by hand repeatedly since
  2026-07-07** (five notarized `dice-roller` builds, §7) — `codesign`,
  `lipo`, and (as of 2026-09-14) file-level Mach-O/`.pyc`/`Info.plist`
  assertions via `--macos-app` have all executed against a real signed,
  notarized artifact. The ad-hoc-signed path runs in CI (`macos_app`, above);
  the notarized one needs a real Apple Developer credential CI does not have.
- Notarization: **verified** — five `notarytool Accepted` submissions since
  2026-07-07 (§7). Previously listed as unverified in §6; that was stale.
- ~~`appimagetool`: run once, locally, 2026-09-13 (§7). Never in CI.~~ — **in CI since 2026-09-22**: `linux_appimage` packages the `linux-gate` fixture with a real `appimagetool` on every push (§5.3, §7).
- Linux `strip_source`: proven end to end **once natively**, 2026-09-13, and
  only after the `AppRun` fix in the same session. The *cross* byte-compile
  path (`find_interpreter()` → host `python3.13`) first ran on 2026-09-17
  producing the aarch64 `dice-roller` AppImage — see §7 that date.
- Whether a stripped macOS `.app` can actually **launch**: **resolved,
  2026-09-14 — it could not, and now it can.** The doubt raised from the Linux
  host (`macos-launcher-strip-source-prompt.md`) was correct: `macos/launcher.py`
  built the same `"%s/%s.py"` exec path Linux's did, and every notarized
  `dice-roller.app` built before 2026-09-14 (five prior `Accepted` submissions,
  §7) was, in fact, unlaunchable — a signed, notarized, T3-passing artifact was
  not evidence it starts. Confirmed by running it directly (exit 2, `can't open
  file '.../app/main.py'`), fixed the same way as Linux (`execv` `-m` instead of
  a path), and proved by an actual launch: rendered, visually confirmed, with
  `codesign --verify` still passing afterward. That last part needed its own
  fix — see the next bullet.
- Running a macOS app writes into its own signed bundle: **resolved,
  2026-09-14.** The embedded stdlib ships as `.py` (stripping is scoped to
  `app`/`site-packages` only, by design), so the *first* successful launch
  above immediately wrote `__pycache__` into it and invalidated the bundle's
  code signature (`codesign --verify` afterward: "a sealed resource is missing
  or invalid"). This had never been seen before because nothing had launched a
  macOS app in this repo until the same session. Fixed by setting
  `PYTHONDONTWRITEBYTECODE=1` in the launcher; a repeat launch afterward left
  `codesign --verify` passing. Windows is unaffected (Authenticode signs the
  executable, not a bundle-wide resource seal).
- ~~The same question **on Linux**: unverified, and the Linux `AppRun` does
  not set `PYTHONDONTWRITEBYTECODE`.~~ — **both halves are stale, corrected
  2026-09-23.** The question was answered on 2026-09-15 by
  [`linux-launcher-bytecode-findings.md`](linux-launcher-bytecode-findings.md):
  an unstripped folder AppDir gained 209 files on launch, 100 of them in the
  payload, and the `.AppImage` was immune because its squashfs mounts
  read-only. **`AppRun` has set `PYTHONDONTWRITEBYTECODE=1` since that same
  session** (`linux/launcher.py`), after which a re-measure showed zero new
  files in either shape. The startup cost the prompt also asked for was
  measured on all three desktop hosts and closed §5.10. Leaving this bullet
  saying the opposite of what the launcher does is exactly the failure the
  rules at the top of this file name.
- ~~Android `arm64_v8a` in CI: never built (`android_gradle` is `x86_64`
  only), so its T2/T3 is inherited from `x86_64` plus the stray-ABI check, not
  direct.~~ — **built in CI since 2026-09-23**: `android_gradle` is a two-leg
  matrix and runs the full T3 pass on both ABIs. T4 for `arm64_v8a` stays
  manual, since the emulator is x86_64.
- ~~Android T3 from a Windows host: once, by hand, 2026-09-13 (§5.2).~~ — **in CI since 2026-09-23** via `android_windows_host`. **But not the part item 1 broke:** that job's own log line shows the resolver taking the "interpreter already running" fast path, so the Windows `py`-launcher *search* is still covered only by the 2026-09-23 local measurement and by `tests/bundle/test_pycompile.py`. See §5.2.
- ~~Android T4 in CI: never; the emulator runs above are local and unrepeated.~~ — **in CI since 2026-09-23**: `android_emulator` runs `run --smoke --release` on an API-35 x86_64 AVD every push (§5.4). `arm64_v8a` T4 stays manual — the emulator is x86_64, so that ABI needs a device.
- Every `examples/verify-*` script except `verify-ios-device.sh`: no logged run.
  `verify-ios-device.sh` got its first logged run 2026-09-14 (§7).
- ~~`requires_device` / `KIVYFORGE_DEVICE_TESTS`: enable nothing today.~~ — **both removed 2026-09-23** (§5.7), rather than left as an opt-in that enabled nothing.
