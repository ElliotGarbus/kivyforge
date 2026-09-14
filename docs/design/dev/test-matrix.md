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
| Android `arm64_v8a` | cross | cross | cross | none |
| Android `x86_64` | cross | cross | cross | none |
| iOS device `arm64` | ✗ | native-only | ✗ | `Darwin` only |
| iOS simulator `arm64` | ✗ | native-only | ✗ | `Darwin` only |

Seven target cells, not five platforms — Android and iOS each carry two, and
they are genuinely different builds.

**The arch sets are narrower than the gates.** `VALID_WINDOWS_ARCHS` is
`{amd64}`, `VALID_MACOS_ARCHS` is `{arm64}`, `VALID_LINUX_ARCHS` is `{x86_64}`.
So although the Windows host gate permits cross-arch builds by design, config
rejects `arm64` today: win-arm64 and Linux `aarch64` (the Raspberry Pi target,
roadmap item 4) are additive changes to those frozensets, and each adds a row
here when it lands.

**The consequence for planning: from the Windows dev box, Windows and Android
are reachable directly, and Linux is reachable through WSL2.** macOS and both
iOS cells need a Mac. Of the six open roadmap items, two are partly
host-blocked rather than effort-blocked — item 4 wants a Linux host and
eventually Pi hardware, and item 8's iOS half wants a Mac — and everything iOS
in §6 is Mac-blocked independently of which item it belongs to.

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

**Three env vars exist because a self-skipping test is indistinguishable from a
passing one:**

- `KIVYFORGE_REQUIRE_SYMLINKS=1` — `requires_symlinks` tests must run, not skip.
  Set on `windows_tests`.
- `KIVYFORGE_REQUIRE_TOOLCHAIN=1` — a missing toolchain becomes a failure
  instead of a skip (`skip_missing_toolchain()`). Set on the three jobs whose
  entire purpose is a toolchain they are known to have.
- `KIVYFORGE_DEVICE_TESTS=1` — the inverse: `requires_device` is opt-**in**,
  because no runner has a device and a marker that skips everywhere is one
  nobody notices has stopped running.

**`requires_device` currently marks nothing.** The marker and its env var are
wired in `conftest.py`, and no test in `tests/` uses either. T5 is a checklist
(§6) and a log (§7), not a selectable suite — so an unused opt-in marker is
itself a silent skip waiting to happen. See §5.7.

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
| `android_gradle` | ubuntu | **3.14** | Android T2 + T3 |
| `macos_integration` | macos | `3.x` | macOS T2 (two `clang` tests) |

**Only `android_gradle` pins an exact minor, and it is the only one that must.**
Its T3 magic-number check compares the APK's `.pyc` headers against the
*runner's* `importlib.util.MAGIC_NUMBER`, so the runner's Python is part of the
test definition; `test_apk_artifact.py` fails naming the runner if they diverge.
The `3.x` jobs float deliberately-ish, but see §5.8 — `macos_integration`
floating means the one macOS host we have is testing an unpinned interpreter.

Local scripts are producers too, and rule 1 means they count only when a run is
logged in §7: `examples/verify-windows-examples.ps1` (a real Windows
build/run/package loop), `examples/verify-desktop-examples.sh`,
`examples/verify-android.ps1`, `examples/verify-ios-device.sh`, and
`examples/run-examples.sh`. **None of them has a logged run.** They are the
cheapest untapped coverage in the repo — `verify-windows-examples.ps1` in
particular covers the Windows column that no CI job reaches (§5.3).

### 3.2 Per-target coverage

**Last proven** distinguishes standing coverage from one-off evidence: *every
push* means a CI job re-proves the row continuously, and a date means the only
evidence is a single logged run in §7 that nothing re-runs.

| Target | T0/T1 | T2 toolchain | T3 artifact | T4 launch | T5 hardware | Last proven |
|---|---|---|---|---|---|---|
| Windows `amd64` | `windows_tests` | **partial** — `windows_launcher` (MSVC), `windows_signing` (self-signed `signtool`) | **partial** — vendored launcher byte-compare only | **partial** — launcher against a stub `python.exe`; no Kivy app | see §6 | every push |
| macOS `arm64` | `unit_tests` (minus mac-only), `macos_integration` | **two `clang` tests** | none | none | see §6 | every push |
| Linux `x86_64` | `unit_tests` | **none** | **none** | **none** | see §6 | every push |
| Linux `aarch64` | — | — | — | — | — | never (item 4) |
| Android `arm64_v8a` | `unit_tests` | **inherited, not direct** | **inherited, not direct** | none | **manual** | 2026-09-13 |
| Android `x86_64` | `unit_tests` | `android_gradle` (AGP, NDK, CMake, `javac`) | `android_gradle` — debug **and** stripped release | **local only** — `run --smoke` on an API-31 AVD, not CI | n/a | every push (T2/T3); 2026-07-27 (T4) |
| iOS device `arm64` | `unit_tests` | **none** | **none** | **none** | **never** | never |
| iOS simulator `arm64` | `unit_tests` | **none** | **none** | **none** | n/a | never |

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
Kivy app. **No CI job runs `kivyforge build -p windows`.**

**macOS is two tests, and the table says so rather than "partial".**
`macos_integration` runs `pytest -q` and nothing else; its entire marginal value
over `unit_tests` is the two `TestLauncherCompile` tests that `clang` makes
runnable — which is why that class now fails rather than skips when `clang` is
absent. **No CI job runs `kivyforge build -p macos`**, so `codesign`, `lipo`,
and `hdiutil` are exercised only through mocks.

**Linux is the emptiest column.** Unit tests only: `appimagetool` has never run
in CI, so the AppDir → AppImage step is entirely untested outside mocks.

**Android is the strongest column, and the only one with real T3.**
`android_gradle` is the real thing — AGP, the pinned NDK, CMake, and `javac` all
consume generated files, and the release path runs `lintRelease` plus the
merged-manifest policy pass against a throwaway keystore. Both the debug APK and
the **stripped release APK** go through `tests/artifact_checks.py` (§5.1).

**Android `arm64_v8a` is marked *inherited* rather than covered**, which is a
downgrade from this file's first revision and the right one. `android_gradle`
builds `x86_64` only, so the shipping ABI is never built in CI. The stray-ABI
check partly compensates — it fails if anything other than the requested ABI
appears — but the arch assertions are precisely the ABI-specific ones, so
claiming `x86_64`'s T3 covers `arm64_v8a` is an argument, not a run. Rule 1 says
label it as such.

**iOS has no toolchain coverage at all.** `xcodebuild` and `simctl` command
construction are unit-tested; neither has run. Blocked on the iOS
`Python.xcframework` and wheels being published, not on effort.

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

---

## 4. Host-dependent behaviour

The same target builds through different code on different hosts, so "Android
passes" is not host-independent. Each of these has bitten:

- **Byte-compile takes a different path per host.** `select_compiler()` uses the
  staged interpreter when the build is native and searches the host via
  `find_interpreter()` otherwise. A Windows host building Windows `amd64` takes
  the first path; the same host building Android takes the second. Item 1 was
  precisely a bug in the second path — and since `android_gradle` runs on ubuntu,
  **CI's Android T3 does not take the path item 1 broke.** Tracked as §5.2, not
  left as an observation.
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

Two orderings are in play and they disagree, so both are stated. §5.1–5.5 are in
**CI-cost order**: cheapest standing coverage first. But the dev box is Windows,
so *what this week can prove* is a different list — §5.2 (Windows-host Android
T3), §5.3 (a Windows or WSL2 desktop build), and §5.6 are all reachable today,
while §5.4's AVD is cheap in CI and awkward locally. Pick by which constraint
is actually binding.

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
- [ ] **Linux and macOS check *functions*, which are not blocked on §5.3.**
      Worth separating: the Android work split cleanly into pure checks (unit-
      tested on synthetic zips, no build needed) and a thin pytest driver that
      needs a real artifact. Only the driver waits on a build job.
      `platforms/linux/elftools.py` (`elf_machine`, `describe`) and
      `macos/machotools.py` (`macho_arches`, `codesign_verify`) already parse
      what is needed, so the checks and their hermetic tests can land **now**
      and sit ready behind `--linux-appimage` / `--macos-app` /
      `--windows-onedir`, exactly as `--android-apk` did.
- [ ] **Merged `AndroidManifest.xml` and `Info.plist` contain what config asked
      for.** `android_gradle` already exports the merged manifest to
      `app/build/kivyforge/AndroidManifest-merged-release.xml` and currently
      archives it **only on failure** — so the artifact needed to assert this is
      produced on every run and thrown away on success.
- [ ] **Signatures verify** — `apksigner verify`, and `signtool verify /pa` on a
      *built app* rather than on the vendored launcher.

### 5.2 Android T3 from a Windows host — the item-1 code path

`android_gradle` runs on ubuntu, where a native-ish `find_interpreter()` search
finds the runner's own CPython. **Item 1's bug lived in what that search does on
Windows** (the `py` launcher, versioned executables, pre-release rejection), and
no automated run exercises it. The unit tests in `tests/bundle/test_pycompile.py`
cover the resolver's logic; nothing builds an APK on Windows and inspects it.

Cheapest form: a `windows-latest` job that builds `hello-android` for one ABI and
runs the existing T3 assertions — the checks already exist, so this is wiring
plus Gradle time. Middle form: run it locally and log it in §7. Doing neither
leaves the exact shape of item 1 uncovered while the file that exists because of
item 1 claims Android is the strong column.

### 5.3 A desktop build job — and the lock blocker is real for *all three*

**Corrected 2026-09-13.** The first revision claimed the four
`examples/desktop/*` projects commit `pylock.windows.toml`. **They commit no
lock at all** — every one of them gitignores `pylock.*.toml`. The only committed
locks in the repo are `examples/mobile/hello-android/pylock.android.toml`,
`examples/mobile/hello-sdl3/pylock.android.toml`, and
`examples/mobile/hello-kivy/pylock.ios.toml`.

That changes the planning conclusion, not just a detail. A **Windows** build job
has the same blocker as Linux and macOS, so "Linux is cheapest" was resting on a
Windows lock that does not exist. Every desktop target needs the same decision
first:

- **commit one desktop lock** for a hello-scale example, copying exactly what
  `hello-android` does and what its `.gitignore` comment explains — the model is
  already in the repo and it works; or
- **adopt lock-at-CI-time explicitly** and accept resolver drift as a documented
  new failure mode, rather than arriving at it by default.

With that settled, `ubuntu-latest` is still the cheapest *CI* desktop job — no
signing identity, no Mac, and it fills the emptiest column. But from this dev
box a Windows build needs no other OS and
`examples/verify-windows-examples.ps1` already exists to drive it (§3.1), so the
cheapest *evidence* and the cheapest *job* are different targets.

### 5.4 T4 on an Android emulator, in CI

`android/06 run --smoke` is the instrumented contract test. It **has** run
green on an API-31 AVD as first-party local runs (§7, 2026-07-24 and
2026-07-27) — it has never run in CI, so nothing re-proves it and a regression
would surface whenever someone next ran it by hand. An `x86_64` AVD on a
KVM-enabled runner is the standard shape, and it is the tier that would have
caught the item-1 device hang without a human holding a phone.

### 5.5 `kivyforge run` cannot reach release stripping at all

This is a **product** hole, not only a test gap, which is why §5.4's predecessor
understated it. `android_run()` calls `android_build(..., debug=True)`
unconditionally and then looks for `_debug_output(...)`, so there is no flag that
makes `run` produce a release build. Since Android applies
`byte_compile`/`strip_source` in **release only**, the command developers use
most can never exercise stripping — and any test written against `run` today
would be testing the branch that was already fine. Fix the command first, then
cover it.

### 5.6 Host-dependent cases with no test at all

From §4, the ones with no producer of any kind: Windows path-length /
`longPathAware`, and case-insensitive staging collisions. Both are cheap policy
or generation tests rather than toolchain work — the model is
`tests/test_message_encoding.py`, which turned a host-specific footgun into a
static check over the source tree.

### 5.7 Wire `requires_device`, or remove it

Nothing uses it (§2). An opt-in marker with no tests behind it is a silent skip
with extra steps: `KIVYFORGE_DEVICE_TESTS=1` currently enables nothing, and
would keep reporting success after real device tests were added and broken.
Either give it the ADB-driven checks from the 2026-09-13 device session or drop
it until there is something to mark.

### 5.8 Pin the floating jobs

`macos_integration` runs `python-version: '3.x'` (§3.1). It is the only macOS
host in the system and it tests whichever minor the runner image happens to
ship — so a macOS-specific break on 3.13 versus 3.14 is invisible, and the
interpreter can change under us the way the MSVC toolset did (§7, three times).
`android_gradle` pins 3.14 because its T3 check forced the issue; the same
argument applies wherever a job is the sole proof of a platform.

### 5.9 Let doctor fail the Android job

`android_gradle`'s doctor step is `continue-on-error: true`, with a documented
reason: doctor reports the known-interim 4 KB-aligned Kivy wheel as a FAIL, so
gating on it would fail every build. The reason is legitimate and the blast
radius is not — **the job that exists to prove the Android toolchain currently
ignores every diagnostic doctor produces**, including ones unrelated to that
wheel. Narrow it to the known FAIL (allow-list that diagnostic, gate on the
rest) rather than waiving the whole step, and the waiver disappears on its own
when the wheel is fixed.

---

## 6. Manual checklist

These need a human, credentials, or hardware CI cannot have. Every one of them
should produce a dated line in §7 — an unlogged manual test did not happen.

- [ ] **iOS device install + launch** on real hardware (needs a Mac, a device, a
      provisioning profile).
- [ ] **iOS `strip_source`** — still unverified on any target. Item 1 proved the
      Android half; this is the other half, and it is host-blocked, not
      effort-blocked.
- [ ] **Notarization** — needs an Apple ID, app-specific password, and network.
- [ ] **Authenticode with a real certificate.** `windows_signing`'s self-signed
      loop proves the `SigntoolSigner` plumbing, not timestamping against a real
      CA chain or SmartScreen behaviour.
- [ ] **Raspberry Pi**: build on a Linux host, run on the Pi (item 4).
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
| 2026-07-25 | iOS (pip marker retargeting) | T0/T1 on a macOS host — **not** `xcodebuild` | macOS 26.5.2 / Xcode 26.6 | Suite green on macOS; pip's iOS environment markers confirmed. Relabelled 2026-09-13: this was logged as "T2", which collided with §3.2's `none` for iOS toolchain coverage. No iOS toolchain has ever run. See [`ios-validation-findings.md`](ios-validation-findings.md). |
| 2026-07-27 | Android `x86_64` | T4 (local) | — | Same `run --smoke` gate green for Kivy 3.0.0.dev0 / SDL3 via the `hello-sdl3` example, on the emulator and a Pixel 8a. Backfilled 2026-09-13. |
| 2026-09-13 | Android `arm64_v8a` (Pixel 8a) | T3 + T5 | Windows | `strip_source` release build verified end to end. Installed payload: 0 `.py`, 1036 `.pyc`, 0 `__pycache__`, `app/main.pyc` sourceless. Header magic 3627 (3.14 final). Kivy imports from `.pyc`, GL comes up (Mali-G715, ES 3.2), app renders. **This is also the only run of the Windows-host byte-compile path** (§5.2) — done by hand, not re-proven. |
| 2026-09-13 | Android `arm64_v8a` (Pixel 8a) | T5 | Windows | Device-state gotchas worth not rediscovering: a locked screen or a raised notification shade both hold focus and SDL never gets a surface, so the app looks hung at `Window: Provider: sdl3`. `wm dismiss-keyguard`, `cmd statusbar collapse`, `svc power stayon true`. |
| 2026-09-13 | Android `x86_64` (CI) | T3 | ubuntu | Artifact assertions added to `android_gradle` for the debug and stripped release APKs. Validated locally against the two real `arm64-v8a` APKs from item 1 first: the stripped one passes under CPython 3.14 and is correctly rejected under 3.13 (magic 3627 vs 3571), and claiming the wrong ABI is caught across all 120 shared objects. |
| 2026-09-13 | Windows `amd64` (CI) | T2 | windows | `windows_launcher` went red: byte mismatch at the same size with the pinned toolset (MSVC 14.51.36231 + SDK 10.0.26100.0) reported as *used*, i.e. a serviced compiler inside an unchanged version string — the drift `/EMITTOOLVERSIONINFO:NO` cannot cover. Last green was 2026-08-12; the hosted image rolled. Fixed by `revendor_launcher`, which changed the binary and `SHA256SUMS` but **not** `TOOLSET.txt`. Third occurrence. |
| 2026-09-13 | Linux `x86_64` | T0/T1 | **WSL2** (Ubuntu, Python 3.14.4) | Editable install plus `doctor -p linux` green on the `dice-roller` example, including the new byte-compile check reporting the native path ("the staged runtime compiles its own payload"). WSLg provides `wayland, x11`, so Linux T4 is locally reachable. No build or AppImage yet — this is environment readiness, not target coverage. |

### Known-unverified, stated plainly

- iOS `strip_source`: never run. No macOS host available.
- Any `kivyforge build` for Linux, macOS, **or Windows**: never run in CI.
- `appimagetool`: never run, anywhere.
- Android `arm64_v8a` in CI: never built (`android_gradle` is `x86_64` only), so
  its T2/T3 is inherited from `x86_64` plus the stray-ABI check, not direct.
- Android T3 from a Windows host: once, by hand, 2026-09-13 (§5.2).
- Android T4 in CI: never; the emulator runs above are local and unrepeated.
- Every `examples/verify-*` script: no logged run.
- `requires_device` / `KIVYFORGE_DEVICE_TESTS`: enable nothing today.
