# Android on a macOS host — findings

Handoff Task 4 ([`handoff-2026-09-25.md`](handoff-2026-09-25.md)): Android had
been built on ubuntu (`android_gradle`) and Windows (`android_windows_host`),
never on macOS, although `kivyforge capabilities` lists macOS as a host. Run on
`item7-small-fixes` @ `b608f06d` — `main` after PR #27, plus PR #28's three
fixes, none of which touch Android. The `doctor` fixes were then verified on
`android-macos-host`. Date: 2026-09-27.

**Summary.** kivyforge builds, packages and runs Android from a Mac. The debug
and release APKs pass the same three T3 checks `android_gradle` runs, the
on-device contract smoke test passes on a Pixel 8a, and the app reaches Kivy's
main loop. Nothing in the build itself is host-specific.

Getting there found **three `doctor` defects**, all in host detection and all
invisible on the CI hosts: the ubuntu and Windows runners install JDK 17
explicitly and set `ANDROID_HOME`. A Mac set up the obvious way — Android
Studio, nothing else — gets a green `doctor` and a failed build. All three are
fixed in the same branch as this document.

## Environment

| Item | Value |
|---|---|
| macOS | 26.6.2 (Build 25G83), Apple Silicon (`arm64`) |
| Android Studio | 2026.1, bundled JDK (JBR) **25.0.3** |
| JDK used for the build | Eclipse Temurin **17.0.20.1+1**, in `~/Library/Java/JavaVirtualMachines` (downloaded from Adoptium, SHA-256 verified) |
| Android SDK | `~/Library/Android/sdk` (Android Studio's default): platforms `android-35` and `android-37.0`, build-tools 36.0.0, NDK 27.3.13750724, cmdline-tools `latest` (23.0), platform-tools 37.0.1 |
| CMake | 3.22.1 — **not preinstalled**; AGP installed it during the first build |
| Gradle / AGP | 8.11.1 (downloaded by the wrapper) / 8.10.0 |
| kivyforge | 3.0.0.dev0, editable `.venv`, CPython 3.14.7 |
| Example | `examples/mobile/hello-android`, `--abi arm64_v8a`; runtime python.org 3.14.6 |
| Device | Pixel 8a, Android 17, `arm64-v8a`, USB debugging, serial `56051JEKB16396` |

## Defects

### 1. `doctor` passes macOS's `/usr/bin/java` stub with no JDK installed

Before any toolchain was installed:

```text
[PASS] JDK: /usr/bin/java
[FAIL] Android SDK: ANDROID_HOME/ANDROID_SDK_ROOT unset and no SDK at the conventional location
```

`/usr/bin/java` exists on every Mac. Without a JDK it prints "Unable to locate
a Java Runtime" and exits 1. The check only asked whether a `java` file existed
(`probe.which("java")`, or `$JAVA_HOME/bin/java` existing), never ran it.

### 2. `doctor` passes a JDK too new for the pinned Gradle

With Android Studio's bundled JDK as `JAVA_HOME`, `doctor` passed everything
but the emulator check, including:

```text
[PASS] JDK: JAVA_HOME=/Applications/Android Studio.app/Contents/jbr/Contents/Home
```

and `build -p android --debug` then failed in Gradle:

```text
FAILURE: Build failed with an exception.

* What went wrong:
BUG! exception in phase 'semantic analysis' in source unit '_BuildScript_' Unsupported class file major version 69
> Unsupported class file major version 69
...
Error: Gradle failed (exit 1) running: assembleDebug
  See the Gradle output above; `kivyforge doctor -p android` checks the JDK/SDK/NDK prerequisites.
```

Class file version 69 is Java 25. Gradle 8.11 runs on Java 23 at most. The
check had no version test at all, not even the documented minimum of 17, and
the build's own error sends the user back to the `doctor` that passed. The docs
said "JDK 17 or later" on four pages, which is how the JDK 25 got chosen.

This one matters most on macOS. Android Studio is the usual way to get the SDK
there, and it ships a JDK newer than the pinned Gradle accepts.

### 3. With `ANDROID_HOME` unset, the SDK is not found where Android Studio puts it on macOS

`RealAndroidProbe.sdk_root()` fell back to `~/Android/Sdk` and `~/android-sdk`,
the Linux locations. Android Studio on macOS installs to
`~/Library/Android/sdk`. Reproduced after the SDK was installed:

```text
$ env -u ANDROID_HOME -u ANDROID_SDK_ROOT kivyforge doctor -p android --offline
[FAIL] Android SDK: ANDROID_HOME/ANDROID_SDK_ROOT unset and no SDK at the conventional location
[SKIP] NDK: no SDK root to look in
```

`sdk_root()` is also what the build writes into `local.properties` as
`sdk.dir`, and what `run` uses to find `adb`, so the defect was not
doctor-only.

### Fixes (this branch)

- `_check_jdk` resolves `java` as `gradlew` does (`$JAVA_HOME/bin/java`,
  else `java` on `PATH`), runs `java -version` with `stdin=DEVNULL`, and FAILs
  when it will not run or its major version is outside
  `toolchain.MIN_JDK`..`toolchain.MAX_JDK` (17..23). `MAX_JDK` sits next to
  `GRADLE_VERSION` because it moves with it. An unreadable banner WARNs.
- `sdk_root()` tries `~/Library/Android/sdk` first on macOS.
- Of the four pages that said "17 or later", only the supported-versions
  table states the range now; the other three link to it. None names the
  JDK version Android Studio bundles, which changes with Android Studio's
  releases, not ours; they say it may be too new and that `doctor` checks.
  `tests/platforms/android/test_toolchain_docs.py` pins the table to
  `toolchain.py`, fails if another guide restates the range, and pins the
  (`GRADLE_VERSION`, `MAX_JDK`) pair so a Gradle bump forces a look at the
  ceiling.

Re-verified on this Mac after the fix:

```text
== JBR 25
[FAIL] JDK: JAVA_HOME=/Applications/Android Studio.app/Contents/jbr/Contents/Home is JDK 25; Gradle 8.11.1 needs a JDK 17 to 23
       hint: install a JDK 17 to 23 (Gradle 8.11.1 runs on no other) and point JAVA_HOME at it.
== JDK 17, ANDROID_HOME unset
[PASS] JDK: JDK 17 (JAVA_HOME=/Users/elliotgarbus/Library/Java/JavaVirtualMachines/jdk-17.0.20.1+1/Contents/Home)
[PASS] Android SDK: /Users/elliotgarbus/Library/Android/sdk
[PASS] Build-tools / platform: build-tools 36.0.0
[PASS] NDK: 27.3.13750724
```

A `build -p android --debug` with `ANDROID_HOME` unset then wrote
`sdk.dir=/Users/elliotgarbus/Library/Android/sdk` and succeeded.

## Steps

All commands ran from `examples/mobile/hello-android` with `JAVA_HOME` set to
Temurin 17 and `ANDROID_HOME` set, unless stated.

### `doctor -p android`

All PASS except `[WARN] Emulator / virtualization: no AVD found`. The
byte-compile check reported `CPython 3.14 via this interpreter`: on macOS the
resolver picked the running kivyforge venv's CPython 3.14.7, not a
`python3.14` on `PATH`, for the 3.14.6 runtime. That is correct: `.pyc` files
need only the same minor version.

### `build -p android --debug --abi arm64_v8a`

```text
[collect] python.org runtime 3.14.6 (arm64_v8a)
[stage] installing 8 wheels for arm64_v8a
[stage] jniLibs/arm64-v8a: 106 extensions flattened
[stage] asset bundle assembled (stamp a059c68209b9e3f5)
[generate] hello-android-android/ regenerated
[gradle] assembleDebug
...
"Install CMake 3.22.1 v.3.22.1" finished.
...
BUILD SUCCESSFUL in 50s
```

Envelope: `ok: true`, artifacts `hello-android-android` (project) and
`hello-android-android/app/build/outputs/apk/debug/app-debug.apk` (apk,
25,296,236 bytes), no diagnostics.

### `package -p android --abi arm64_v8a --keystore <throwaway> --key-alias ci`

The keystore was generated with the same `keytool` command `android_gradle`
uses, but in `/tmp` so nothing new landed in the example.

```text
[stage] byte-compiling the Python payload with this interpreter (.pyc only)
[stage] asset bundle assembled (stamp cfa2402418362df7)
[generate] hello-android-android/ regenerated
[gradle] lintRelease (8 curated checks)
BUILD SUCCESSFUL in 8s
[policy] merged release manifest
[gradle] assembleRelease
BUILD SUCCESSFUL in 9s
```

Envelope: `ok: true`, artifact `.../apk/release/app-release.apk` (25,570,454
bytes), no diagnostics.

### The three T3 drivers, as `android_gradle` runs them

| Driver | Input | Result |
|---|---|---|
| `test_apk_artifact.py --android-abi arm64-v8a` | debug APK | 1 passed |
| `test_apk_artifact.py --android-abi arm64-v8a --android-stripped` | release APK | 1 passed |
| `test_merged_manifest.py --android-project examples/mobile/hello-android` | merged release manifest | 1 passed |
| `test_apk_signature.py` with `KIVYFORGE_REQUIRE_TOOLCHAIN=1` | release APK | 1 passed (really ran `apksigner`) |

Each driver is one test that collects every problem into a list, so "1
passed" means no problems, not one check.

### On the phone (beyond the task)

`run -p android --device --smoke --abi arm64_v8a`:

```text
[smoke] device 56051JEKB16396; building the probe...
...
[smoke] running the contract test on 56051JEKB16396...
Contract smoke test PASSED.
```

(`Starting 1 tests on Pixel 8a - 17` / `Finished 1 tests on Pixel 8a - 17` in
the Gradle log; exit 0 in 34 s.)

`run -p android --device --abi arm64_v8a` installed and launched the app; the
log reached `[Base] Start application main loop` on `Mali-G715`, OpenGL ES
3.2, and the process was still alive afterwards. The maintainer confirmed the
app visibly ran on the phone.

## Observations, not macOS-specific

None of these is a macOS-host defect; they would show on any host.

- **`run --smoke` without `--release` stages the release payload.**
  `android_smoke` calls `android_build(debug=False)`, so the debug smoke test
  byte-compiles and reuses the release stamp (`cfa24…`), although
  `byte_compile = "release"`. **Fixed on this branch:** `debug=False` was the
  only way to skip `assembleDebug`, which the connected test does not need, and
  the release staging came with it. `android_build(assemble=False)` now skips
  that step alone, and the smoke test stages the payload of the variant it
  tests. Re-run on the Pixel 8a with the fix: `run -p android --smoke
  --device` PASSED, staging stamp `a059c68209b9e3f5`, the same as
  `build --debug`'s (before the fix it was `package`'s `cfa2402418362df7`).
- **`run --smoke` prints progress to stdout** with `click.echo`, where `build`
  and `package` send it to stderr. `AGENTS.md` says backends never print.
  *(Fixed 2026-09-28 for `--smoke`, and for plain `run` on Android and the
  desktop platforms: progress to stderr, stdout only the verdict or the
  app's output.)*
- **Kivy/SDL warnings on Android 17**, from the app, not the build:
  `hidapi: hid_init threw an exception … RECEIVER_EXPORTED or
  RECEIVER_NOT_EXPORTED should be specified` (SDL2's HID support on Android
  14+; not fatal), `Failed to import "android" module. Could not remove android
  presplash.` and `Unknown <android> provider`.
- An earlier draft said `doctor`'s adb check passed the phone while it was
  `unauthorized`. **That was wrong.** `adb.connected_devices()` keeps only
  devices in the `device` state, so an unauthorized phone is dropped, and
  `doctor` WARNs "no device or emulator attached". The phone had been
  authorized by the time `doctor` ran; `adb devices` was not re-checked.
- Byte-compiling Kivy on CPython 3.14 prints
  `kivy/uix/codeinput.py:204: SyntaxWarning: 'return' in a 'finally' block`.

## Not done

- No `x86_64` build: Task 4 asked for `arm64_v8a`, and there is no AVD here.
- The tracked `pylock.android.toml` was not re-locked and is unchanged.
