# Android — CLI Behavior

> **Status: implemented (v1).** The Android analog of [iOS CLI behavior](../ios/04-cli-ios.md).

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
| `clean [--cache\|--cache-all]` | Remove generated artifacts (stopping the project's Gradle daemon first); with `--cache`, also flush the download cache; with `--cache-all`, the shared Gradle caches too. |
| `status` | Read-only project snapshot: identity, Python version, SDL generation, lock sync, build state. |
| `doctor` | Environment + project health check for Android. Advisory: it reports, it is not a build gate. |

## Verb-by-verb specifics

### `kivyforge init`

Flags: `--force` (overwrite an existing `[tool.kivy.android]` table).

Pure file-in/file-out: reads `pyproject.toml`, auto-fills metadata, writes
`[tool.kivy]` + `[tool.kivy.android]`. A `pyproject.toml` is required (init does
not migrate `buildozer.spec` or `requirements.txt` automatically; if a
`buildozer.spec` is found without a `pyproject.toml`, init exits non-zero with a
migration pointer. That pointer maps each `[app]` key onto its kivyforge key and
echoes the spec's own value beside it where it can read one, then names the
settings with no counterpart at all — the `p4a.*` knobs, recipe-style
`requirements`, the `android.ndk`/`android.sdk` pins kivyforge owns, and
`android.add_src` — and why.)

- Seeds `app_dir = "src"`, `entry_point = "main"`; `package = "org.example.<slug>"` with a change-me comment; `min_sdk = 24`, `target_sdk`/`compile_sdk` = latest known; `kivy_generation = 2` with a comment naming both choices (it is not inferred from `[project].dependencies` — `lock` has not run yet, so the resolved Kivy version is not known at `init` time); `abis = ["arm64_v8a", "x86_64"]`.
- Seeds `[tool.kivy.android.python].version` (latest known), `[tool.kivy.android.permissions].uses = ["INTERNET"]`, and commented TODO stubs for `[tool.kivy.android.icons]`, `[tool.kivy.android.splash]`, `[tool.kivy.android.signing]`, `find_links = ["wheels"]` (a local wheelhouse for wheels you cross-build yourself), and `extra_index_urls` pointing at the `kivy-mobile-wheels` index (where the first-party Kivy/pyjnius Android wheels live until they are on PyPI).
- When `kivy` is a direct dependency, seeds the documented `exclude` block.
- **`--force`** preserves user-specific values it can't re-derive (the `signing` table, the pinned `python.version`, `package`, `abis`, `kivy_generation`, icon/splash sources) and regenerates the rest to template defaults.

Version pinning of `[project].dependencies` is `kivyforge lock`'s job, not init's.

### `kivyforge lock`

Flags: `--update`, `--offline`, `--check` (same semantics as iOS).

Resolves per-ABI wheels (with the missing-ABI / inconsistent-version fail-fast
checks), the per-ABI python.org runtime, `.aar`/`.jar` SHA-256s, and — when
`[tool.kivy.android.gradle].dependencies` is non-empty — runs Gradle dependency
locking + hash verification against a scratch project and embeds the resolved
transitive graph (per-artifact SHA-256) under `[[tool.kivyforge.gradle.resolved]]`
in the lock (`kivyforge build` later mirrors it into `app/gradle.lockfile` as the
audit record; it is not re-verified at build time — see
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
6. Assemble the ABI-independent Python bundle into `assets/_python_bundle/` (stdlib + `pip-deps` pure-Python + app code copied from `app_dir`).
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

- **Manifest policy preflight (fail fast), in two passes.** kivyforge's own checks are: exactly one `LAUNCHER` activity and no conflicting deep-link `<data>` (scheme/host); every intent-filtered component sets `android:exported` explicitly and only the baseline components (`PythonActivity`; `androidx.profileinstaller.ProfileInstallReceiver`, which the hardcoded Material Components dependency always pulls in and AndroidX exports by design, gated by the system-only `DUMP` permission; plus anything in `[tool.kivy.android.manifest].allow_exported`) are exported; `android:debuggable` is not forced `true` in a release (a manifest-passthrough override that would ship a debuggable release); and the `applicationId` is **not** the `org.example.*` init placeholder. Cleartext traffic and dangerous runtime permissions are reported (INFO) as reminders.
  - **Pass 1 — the generated manifest, before any Gradle work.** An own goal (the placeholder `applicationId`, a passthrough that forces `debuggable`) costs nothing to find, so it is found first.
  - **Pass 2 — Lint plus the *merged* manifest.** `gradlew lintRelease exportKivyforgeReleaseManifest` runs the **curated `lintRelease` subset** — `AllowBackup`, `Exported{Activity,Service,Receiver,ContentProvider,PreferenceActivity}`, `IntentFilterExportedReceiver`, `InsecureBaseConfiguration` — and exports AGP's merged release manifest (via the public Artifacts API, since the intermediates layout is not a contract) to `app/build/kivyforge/AndroidManifest-merged-release.xml`; the same kivyforge checks then run over *that*, which is what actually ships, `.aar`/Maven library manifests included. The generated `lint {}` block uses `checkOnly` + `fatal` for exactly that subset, so those findings break the build while a future Lint's new checks stay advisory.
  
  A FAIL in either pass aborts **before** the release is assembled and therefore before it is signed. Fix a flagged attribute through the manifest escape hatches (passthrough / raw XML) or, for a component a dependency insists on exporting, `allow_exported` — never by editing the generated file. See [gradle-project-generation §"Manifest generation"](04-gradle-project-generation.md#manifest-generation).
- **Gradle release build + sign.** `-f apk` → `gradlew assembleRelease` → signed `.apk` in `app/build/outputs/apk/release/`; `-f aab` → `gradlew bundleRelease` → signed `.aab` in `app/build/outputs/bundle/release/`.
- **APK vs AAB signing.** For `.apk` Gradle invokes `apksigner` and the v1–v4 scheme toggles from `[tool.kivy.android.signing]` apply directly. An `.aab` is **JAR-signed (`jarsigner`) with the same key** — the v2–v4 APK signature schemes do **not** apply to the `.aab` container; they apply to the per-device APKs Play (or `bundletool`) derives from it (with Play App Signing, signed by Google with the app key).
- **Native debug symbols.** A stripped release (`build_settings.strip_native_libs` on, the default) also emits `app/build/outputs/native-debug-symbols/release/native-debug-symbols.zip` per `build_settings.debug_symbols`, for Play/crash-reporter symbolication — the Android analog of iOS dSYMs. See [pyproject-android §"Native debug symbols"](01-pyproject-android.md#native-debug-symbols).

### `kivyforge run`

Flags:

- `--emulator` / `--device` (mutually exclusive mode selectors; default: auto — a connected device if exactly one is attached, else the default/most-recent AVD emulator). `--device` means hardware: it never falls back to booting an AVD, and errors naming what `adb` does see. (`--simulator` is iOS's selector and is rejected here.)
- `--avd NAME` (which AVD to boot when `--emulator`; contradicts `--device`), `--serial ID` (which `adb` device when several are attached; wins over both selectors).
- `--list-devices` (print `adb devices` + available AVDs, exit).
- `--no-build` (skip the build; install + launch the already-assembled `.apk`).
- `--abi` (as in `build`; defaults to **the resolved target's own ABI**, read from its `ro.product.cpu.abilist` — so an x86_64 AVD, an arm64 AVD on Apple Silicon, and an arm64 phone each build only what they can run. Falls back to the host architecture's ABI if the target reports nothing kivyforge builds for. A target needing an ABI the project does not lock **fails before Gradle runs**, naming both, rather than surfacing later as `INSTALL_FAILED_NO_MATCHING_ABIS`.)

- `--smoke` (run the generated **contract smoke test** instead of a normal launch; exits non-zero on failure — see below).
- `--release` (with `--smoke`: target the **release** variant/artifact instead of a debug build, so the probe exercises byte-compilation, stripping, and R8).

**Implicit build step.** By default `run` performs `build --debug` for the
selected target, then installs and launches:

1. Resolve the target **first** — because `--abi`'s default comes from it. `--emulator` boots the AVD if one is not already running (`emulator -avd <name>`) and waits for `sys.boot_completed`, so the emulator warms up while Gradle works; `--device` takes the attached device.
2. `build --debug --abi <the target's ABI>`, unless `--no-build`.
3. `adb install -r`, then launch via `adb shell am start -n <package>/org.kivy.android.PythonActivity`.
4. Capture logcat: `run` waits ~25s for the app to get through startup, then takes a **one-shot `adb logcat -d` dump** and echoes the lines tagged `kivyforge`, `python.std`, or `SDL`. It is a snapshot, not a live stream — `run` returns rather than tailing, which is what makes it usable as a scripted step. For live output, `adb logcat` alongside it.

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
stripping or a missing R8 keep-rule — not just a debug build. The probe is
generated by kivyforge, so a kivyforge regression and a project regression are
caught by identical assertions.

> **Required release gate (CI).** Because it needs a device/emulator, the smoke
> test is deliberately **not** part of the headless `package` path. Instead it is
> the **required step between `package` and store upload**: package the release
> artifact, boot an emulator, run `kivyforge run --smoke --release`, and publish
> only on green. `doctor`'s **Emulator / virtualization** check gates whether the
> job can run on a given host.

#### What kivyforge's own CI gates, and what it doesn't

Worth stating plainly, because "generated correctly" and "actually builds" are
different claims and only one of them is cheap to test:

| Gate | Where | Covers |
|------|-------|--------|
| Unit tests | every push (Ubuntu + Windows) | Generation, staging, lock, policy, and bootstrap-contract logic — every generated file as a *string*. |
| `android_gradle` job | every push (Ubuntu, no device) | The real toolchain consuming those strings: AGP + AAPT + javac + the NDK build [`examples/mobile/hello-android`](../../../../examples/mobile/hello-android) from its committed lock (`build --debug --abi x86_64`), the APK is asserted to carry `libmain.so`, `libpython3.14.so`, and `assets/_python_bundle/`, and `package` then runs the whole release policy path (curated `lintRelease` + merged-manifest export + signing) against a throwaway keystore. |
| `run --smoke` | **not** hosted CI | Everything that only a running app can prove: the load order, the extension-module finder, the pyjnius `invoke0` round-trip. It needs an emulator or device, so it is run locally / on a self-hosted runner and is the release gate above. Rows in [compatibility-matrix](08-compatibility-matrix.md) marked **Validated** cite those runs. |

### `kivyforge open`

Opens `<app>-android/` in Android Studio (via the platform opener / `studio`
launcher if resolvable). Exits with a clear error if `kivyforge build` hasn't been
run yet. Typical IDE flow:

```bash
kivyforge init && kivyforge lock && kivyforge build
kivyforge open   # → pick a device in Android Studio → Run
```

### `kivyforge upgrade`

Flags: `--python` (only the runtime), `--libs` (only `.aar`/`.jar` — Android's
counterpart to iOS's `--xcframeworks`; the two selectors are disjoint, so passing
both is an error), `--name NAME` (one `.aar`/`.jar` name, one ABI, or `python`
for every runtime; an unknown name errors listing the ones the lock holds).

Re-fetches the pinned python.org runtime and/or `[[tool.kivyforge.android_libs]]`
per the **existing lock** — does not reinstall wheels, regenerate the project, or
invoke Gradle. To pick up newer versions, edit `pyproject.toml` and re-run
`kivyforge lock`.

### `kivyforge clean`

Flags: `--cache` (also flush the artifact download cache), `--cache-all`
(`--cache` plus the shared Gradle caches), `--project-only` (default; only the
generated `<app>-android/`).

Removing `<app>-android/` takes the project's Gradle state (`app/build/`,
`.gradle/`) with it, so `clean` always runs `gradlew --stop` first when that
project exists: a live daemon holds file handles under `app/build`, which makes
the removal fail outright on Windows. `--cache-all` additionally clears
`caches/` and `daemon/` under `GRADLE_USER_HOME` (default `~/.gradle`) — shared
state, so this affects every project on the machine and the next build
re-downloads Gradle's dependencies. The wrapper distributions and any
`gradle.properties` there are configuration and are left alone.

### `kivyforge status`

Read-only snapshot:

```
App:        touchtracer  (org.kivy.touchtracer)
Python:     3.14.6
Kivy/SDL:   kivy 2.3.1  (kivy_generation 2)
ABIs:       arm64_v8a, x86_64
Lock:       in sync
Build:
  apk (debug)      built 2026-07-28 16:41
  apk (release)    not built
  aab (release)    not built
```

| Field | Source |
|-------|--------|
| App / package | `[project].name` / `[tool.kivy].display_name`; `[tool.kivy.android].package` |
| Python | `[tool.kivy.android.python].version` |
| Kivy/SDL | resolved `kivy` version from the lock (`—` if absent, `?` with no lock) + `[tool.kivy.android].kivy_generation` |
| ABIs | `[tool.kivy.android].abis` |
| Lock | `pyproject_sha256` compare — `in sync` / `out of date` / `missing` / `unreadable` |
| Build | presence + mtime of all three artifacts under `app/build/outputs/` — debug `.apk`, release `.apk`, release `.aab` — as `built YYYY-MM-DD HH:MM` or `not built` |

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
| SDK licenses | environment | At least one acceptance recorded under `<sdk>/licenses/` — the hash files AGP's auto-download consults; WARN with the `sdkmanager --licenses` command if none is. |
| NDK | environment | **Required for every build** — AGP + the NDK compile the bootstrap's native launcher (`libmain.so`) from the emitted `cpp/` sources (a symbol-exporting release also uses the NDK to extract `native-debug-symbols.zip`). FAIL if no NDK resolves, with the `sdkmanager 'ndk;<version>'` hint. |
| Gradle wrapper | project | Once the project is generated: `gradlew`/`gradlew.bat` and `gradle-wrapper.properties` are present (FAIL) and the `distributionUrl` is still kivyforge's pinned Gradle (WARN on drift — the project is a managed artifact, so rebuild rather than edit). SKIP before the first `build`. |
| Emulator / virtualization | environment | For `run --emulator`: an AVD exists and the host has hardware acceleration (KVM on Linux, HAXM/Hypervisor on macOS/Windows). WARN with setup pointer if missing. |
| `adb` | environment | `adb` resolves (on `PATH` or under `<sdk>/platform-tools/`); WARN listing nothing attached when `adb devices` is empty, since `run` and `run --smoke` need one. |
| kivyforge | environment | The running version, plus a WARN nudge when PyPI has a newer one (best-effort; skipped under `--offline`). The generated project's toolchain pins move with a kivyforge release, so this is build-relevant. |
| Android config | project | `pyproject.toml`'s `[tool.kivy.android]` loads and validates. This subsumes every rule the loader enforces — including that `manifest.extra_manifest_xml` / `extra_application_xml` / `extra_activity_xml` parse as well-formed XML, and that each `include_files` `dest` stays inside the project without clobbering a generated file — so a config error is one **FAIL** here carrying the loader's own message rather than a row per rule. Every project check below reads the config, so a failure here ends the run. |
| App source directory | project | `[tool.kivy].app_dir` resolves to an existing directory. |
| SDL / Kivy match | project | `[tool.kivy.android].kivy_generation` matches the resolved `kivy` version (SDL2 for `< 3.0`, SDL3 for `>= 3.0`); WARN on mismatch. |
| pyjnius / bootstrap match | project | The locked `pyjnius` version is within the bootstrap template's compatible range (the `NativeInvocationHandler.invoke0` ABI pair); **FAIL** otherwise — `kivyforge build` enforces the same gate and aborts before generating the bootstrap. |
| 16 KB alignment | project | Every `.so` staged under `app/src/main/jniLibs/` has 16 KB-aligned LOAD segments; **FAIL** naming each 4 KB-aligned one (it won't load on an Android 15/16 16 KB-page device). Post-`build` only — SKIP when nothing is staged yet. The APK's *zip* alignment is AGP's job and is not re-checked. |
| ABI coverage | project | Every compiled dependency has a wheel for each `[tool.kivy.android].abis` entry (mirrors the lock-time missing-ABI check; catches a stale lock). |
| App icon | project | If `[tool.kivy.android.icons].source` is set, FAIL unless it is a valid PNG of the expected size. SKIP if unset. |
| Splash assets | project | If `[tool.kivy.android.splash]` is set, FAIL unless each referenced file (`source`, `branding`) exists and `source` is a valid PNG or AnimatedVectorDrawable; WARN if `animation_duration` is set for a non-animated `source`. SKIP if unset. |
| find_links directories | project | If `[tool.kivy.android].find_links` is set, FAIL on a missing or non-directory entry; WARN on one holding no `.whl`. SKIP if unset. |
| Signing (release) | project | If `[tool.kivy.android.signing]` is set: the keystore exists, the alias is present (`keytool -list`), and the password env vars are set. |
| Required hosts reachable | project | TCP connect to every host the lock will fetch from: the runtime and wheel URLs, hosted `.aar`/`.jar` URLs, and — when Maven coordinates are declared — Gradle's own repositories (its defaults plus any the project adds). Derived from `pylock.android.toml`; `path` entries skipped, so a fully vendored lock SKIPs. |
| App-local native binaries | project | Scan `app_dir` for `.so`/`.pyd`/`.dylib`/`.dll`; **FAIL** naming each one and its ELF machine. `app_dir` is staged into the *asset* bundle and unpacked to app-private storage, which Android will not `dlopen` — native code belongs in an Android wheel (`jniLibs/`), whatever its ABI. |
| include_files | project + lock | With a lock present, WARN on drift vs. the locked SHA-256 — a file changed, added, or deleted since `kivyforge lock` — which `kivyforge build` refuses to stage. (The path rules themselves are loader-validated; see **Android config**.) |
| Manifest policy (release) | project | `package`'s preflight, first pass only: kivyforge's own checks over the manifest it *would* generate — exported components explicit and limited to the baseline set (`PythonActivity` + `ProfileInstallReceiver`, plus `manifest.allow_exported`), single `LAUNCHER`, no deep-link conflicts, `debuggable` not forced on, `allowBackup`/cleartext posture, and a non-placeholder (`org.example.*`) `applicationId`. **FAIL** here is what `package` will block on. The merged-manifest pass and the curated `lintRelease` subset need AGP, so `package` stays the gate that sees library manifests. |
| Implied features | project | Advisory (always PASS): names the `android:required="false"` `<uses-feature>` set `auto_features` will synthesize from `permissions.uses`, minus any declared explicitly, so Play device-filtering is visible before upload. SKIP when `auto_features` is off. |

## Version and upgrade policy

Everything the build depends on falls into **three layers**, each upgraded a
different way. kivyforge never blurs them:

### 1. Lock-pinned — `kivyforge lock --update`

The reproducibility surface: the **python.org runtime** (per ABI), all **wheels**
(Kivy, pyjnius, dependencies), every `.aar`/`.jar`, every staged config file, and
the resolved **Maven** graph. All are pinned by content hash in
`pylock.android.toml`, and all but Maven are hash-*verified* at build time (Maven
is Gradle's download and the hash is an audit record — see [pylock-android-spec
§"Gradle/Maven pins"](02-pylock-android-spec.md#toolkivyforgegradle--mavengradle-pins)).
**`kivyforge lock --update` is the single command that re-resolves and re-pins all
of them at once** — new runtime, new wheels, and a freshly resolved Gradle graph —
so the pinned evidence moves together and stays internally consistent. (`kivyforge upgrade`
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
