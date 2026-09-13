# Test matrix and test plan

**Created 2026-09-13** (roadmap item 2). This is the answer to "which host ×
target × tier combinations have actually been exercised, and when." Nothing else
in the repo answers it, and roadmap item 1 is what that cost: `strip_source` had
shipped for two releases having never once run on a mobile target, and the way it
was finally noticed was a person opening a staged bundle and looking for
`main.py`.

Two rules for keeping this file honest:

1. **Coverage claims name the thing that produces them** — a CI job, a marker
   expression, or a dated line in the results log. "Should work" is not
   coverage, and neither is "there are unit tests for it".
2. **The gap list is the deliverable, not the coverage list.** A matrix that
   only records what passes is how item 1 stayed invisible.

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

**The consequence for planning: from the Windows dev box, only Windows and
Android are reachable.** Linux `x86_64` and the Pi need a Linux host (WSL2
counts); macOS and both iOS cells need a Mac. Three of the eight roadmap items
are host-blocked rather than effort-blocked, which is worth knowing when picking
what to work on in a given week.

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
both are "the hermetic suite", 2515 of 2530 tests.

### Selecting a tier

The markers in `tests/conftest.py` make this a `-m` expression rather than a
question about which CI job happens to invoke which code path:

```
pytest -m "not integration"    # T0+T1, the hermetic suite (2515 tests)
pytest -m integration          # T2+ (15 tests today)
pytest -m requires_device      # T5, and see KIVYFORGE_DEVICE_TESTS below
```

`requires_toolchain` and `requires_device` both imply `integration`, so a test
declares one thing and the selection follows.

**Two env vars exist because a self-skipping test is indistinguishable from a
passing one:**

- `KIVYFORGE_REQUIRE_SYMLINKS=1` — `requires_symlinks` tests must run, not skip.
  Set on `windows_tests`.
- `KIVYFORGE_REQUIRE_TOOLCHAIN=1` — a missing toolchain becomes a failure
  instead of a skip (`skip_missing_toolchain()`). Set on the three jobs whose
  entire purpose is a toolchain they are known to have.
- `KIVYFORGE_DEVICE_TESTS=1` — the inverse: `requires_device` is opt-**in**,
  because no runner has a device and a marker that skips everywhere is one
  nobody notices has stopped running.

---

## 3. Coverage today

CI jobs are in `.github/workflows/kivyforge.yml`. Cross-cutting jobs that belong
to no target cell: `lint` (ruff), `package` (build + `twine check`),
`sdl_glue_sync` (vendored SDL Java glue vs. kivy-mobile-wheels).

| Target | T0/T1 | T2 toolchain | T3 artifact | T4 launch | T5 hardware |
|---|---|---|---|---|---|
| Windows `amd64` | `unit_tests`, `windows_tests` | **partial** — `windows_launcher` (MSVC), `windows_signing` (signtool) | **partial** — launcher byte-compare, `signtool verify /pa` | **partial** — launcher only, stub `python.exe` | n/a |
| macOS `arm64` | `unit_tests`, `macos_integration` | **partial** — `clang` Mach-O launcher, 2 tests | none | none | n/a |
| Linux `x86_64` | `unit_tests` | **none** | **none** | **none** | n/a |
| Linux `aarch64` | — | — | — | — | — (item 4) |
| Android `arm64_v8a` | `unit_tests` | via `x86_64` below | **none** | none | **manual** — 2026-09-13 |
| Android `x86_64` | `unit_tests` | `android_gradle` (real AGP, NDK, CMake, javac) | **partial** — 3 APK entries | none (no emulator) | n/a |
| iOS device `arm64` | `unit_tests` | **none** | **none** | **none** | **manual** — never |
| iOS simulator `arm64` | `unit_tests` | **none** | **none** | **none** | n/a |

### Reading the partials

**Windows.** `windows_launcher` rebuilds `launcher-amd64.exe` from source and
byte-compares it against the vendored copy, which is a strong T3 — but of one
vendored binary, not of a built app. `test_launcher_exe.py` runs the real
launcher against a compiled stub `python.exe`, proving spawn/argv/exit-code/env
and process-tree teardown; that is a genuine T4 for the launcher and says
nothing about a Kivy app. **No CI job runs `kivyforge build -p windows`.**

**macOS.** `macos_integration` runs `pytest -q` and nothing else. Its entire
marginal value over `unit_tests` is the two `TestLauncherCompile` tests that
`clang` makes runnable — which is why that class now fails rather than skips
when `clang` is absent. **No CI job runs `kivyforge build -p macos`**, so
`codesign`, `lipo`, and `hdiutil` are exercised only through mocks.

**Linux is the emptiest column.** Unit tests only: `appimagetool` has never run
in CI, so the AppDir → AppImage step is entirely untested outside mocks.

**Android is the strongest, and still has no T3 worth the name.**
`android_gradle` is the real thing — AGP, the pinned NDK, CMake, and `javac` all
consume generated files, and the release path runs `lintRelease` plus the
merged-manifest policy pass against a throwaway keystore. Its artifact
assertions are three `unzip -l | grep` checks (`lib/<abi>/libmain.so`,
`lib/<abi>/libpython3.14.so`, `assets/_python_bundle/`). Presence, not
correctness. It also builds `x86_64` only, on the stated grounds that a second
ABI doubles the CMake work for no new signal — true for T2, false for T3, since
per-ABI arch assertions are exactly where a staging bug would show.

**iOS has no toolchain coverage at all.** `xcodebuild` and `simctl` command
construction are unit-tested; neither has run. This is blocked on the iOS
`Python.xcframework` and wheels being published, not on effort.

---

## 4. Host-dependent behaviour

The same target builds through different code on different hosts, so "Android
passes" is not host-independent. Each of these has bitten:

- **Byte-compile takes a different path per host.** `select_compiler()` uses the
  staged interpreter when the build is native and searches the host via
  `find_interpreter()` otherwise. A Windows host building Windows `amd64` takes
  the first path; the same host building Android takes the second. Item 1 was
  precisely a bug in the path CI does not take.
- **Windows needs Developer Mode for symlinks.** Covered by
  `requires_symlinks` + `KIVYFORGE_REQUIRE_SYMLINKS`.
- **Windows has a path-length ceiling** that deep staging trees can hit, and the
  launcher declares no `longPathAware` manifest.
- **Windows redirected streams are cp1252.** Guarded statically by
  `tests/test_message_encoding.py`, which parses `kivyforge/` for strings that
  can reach a stream and cannot encode — the model for the kind of cheap policy
  test this matrix should have more of.
- **macOS and Windows are case-insensitive; Linux is not.** Staging collisions
  appear on one host and not another.
- **Windows launcher reproducibility is pinned to an exact MSVC toolset**
  (`vendor/TOOLSET.txt`), so the runner image is part of the test definition —
  hence `revendor_launcher`/`revendor_verify` existing at all.

---

## 5. The gap list, in priority order

### 5.1 T3 artifact assertions — highest value available

Every one of these is a file read. No device, no human, no toolchain beyond the
build itself. **A T3 pass would have caught item 1 on the day it shipped**,
which is the whole argument.

- **`.pyc`-only when `strip_source` is on**, and `app/main.pyc` in the legacy
  sourceless layout. Assert against the *installed* payload where possible, not
  just the staged tree — item 1 verified both and they can differ.
- **`.pyc` magic number matches the shipped runtime.** The item-1 bug wrote
  loadable-looking bytecode from the wrong interpreter; a header check is four
  bytes.
- **ELF class and machine per target arch** — `platforms/android/elf.py`
  (`read_elf().machine`, `machine_name()`) and `platforms/linux/elftools.py`
  (`elf_machine`, `describe`) already parse this. Assert no host-arch binary
  leaked into a cross-build, which is the failure a single-ABI CI job cannot see.
- **Mach-O arch** via `machotools.macho_arches`, and `codesign_verify`.
- **Merged `AndroidManifest.xml` and `Info.plist` contain what config asked
  for.** `android_gradle` already exports the merged manifest and only archives
  it on failure.
- **Signatures verify** — `apksigner verify`, `signtool verify /pa` (the latter
  exists, on the vendored launcher rather than a built app).

### 5.2 A desktop build job for any of the three desktop targets

Linux is the cheapest (`ubuntu-latest`, no signing identity, no Mac) and the
emptiest column, so it is the obvious first one.

**Blocker, and it is a real one:** the four `examples/desktop/*` projects commit
only `pylock.windows.toml`. There is no `pylock.linux.toml` or
`pylock.macos.toml` anywhere in the repo, so a Linux or macOS build job must
either lock at CI time — network, a resolver run, and lock drift as a new
failure mode — or the examples must gain committed locks. `android_gradle`
sidesteps this entirely by consuming `hello-android`'s committed
`pylock.android.toml`, and that is the model to copy.

### 5.3 T4 on an Android emulator

`android/06 run --smoke` is the instrumented contract test and has never run in
CI. An `x86_64` AVD on a KVM-enabled runner is the standard shape. This is the
tier that would have caught the item-1 device hang without a human holding a
phone.

### 5.4 Release-mode coverage of `kivyforge run`

Android applies `byte_compile`/`strip_source` in **release only**, so the debug
path most users take never exercises stripping. Whatever covers this must
invoke a release run, or it is testing the branch that was already fine.

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
- [ ] **Store submission** — Play Console and App Store Connect.

---

## 7. Results log

Append-only. Date, target, what ran, what it proved.

| Date | Target | Tier | Result |
|---|---|---|---|
| 2026-07-25 | iOS (marker retargeting) | T2 | macOS 26.5.2 / Xcode 26.6. Suite green on macOS; pip's iOS environment markers confirmed. See [`ios-validation-findings.md`](ios-validation-findings.md). |
| 2026-09-13 | Android `arm64_v8a` (Pixel 8a) | T3 + T5 | `strip_source` release build verified end to end. Installed payload: 0 `.py`, 1036 `.pyc`, 0 `__pycache__`, `app/main.pyc` sourceless. Header magic 3627 (3.14 final). Kivy imports from `.pyc`, GL comes up (Mali-G715, ES 3.2), app renders. |
| 2026-09-13 | Android `arm64_v8a` (Pixel 8a) | T5 | Device-state gotchas worth not rediscovering: a locked screen or a raised notification shade both hold focus and SDL never gets a surface, so the app looks hung at `Window: Provider: sdl3`. `wm dismiss-keyguard`, `cmd statusbar collapse`, `svc power stayon true`. |

### Known-unverified, stated plainly

- iOS `strip_source`: never run. No macOS host available.
- Any `kivyforge build` for Linux or macOS: never run in CI.
- `appimagetool`: never run.
- Android `arm64_v8a` in CI: never built (`android_gradle` is `x86_64` only).
