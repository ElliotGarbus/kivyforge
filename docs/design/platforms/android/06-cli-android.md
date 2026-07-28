# Android — CLI Behavior

> **Status: design.** The Android analog of [iOS CLI behavior](../ios/04-cli-ios.md).

This document defines the **Android-specific behavior** of the kivyforge CLI verbs
— the flags, the Gradle/`adb`/emulator integration, and the Android `doctor`
checks. For the cross-platform verb model, the `--platform` / `-p` selector, the
`KIVYFORGE_PLATFORM` env var, and the platform-resolution chain, see
[common CLI + platform resolution](../../common/02-cli-and-platform-resolution.md).

All verbs look for `pyproject.toml` in the **current working directory only**; run
`kivyforge` commands from the directory that contains it.

## Host support

The Android backend runs on **Windows, macOS, and Linux**. kivyforge consumes
**prebuilt** wheels and the prebuilt python.org runtime and drives Gradle + the
Android SDK/NDK + `apksigner`/`adb` — all of which are cross-platform — so no
POSIX-only build step is involved. (Cross-*building* the Kivy/pyjnius wheels
themselves needs a Linux/macOS host, but that is an out-of-band, upstream step;
`kivyforge build` only consumes the resulting wheels.)

## Verbs (Android behavior)

| Verb | Android behavior |
|------|------------------|
| `init` | Seed `[tool.kivy]` + `[tool.kivy.android]` into `pyproject.toml`. |
| `lock` | Resolve `[project].dependencies` (per ABI), the python.org runtime, `.aar`/`.jar`, and Gradle/Maven deps; write `pylock.android.toml`. `--check` for CI pre-flight. |
| `build` | Download artifacts, stage `jniLibs/` + the Python bundle, and (re)generate the `<app>-android/` Gradle project. Without `--debug`, stops here — ready to open in Android Studio or assemble. |
| `build --debug [-f apk\|aab]` | Same as `build`, then `assembleDebug` (`.apk`) / `bundleDebug` (`.aab`, niche), debug-keystore signed — the fast dev-loop build. |
| `run [--emulator\|--device]` | Build (unless `--no-build`), install via `adb`, launch on an emulator or connected device. |
| `package -f apk\|aab` | Produce the **signed release** distributable: `assembleRelease` (`.apk`) / `bundleRelease` (`.aab`). Runs the release signing pre-flight first. |
| `open` | Open `<app>-android/` in Android Studio. |
| `upgrade` | Re-download the pinned python.org runtime and `.aar`/`.jar` artifacts per the existing lock. |
| `clean [--cache]` | Remove generated artifacts; with `--cache`, also flush the download cache. |
| `status` | Read-only project snapshot: identity, Python version, SDL generation, lock sync, build state. |
| `doctor` | Environment + project health check, including host-capability checks for Android. |

## Verb-by-verb specifics

### `kivyforge init`

Flags: `--force` (overwrite an existing `[tool.kivy.android]` table).

Pure file-in/file-out: reads `pyproject.toml`, auto-fills metadata, writes
`[tool.kivy]` + `[tool.kivy.android]`. A `pyproject.toml` is required (init does
not migrate `buildozer.spec` or `requirements.txt` automatically; if a
`buildozer.spec` is found without a `pyproject.toml`, init exits non-zero with a
migration pointer listing the equivalent `[tool.kivy.android]` keys).

- Seeds `app_dir = "src"`, `entry_point = "main"`; `package = "org.example.<slug>"` with a change-me comment; `min_sdk = 24`, `target_sdk`/`compile_sdk` = latest known; `sdl` from the seeded Kivy version; `abis = ["arm64_v8a", "x86_64"]`.
- Seeds `[tool.kivy.android.python].version` (latest known), `[tool.kivy.android.permissions].uses = ["INTERNET"]`, and commented TODO stubs for `[tool.kivy.android.icons]`, `[tool.kivy.android.splash]`, `[tool.kivy.android.signing]`, and (when vendoring) `find_links = ["wheels"]`.
- When `kivy` is a direct dependency, seeds the documented `exclude` block.
- **`--force`** preserves user-specific values it can't re-derive (the `signing` table, the pinned `python.version`, `package`, `abis`, `sdl`, icon/splash sources) and regenerates the rest to template defaults.

Version pinning of `[project].dependencies` is `kivyforge lock`'s job, not init's.

### `kivyforge lock`

Flags: `--update`, `--offline`, `--check` (same semantics as iOS).

Resolves per-ABI wheels (with the missing-ABI / inconsistent-version fail-fast
checks), the per-ABI python.org runtime, `.aar`/`.jar` SHA-256s, and — when
`[tool.kivy.android.gradle].dependencies` is non-empty — runs Gradle dependency
locking + hash verification against a scratch project and embeds the resolved
transitive graph (per-artifact SHA-256) under `[[tool.kivyforge.gradle.resolved]]`
in the lock (`kivyforge build` later materializes `app/gradle.lockfile` and
`gradle/verification-metadata.xml` from it — see
[pylock-android-spec §"Gradle/Maven pins"](02-pylock-android-spec.md#toolkivyforgegradle--mavengradle-pins)).
Writes `pylock.android.toml`. Exits non-zero
with a clear error if no pyproject is present or it lacks `[tool.kivy.android]`.

> **`lock` may require a JDK + network for the Gradle channel.** Generating the
> Gradle dependency lock needs a reachable JDK/Gradle and Maven repositories. When
> `[tool.kivy.android].gradle.dependencies` is empty (the common Kivy case), this
> step is skipped and `lock` needs only pip resolution + python.org metadata.

### `kivyforge build`

Flags:

- `--debug` (optional; **no default**). Without it, `build` stops after generating the project (ready for Android Studio or a manual `gradlew`). With it, `build` invokes Gradle after staging: `assembleDebug` (debug-keystore signed) — the fast dev-loop build. **Signed release artifacts are produced by [`kivyforge package`](#kivyforge-package), not `build`.**
- `-f apk|aab` / `--format apk|aab` (default `apk`; only meaningful with `--debug`). `-f apk` → `assembleDebug` (`.apk`). `-f aab` → `bundleDebug` (`.aab`, niche — only to test bundle delivery via `bundletool`).
- `--abi arm64_v8a|x86_64` (restrict this build to one ABI; default: all `[tool.kivy.android].abis`). Handy for a fast emulator loop with the host-architecture ABI: `--abi x86_64` on an x86_64 host, `--abi arm64_v8a` on an arm64 host (Apple Silicon).
- `--no-verify-lock` (skip the `pyproject_sha256` drift check; CI only).
- `--no-cache` (force re-download of every artifact).

`build` always performs the staging + generation steps 1–7; step 8 only runs with `--debug`.

1. Verify `pyproject.toml` and `pylock.android.toml` are present and in sync (drift check).
2. Download (or cache hit) the per-ABI python.org runtime from `[[tool.kivyforge.python_android]]`; extract into `<app>-android/python-runtime/<abi>/`.
3. Download (or cache hit) each `[[tool.kivyforge.android_libs]]` `.aar`/`.jar` into `<app>-android/app/libs/`.
4. Install the pinned wheels per ABI into `pip-deps/<abi>/` with Android cross-install flags (`pip install --platform android_<api>_<abi> --python-version <X.Y> --abi <abi> --only-binary :all: --no-deps --target ...`). The lock holds the full transitive set with URLs/hashes, so `--no-deps` is used and pip does not re-resolve.
5. Lay native libraries into `jniLibs/<abi>/`: the runtime `.so`s, each wheel's `.so` extension modules (per the embeddable-package mapping), and each wheel's flat `.libs/` payload (the Kivy SDL family), keyed by the wheel's platform tag. Apply the duplicate-`.so` policy.
6. Assemble the ABI-independent Python bundle into `assets/_python_bundle/` (stdlib + `pip-deps` pure-Python + app code via the `app-src/` staging link).
7. (Re)generate the Gradle project: `AndroidManifest.xml`, `app/build.gradle`, `gradle.properties`, the bootstrap sources for the selected `sdl`, and icon/splash resources. Before emitting the bootstrap, verify the locked `pyjnius` version is within the template's compatible range and **abort** on a mismatch (the `NativeInvocationHandler.invoke0` ABI pair). See [gradle-project-generation](04-gradle-project-generation.md).
8. *(Only with `--debug`)* Invoke the Gradle wrapper against the Android **debug** keystore (no signing config required):
   - `-f apk` (default): `gradlew assembleDebug` → debug-keystore-signed `.apk` in `app/build/outputs/apk/debug/`.
   - `-f aab`: `gradlew bundleDebug` → debug-key JAR-signed `.aab` in `app/build/outputs/bundle/debug/` (niche; only for testing bundle delivery via `bundletool`).

#### Step 4 — pip platform tag

| Build ABI | Platform tag |
|-----------|--------------|
| `arm64_v8a` | `android_<min_sdk>_arm64_v8a` |
| `x86_64` | `android_<min_sdk>_x86_64` |
| *(none / all)* | both slices installed (project builds any configured ABI) |

`<min_sdk>` is `[tool.kivy.android].min_sdk`. End users never type a raw pip
command; flags are derived from the lock + CLI args. pip treats the tag API as a
target floor, so a compatible lower-tag wheel (e.g. `android_21_*` for
`min_sdk = 24`) is still accepted.

### `kivyforge package`

Produces the **signed release distributable** — the "produce" verb of the
[common CLI model](../../common/02-cli-and-platform-resolution.md#the-package-verb-and-the--f-format-slot).
Flags:

- `-f apk|aab` / `--format apk|aab` (default `apk`). `-f apk` → `assembleRelease` (`.apk`, sideload / store-independent). `-f aab` → `bundleRelease` (`.aab`, Play upload).
- `--abi`, `--no-verify-lock`, `--no-cache` (as in `build`).
- `--keystore PATH` / `--key-alias NAME` (override `[tool.kivy.android.signing]`; passwords via `KIVYFORGE_KEYSTORE_PASSWORD` / `KIVYFORGE_KEY_PASSWORD`). Useful for CI where signing config isn't committed.

`package` performs the same staging + generation steps 1–7 as `build`, then:

- **Signing pre-flight (fail fast).** Resolve the effective keystore + alias (precedence: `--keystore`/`--key-alias` → `[tool.kivy.android.signing]`) and confirm the passwords are present in the configured env vars. If unresolved, exit non-zero **before** invoking Gradle:

  ```
  Error: code signing required to package a release, but no keystore is resolved.
    Set it one of these ways:
      • [tool.kivy.android.signing] keystore/key_alias in pyproject.toml, then re-lock
      • kivyforge package --keystore release.keystore --key-alias upload
    And export the passwords:
      • export KIVYFORGE_KEYSTORE_PASSWORD=...   (and KIVYFORGE_KEY_PASSWORD if different)
  ```

- **Manifest policy preflight (fail fast).** Before signing, kivyforge lints the *merged* release manifest and blocks on policy violations. It **delegates the well-covered checks to a curated Android `lintRelease` subset** (unexpectedly exported components, `allowBackup` posture, cleartext-traffic posture) and **hand-rolls only what Lint misses**: exactly one `LAUNCHER` activity and no conflicting deep-link `<data>` (scheme/host); every intent-filtered component sets `android:exported` explicitly and only the bootstrap's expected components (`PythonActivity`) are exported; `android:debuggable` is not forced `true` in a release (a manifest-passthrough override that would ship a debuggable release); and the `applicationId` is **not** the `org.example.*` init placeholder. Dangerous runtime permissions are reported (INFO) as a reminder they need a runtime request. A FAIL aborts **before** Gradle; the only sanctioned way to change a flagged attribute is through the manifest escape hatches (passthrough / raw XML), never by editing the generated file. See [gradle-project-generation §"Manifest generation"](04-gradle-project-generation.md#manifest-generation).
- **Gradle release build + sign.** `-f apk` → `gradlew assembleRelease` → signed `.apk` in `app/build/outputs/apk/release/`; `-f aab` → `gradlew bundleRelease` → signed `.aab` in `app/build/outputs/bundle/release/`.
- **APK vs AAB signing.** For `.apk` Gradle invokes `apksigner` and the v1–v4 scheme toggles from `[tool.kivy.android.signing]` apply directly. An `.aab` is **JAR-signed (`jarsigner`) with the same key** — the v2–v4 APK signature schemes do **not** apply to the `.aab` container; they apply to the per-device APKs Play (or `bundletool`) derives from it (with Play App Signing, signed by Google with the app key).
- **Native debug symbols.** A stripped release (`build_settings.strip_native_libs` on, the default) also emits `app/build/outputs/native-debug-symbols/release/native-debug-symbols.zip` per `build_settings.debug_symbols`, for Play/crash-reporter symbolication — the Android analog of iOS dSYMs. See [pyproject-android §"Native debug symbols"](01-pyproject-android.md#native-debug-symbols).

### `kivyforge run`

Flags:

- `--emulator` / `--device` (mutually exclusive mode selectors; default: auto — a connected device if exactly one is attached, else the default/most-recent AVD emulator).
- `--avd NAME` (which AVD to boot when `--emulator`), `--serial ID` (which `adb` device when several are attached).
- `--list-devices` (print `adb devices` + available AVDs, exit).
- `--no-build` (skip the build; install + launch the already-assembled `.apk`).
- `--abi` (as in `build`; for `--emulator` defaults to the **host architecture's** ABI — `x86_64` on an x86_64 host, `arm64_v8a` on an arm64 host such as Apple Silicon, matching the system images the emulator runs at native speed — and `arm64_v8a` for a physical device).
- `--smoke` (run the generated **contract smoke test** instead of a normal launch; exits non-zero on failure — see below).
- `--release` (with `--smoke`: target the **release** variant/artifact instead of a debug build, so the probe exercises byte-compilation, stripping, and R8).

**Implicit build step.** By default `run` performs `build --debug` for the
selected target, then installs and launches:

1. `--emulator`: boot the AVD if not running (`emulator -avd <name>`), wait for `adb wait-for-device` + `sys.boot_completed`, `adb install -r`, launch via `adb shell am start -n <package>/org.kivy.android.PythonActivity`, and stream logcat (`adb logcat`) filtered to the app.
2. `--device`: `adb install -r`, then the same `am start` + logcat.

If the lock is out of date (drift check fails), `run` propagates the same error as
`build` and exits before doing anything.

#### `--smoke`: the contract smoke test

`kivyforge run --smoke` runs a **kivyforge-generated instrumented test** (not
app-specific — you write no test code) that validates the load-bearing runtime
contract on a real emulator/device, via the platform's own instrumented-test path
(`gradlew connected<Variant>AndroidTest`):

1. **Launch** — `PythonActivity` starts and the bootstrap initializes CPython with no crash in the SDL → `libpython` → `libmain` load order; the app signals *ready*.
2. **Extension-module import** — a known stdlib `lib-dynload` module **and** a wheel extension import successfully through the `sys.meta_path` finder, proving the flattened-`.so` + manifest mechanism works on-device (see [bootstrap-android §"Extension-module finder"](05-bootstrap-android.md#extension-module-finder)).
3. **pyjnius proxy round-trip** — a `PythonJavaClass`/`@java_method` proxy (`Runnable`/`Comparator`) invoked from Java fires `invoke0`, proving the `NativeInvocationHandler` glue + SDL-loaded `JNIEnv` contract (see [bootstrap-android §"Contract smoke-test hook"](05-bootstrap-android.md#contract-smoke-test-hook)).

It reports green/red with a **non-zero exit on any failure**. `--release`
smoke-tests the **release variant** (byte-compiled, stripped, R8-processed) under
a test-instrumentation signing config, so the gate catches a finder break from
stripping or a missing R8 keep-rule — not just a debug build. The same probe
backs kivyforge's own canary CI, so a kivyforge regression and a project
regression are caught by identical assertions.

> **Required release gate (CI).** Because it needs a device/emulator, the smoke
> test is deliberately **not** part of the headless `package` path. Instead it is
> the **required step between `package` and store upload**: package the release
> artifact, boot an emulator, run `kivyforge run --smoke --release`, and publish
> only on green. `doctor`'s **Emulator / virtualization** check gates whether the
> job can run on a given host.

### `kivyforge open`

Opens `<app>-android/` in Android Studio (via the platform opener / `studio`
launcher if resolvable). Exits with a clear error if `kivyforge build` hasn't been
run yet. Typical IDE flow:

```bash
kivyforge init && kivyforge lock && kivyforge build
kivyforge open   # → pick a device in Android Studio → Run
```

### `kivyforge upgrade`

Flags: `--python` (only the runtime), `--libs` (only `.aar`/`.jar`), `--name NAME`.

Re-fetches the pinned python.org runtime and/or `[[tool.kivyforge.android_libs]]`
per the **existing lock** — does not reinstall wheels, regenerate the project, or
invoke Gradle. To pick up newer versions, edit `pyproject.toml` and re-run
`kivyforge lock`.

### `kivyforge clean`

Flags: `--cache` (also flush the artifact download cache), `--project-only`
(default; only the generated `<app>-android/`). `--cache` additionally runs
`gradlew --stop` and clears the project's Gradle build cache; the shared
`~/.gradle` is left alone unless `--cache-all` is passed.

### `kivyforge status`

Read-only snapshot:

```
App:        touchtracer  (org.kivy.touchtracer)
Python:     3.14.6
Kivy/SDL:   kivy 2.3.1  (sdl 2)
ABIs:       arm64_v8a, x86_64
Lock:       in sync
Build:
  apk (debug)     built 5 minutes ago
  aab (release)   not built
```

| Field | Source |
|-------|--------|
| App / package | `[project].name` / `[tool.kivy].display_name`; `[tool.kivy.android].package` |
| Python | `[tool.kivy.android.python].version` |
| Kivy/SDL | resolved `kivy` version + `[tool.kivy.android].kivy_generation` |
| ABIs | `[tool.kivy.android].abis` |
| Lock | `pyproject_sha256` compare — `in sync` / `out of date` / `missing` |
| Build | presence + mtime of `.apk`/`.aab` under `app/build/outputs/` |

### `kivyforge doctor`

Runs in **environment mode** (no pyproject) or **project mode** (pyproject
present), like iOS. Each check reports PASS / WARN / FAIL with a remediation hint;
exit code is non-zero only on FAIL.

> **kivyforge never installs the host toolchain.** The JDK and the Android
> SDK/NDK/build-tools are **user-installed prerequisites** (via Android Studio's
> SDK Manager or the official `sdkmanager`), exactly as Xcode is on iOS. `doctor`
> only *detects* them and prints an actionable hint — it does **not** download,
> install, or auto-`--fix` them, and kivyforge ships **no** bundled downloader.
> This is deliberate: hardcoding installer URLs, package coordinates, or pinned
> component versions would be a standing maintenance/drift liability when those get
> moved or renamed. Accordingly, `doctor` checks for *adequacy* (a resolvable SDK,
> a build-tools version compatible with `compile_sdk`, accepted licenses, the NDK
> — now required for every build, since it compiles the native launcher) and
> derives any suggested `sdkmanager`
> package name from your own project config (e.g. `platforms;android-<compile_sdk>`)
> rather than from a maintained version manifest.

| Check | Scope | What it validates |
|-------|-------|-------------------|
| JDK | environment | A supported JDK (17+) on `PATH` / `JAVA_HOME`; the version AGP requires. |
| Android SDK | environment | `ANDROID_HOME`/`ANDROID_SDK_ROOT` resolves; `sdkmanager` present. |
| Build-tools / platform | environment | The `compile_sdk` platform + a matching build-tools version are installed. |
| SDK licenses | environment | `sdkmanager --licenses` accepted; FAIL with the accept command if not. |
| NDK | environment | **Required for every build** — AGP + the NDK compile the bootstrap's native launcher (`libmain.so`) from the emitted `cpp/` sources (a symbol-exporting release also uses the NDK to extract `native-debug-symbols.zip`). FAIL if no NDK resolves, with the `sdkmanager 'ndk;<version>'` hint. |
| Gradle wrapper | environment/project | The pinned wrapper is present and its distribution downloadable. |
| Emulator / virtualization | environment | For `run --emulator`: an AVD exists and the host has hardware acceleration (KVM on Linux, HAXM/Hypervisor on macOS/Windows). WARN with setup pointer if missing. |
| `adb` devices | environment | `adb` present; in `run`, at least one device/emulator reachable. |
| kivyforge version | environment | Self-version + newer-on-PyPI nudge (best-effort). |
| App source directory | project | `[tool.kivy].app_dir` resolves to an existing directory. |
| SDL / Kivy match | project | `[tool.kivy.android].kivy_generation` matches the resolved `kivy` version (SDL2 for `< 3.0`, SDL3 for `>= 3.0`); WARN on mismatch. |
| pyjnius / bootstrap match | project | The locked `pyjnius` version is within the bootstrap template's compatible range (the `NativeInvocationHandler.invoke0` ABI pair); **FAIL** otherwise — `kivyforge build` enforces the same gate and aborts before generating the bootstrap. |
| 16 KB alignment | project | Every staged `.so` LOAD segment is 16 KB-aligned and the APK is 16 KB zip-aligned; FAIL on a 4 KB-aligned library (won't load on Android 15/16 16 KB-page devices). |
| ABI coverage | project | Every compiled dependency has a wheel for each `[tool.kivy.android].abis` entry (mirrors the lock-time missing-ABI check; catches a stale lock). |
| App icon | project | If `[tool.kivy.android.icons].source` is set, FAIL unless it is a valid PNG of the expected size. SKIP if unset. |
| Splash assets | project | If `[tool.kivy.android.splash]` is set, FAIL unless each referenced file (`source`, `branding`) exists and `source` is a valid PNG or AnimatedVectorDrawable; WARN if `animation_duration` is set for a non-animated `source`. SKIP if unset. |
| find_links directories | project | If `find_links` is set, FAIL on a non-existent dir; WARN if it has no `.whl`. |
| Signing (release) | project | If `[tool.kivy.android.signing]` is set: the keystore exists, the alias is present (`keytool -list`), and the password env vars are set. |
| Required hosts reachable | project | TCP connect to every host the lock will fetch from (python.org, PyPI/supplemental indexes, `.aar`/`.jar` URLs, Maven repos). Derived from `pylock.android.toml`; `path` entries skipped. |
| App-local native binaries | project | Scan `app_dir` for `.so`; FAIL on any non-Android-ABI binary (native code belongs in an Android wheel, not `app_dir`). |
| include_files | project | Each `[[tool.kivy.android.include_files]]` `source` exists and each `dest` stays inside the project without clobbering a generated file; FAIL otherwise. Warns on drift vs. the locked SHA-256. |
| Manifest raw XML | project | `manifest.extra_manifest_xml` / `extra_application_xml` / `extra_activity_xml` parse as well-formed XML; FAIL with the parse error and offset otherwise. |
| Manifest policy (release) | project | The release-manifest preflight `kivyforge package` runs (see there): exported components explicit and limited to the bootstrap set, single `LAUNCHER`, no deep-link conflicts, `debuggable` not forced on, `allowBackup`/cleartext posture, and a non-placeholder (`org.example.*`) `applicationId`. Runs the curated `lintRelease` subset + kivyforge checks; **FAIL** blocks a release (advisory INFO for dangerous runtime permissions). |
| Implied features | project | Reports (INFO) the non-required `<uses-feature>` set `auto_features` will synthesize from `permissions.uses`, so Play device-filtering is visible before upload. |

## Version and upgrade policy

Everything the build depends on falls into **three layers**, each upgraded a
different way. kivyforge never blurs them:

### 1. Lock-pinned, hash-verified — `kivyforge lock --update`

The reproducibility surface: the **python.org runtime** (per ABI), all **wheels**
(Kivy, pyjnius, dependencies), and every **Maven artifact** (with its
`verification-metadata.xml` SHA-256s). All are pinned by content hash in
`pylock.android.toml`. **`kivyforge lock --update` is the single command that
re-resolves and re-pins all of them at once** — new runtime, new wheels, and a
freshly written Gradle resolved graph + verification metadata — so the pinned
evidence moves together and stays internally consistent. (`kivyforge upgrade`
only re-*fetches* what the existing lock already pins, with no version change; to
take newer versions, edit `pyproject.toml` and re-lock.)

### 2. kivyforge-emitted tool pins — move with a kivyforge release

The versions kivyforge writes into the generated (regenerated) project: the
**Gradle wrapper**, **AGP** / **Kotlin**, and the **`ndkVersion`** for the native
launcher. These track the kivyforge release you run (validated together) and are
overridable through `[tool.kivy.android.gradle]` / `gradle_properties` for a
project that must pin differently. Because the project is regenerated, bumping
kivyforge and re-running `build` is the normal way to move them.

### 3. User-installed host toolchain — kivyforge detects, never installs

The **JDK**, **Android SDK / build-tools**, and the **NDK** binaries are
prerequisites you install (Android Studio SDK Manager / `sdkmanager`), exactly as
Xcode is on iOS. kivyforge **cannot upgrade these** — `doctor` only checks
*adequacy* against your project config and prints an `sdkmanager` hint derived
from your own settings. There is **no** kivyforge-driven SDK/NDK upgrade and **no**
maintained version manifest (that would be a standing drift liability).

**`compile_sdk` / `target_sdk`** sit at the boundary: they are *your* declared
values in `pyproject.toml` (a layer-1 config choice), but satisfying them requires
the matching installed platform (layer 3). Raise them to track
[Play's `target_sdk` deadlines](08-compatibility-matrix.md#the-one-calendar-constraint-play-target_sdk-deadlines),
then install the platform `doctor` names.

## Mobile window/display geometry: `kivy.mobile`

Like iOS, runtime geometry (DPI, scale, safe-area insets, software-keyboard
height) belongs in **Kivy core** (`kivy.mobile`), not the build tool.
`kivy.mobile._platform.android` provides the Android implementation (via pyjnius),
shipped inside the Kivy Android wheel. **kivyforge vendors no platform shim** —
`kivyforge build` writes no `platform/` directory. App code guards on
`kivy.utils.platform == "android"` and, in Kivy 3.0, can bind `Window.safe_area`
directly.
