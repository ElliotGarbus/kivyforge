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
`examples/run-examples.sh`. **`examples/verify-ios-device.sh` got its first
logged run 2026-09-14** (§7) — the other four still have none. They remain the
cheapest untapped coverage in the repo — `verify-windows-examples.ps1` in
particular covers the Windows column that no CI job reaches (§5.3).

### 3.2 Per-target coverage

**Last proven** distinguishes standing coverage from one-off evidence: *every
push* means a CI job re-proves the row continuously, and a date means the only
evidence is a single logged run in §7 that nothing re-runs.

| Target | T0/T1 | T2 toolchain | T3 artifact | T4 launch | T5 hardware | Last proven |
|---|---|---|---|---|---|---|
| Windows `amd64` | `windows_tests` | **partial** — `windows_launcher` (MSVC), `windows_signing` (self-signed `signtool`) | **partial** — vendored launcher byte-compare only | **partial** — launcher against a stub `python.exe`; no Kivy app | see §6 | every push |
| macOS `arm64` | `unit_tests` (minus mac-only), `macos_integration` | **two `clang` tests** (CI); **local** — real Developer-ID sign + notarize + staple + `strip_source`, `examples/desktop/dice-roller` | **local** — `tests/platforms/macos/test_app_artifact.py` via `--macos-app`, run against the notarized `dice-roller.app` | **local** — a stripped, re-notarized `dice-roller.app` launched and rendered for the first time, after fixing the launcher (§7, 2026-09-14) | see §6 | every push (T0/T1/T2-CI); 2026-09-14 (T2-local, T3, T4) |
| Linux `x86_64` | `unit_tests` | **local only** — `appimagetool`, one run | **local only** — assertions exist and are hermetically tested every push; pointed at a real artifact once | **local only** — stripped AppImage reaches first frame (llvmpipe) | see §6 | every push (T0/T1); 2026-09-13 (T2/T3/T4) |
| Linux `aarch64` | — | — | — | — | — | never (item 4) |
| Android `arm64_v8a` | `unit_tests` | **inherited, not direct** | **inherited, not direct** | none | **manual** | 2026-09-13 |
| Android `x86_64` | `unit_tests` | `android_gradle` (AGP, NDK, CMake, `javac`) | `android_gradle` — debug **and** stripped release | **local only** — `run --smoke` on an API-31 AVD, not CI | n/a | every push (T2/T3); 2026-07-27 (T4) |
| iOS device `arm64` | `unit_tests` | **local** — `build -p ios --device`, `package -p ios --export-method development`, real iPhone14,3 | **none** | **local** — installed, launched, `hello-kivy` rendered on device | **manual** — first physical run, 2026-09-14 | 2026-09-14 |
| iOS simulator `arm64` | `unit_tests` | **local** — `xcodebuild` via `build -p ios --simulator`, 6 examples | **none** | **local** — `simctl` launch, all 6 render | n/a | 2026-09-14 (regression re-check; no drift since 2026-07-27) |

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

**macOS's CI job is still two tests** — `macos_integration` runs `pytest -q`
and nothing else; its entire marginal value over `unit_tests` is the two
`TestLauncherCompile` tests that `clang` makes runnable, which is why that
class now fails rather than skips when `clang` is absent. **No CI job runs
`kivyforge build -p macos`.** But outside CI the maintainer has been building,
Developer-ID-signing, and notarizing `dice-roller` by hand since July 2026 (five
`notarytool` submissions, all `Accepted` — §7), and 2026-09-14 turned that
existing habit into logged evidence plus a T3 driver
(`tests/platforms/macos/test_app_artifact.py`, §5.1) that ran `codesign
--verify` and file-level Mach-O/`.pyc`/`Info.plist` assertions against that real
notarized `.app` — both passed. So `codesign`, `lipo`, and `hdiutil` are no
longer mock-only; they are local-only, which is a real but different gap (see
below).

**Linux is still the emptiest CI column, but it is no longer unproven.** No CI
job runs `kivyforge build -p linux`, so the AppDir → AppImage step remains
untested *in CI*. It has now run once locally (§7, 2026-09-13), and that single
run is the argument for §5.3: it found a defect that made every default
`kivyforge package -p linux` produce an AppImage that could not start. The T3
assertions it exposed that with are hermetic and do run every push; what does
not re-run is anything pointing them at a real artifact.

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
`kivy-mobile-wheels` index.

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

What remains genuinely unproven for iOS, restated after that run: **no CI**
(the device and simulator runs above are local and unrepeated — a regression
surfaces only when someone next runs it by hand), **no T3** (nothing inspects
the built `.app` or `.ipa` the way `--macos-app` now inspects a macOS bundle),
and **`strip_source`**, which is not merely unrun but currently *unrunnable*:
`package -p ios` degrades to shipping source because there is no final CPython
3.15 yet, and **every iOS example in this repo pins `3.15.0b4`** — so this is a
structural gap general to the whole platform, not a gap in any one example or
test.

**macOS as a *target* is no longer the empty half.** No CI job runs
`kivyforge build -p macos`, but the maintainer has been building,
signing, and notarizing `dice-roller` by hand since July 2026, and 2026-09-14
turned that into logged evidence (§7) plus an automated T3 check (§5.1) that
passed against the real artifact. What's left is making that CI-shaped: a
`macos_integration`-adjacent job that actually runs `kivyforge build -p macos`
and points `--macos-app` at the result, rather than relying on a human
remembering to notarize.

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
- [x] **macOS check *functions* and driver — done 2026-09-14.**
      `tests/artifact_checks.py::macos_app_problems` (required entries, Mach-O
      arch via a new pure-Python `machotools.read_macho_cpu_type`, payload
      stripping scoped to `app/`+`lib/` only per the settled stdlib-exclusion
      design, `.pyc` magic, `Info.plist`), hermetic-tested in
      `tests/test_artifact_checks.py`, and wired to a real bundle via
      `tests/platforms/macos/test_app_artifact.py --macos-app`. Ran against the
      real notarized `dice-roller.app` — passed. Not yet in CI (§3.2).
- [x] **Linux check functions — done 2026-09-13, and they caught a shipped bug.**
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
- [ ] **Windows check functions.** Same split, not blocked on §5.3, and the
      option can sit ready behind `--windows-onedir` exactly as `--android-apk`,
      `--macos-app`, and `--linux-appimage` did. Windows is the one desktop
      target immune to the launcher defect above: its bootstrap uses
      `runpy.run_module`, which resolves through the import system.
- [ ] **Merged `AndroidManifest.xml` and `Info.plist` contain what config asked
      for.** `android_gradle` already exports the merged manifest to
      `app/build/kivyforge/AndroidManifest-merged-release.xml` and currently
      archives it **only on failure** — so the artifact needed to assert this is
      produced on every run and thrown away on success. (The macOS check above
      does assert `Info.plist` structure/optional-exact-match; the Android
      manifest side of this item is still open.)
- [x] **macOS code signature verifies** — `codesign --verify`, via
      `machotools.codesign_verify`, exercised in
      `test_app_artifact.py::test_the_app_is_codesigned` against the real
      notarized `dice-roller.app`.
- [ ] **Signatures verify** — `apksigner verify` (Android), and `signtool verify
      /pa` on a *built app* rather than on the vendored launcher (Windows).

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

**This is not Android-only, and on 2026-09-13 it stopped being hypothetical.**
`linux_run()` calls `linux_build(...)`, which hardcodes `release=False`, so
`package` is the only Linux verb that reaches `strip_source` — and `package`
emits a distributable nobody launches while iterating. That gap is exactly where
the `AppRun` defect in §7 lived: shipped, reproducible in one command, and
invisible to every path a developer actually uses. The cost of this hole is now
measured, not argued.

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

### 5.10 Byte-compile the embedded stdlib at build time — **closed 2026-09-17**

Both pieces landed together, as this section required. The staged stdlib is
byte-compiled during staging on all three desktop targets (sources kept —
`site-packages` is left to the payload compile under its own strip setting), and
the compile subprocess now runs with `PYTHONDONTWRITEBYTECODE=1` so its own
imports stop seeding the artifact with an arbitrary subset of caches.

**Re-measured on Windows** (§7, 2026-09-17): `import kivy` in a real packaged
`dice-roller` bundle costs **66 ms compiled against 276 ms source-only** — 4.2×,
~210 ms off every launch. **Re-measured on Linux** the same day (§7): **34 ms
compiled against 214 ms source-only** — 6.3×, ~180 ms off every launch, on the
host that had the most to gain because an AppImage can never cache at runtime.
The AppImage itself carries the same 633/633 stdlib pair. **macOS is not
re-measured**: the code path is shared, but this file does not count a shared
code path as coverage.

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
| 2026-09-17 | Linux `x86_64` (`dice-roller`) | stdlib byte-compile measurement | **WSL2** (Ubuntu 26.04, Python 3.14.4 host / 3.13.14 bundled) | Follow-up in [`build-package-output-linux-prompt.md`](build-package-output-linux-prompt.md). `package -p linux -f folder`: stdlib ships **633 `.py` and 633 `.pyc`** in 47 `__pycache__` dirs — the 2026-09-15 incidental subset (41 files / 6 dirs) is gone, replaced by the complete compile; payload still 0 `.py`. A/B on that AppDir, bundled interpreter, `PYTHONDONTWRITEBYTECODE=1`, min of 5: `import kivy` **34 ms compiled vs 214 ms after deleting the stdlib `__pycache__`** (wall 40 ms vs 260 ms) — 6.3×, ~180 ms per launch. Writes stayed suppressed (0 `.pyc` after the source-only runs). The `.AppImage` carries the same 633/633 pair (extracted and counted; tree discarded). AppDir restored afterwards. macOS remains the unmeasured desktop host. |

### Known-unverified, stated plainly

- iOS `strip_source`: never run, on simulator or device — and, as of 2026-09-14,
  known to be currently *unrunnable* on any in-repo example, since all of them
  pin the pre-release `3.15.0b4` and `package -p ios` requires a final CPython
  to byte-compile.
- iOS on a **device**: verified once, by hand, 2026-09-14 (§7) — `build`, `run`,
  and `package --export-method development` all succeeded on a real iPhone.
  Not re-proven anywhere, so this is a point-in-time result, not standing
  coverage, and it found+fixed a real `--team-id` propagation bug along the way.
- Nothing iOS in CI: both the simulator and device coverage above are local and
  unrepeated, so together they prove 2026-09-14's tree rather than a
  continuously-checked one.
- No T3 for iOS: nothing inspects a built `.app`/`.ipa` — not its `Info.plist`,
  not its Mach-O arch, not whether `strip_source` did anything. (macOS gained a
  T3 driver 2026-09-14 — see below — but nothing analogous exists for iOS yet.)
- Any `kivyforge build` for Linux, macOS, **or Windows**: never run in CI.
  Linux and macOS have each been built **locally** (§7, 2026-09-13 and
  2026-09-14); nothing re-runs either.
- `kivyforge build -p macos`: never run in CI, but run **locally by hand
  repeatedly since 2026-07-07** (five notarized `dice-roller` builds, §7) —
  `codesign`, `lipo`, and (as of 2026-09-14) file-level Mach-O/`.pyc`/`Info.plist`
  assertions via `--macos-app` have all executed against a real signed,
  notarized artifact. What's still missing is CI: nothing re-proves this on
  every push.
- Notarization: **verified** — five `notarytool Accepted` submissions since
  2026-07-07 (§7). Previously listed as unverified in §6; that was stale.
- `appimagetool`: run once, locally, 2026-09-13 (§7). Never in CI.
- Linux `strip_source`: proven end to end **once, locally**, and only after
  the `AppRun` fix in the same session. The *native* byte-compile path is
  what ran; `find_interpreter()` has still never been exercised by a Linux
  build.
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
- The same question **on Linux**: unverified, and queued as
  [`linux-launcher-bytecode-prompt.md`](linux-launcher-bytecode-prompt.md). The
  Linux `AppRun` does not set `PYTHONDONTWRITEBYTECODE` (read out of
  `linux/launcher.py`), and the reasoning that Linux is therefore safe — an
  AppImage mounts read-only, so the write cannot persist — is a hypothesis
  nobody has tested. It also does not cover `package -f folder`, which leaves a
  *writable* AppDir that is simultaneously the tree the T3 driver inspects. Per
  this file's own first rule, that makes Linux uncovered here, not fine. The
  same prompt asks for the startup cost of shipping an uncompiled stdlib to be
  measured, since the macOS write is evidence that no usable `.pyc` ships and
  every launch on every platform re-parses the stdlib from source.
- Android `arm64_v8a` in CI: never built (`android_gradle` is `x86_64` only), so
  its T2/T3 is inherited from `x86_64` plus the stray-ABI check, not direct.
- Android T3 from a Windows host: once, by hand, 2026-09-13 (§5.2).
- Android T4 in CI: never; the emulator runs above are local and unrepeated.
- Every `examples/verify-*` script except `verify-ios-device.sh`: no logged run.
  `verify-ios-device.sh` got its first logged run 2026-09-14 (§7).
- `requires_device` / `KIVYFORGE_DEVICE_TESTS`: enable nothing today.
