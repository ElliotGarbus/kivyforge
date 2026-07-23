# Android — Gradle Project Generation

> **Status: design.** The Android analog of [iOS Xcode project generation](../ios/05-xcode-project-generation.md).

This document defines how `kivyforge build` materializes a `pyproject.toml` (with
`[tool.kivy]` + `[tool.kivy.android]`) + `pylock.android.toml` into a working
**Gradle / Android Gradle Plugin (AGP)** project that produces a runnable `.apk`
and a distributable `.aab`. It uses programmatic template generation (not a
cookiecutter dump), and pins the integration with the python.org Android
embeddable package's documented app-integration layout.

## Build process overview

Building an Android app with kivyforge is a four-phase pipeline across two tools:

1. **Collect** (`kivyforge build`) — downloads the python.org Android runtime (per ABI), Android wheels, and `.aar`/`.jar` archives per `pylock.android.toml`. Cached locally.
2. **Stage** (`kivyforge build`) — installs wheels per ABI, lays native `.so`s into `jniLibs/<abi>/`, assembles the pure-Python bundle (byte-compiling/stripping per `build_settings`), generates the manifest + Gradle files + bootstrap sources into an `<app>-android/` project, and copies any `[tool.kivy.android.include_files]` into the tree.
3. **Assemble** (Gradle/AGP) — compiles the thin Java/Kotlin bootstrap, compiles the native launcher (`libmain.so`) from the emitted C sources via the NDK, merges manifests/resources/`.aar`s, packages native libs and the Python asset bundle, and produces a signed `.apk` (`assembleDebug`/`assembleRelease`) or `.aab` (`bundleRelease`).
4. **Sign** (Gradle) — applies the debug or release signing config: an `.apk` is signed with `apksigner` (schemes v1–v4 per the toggles); an `.aab` is JAR-signed (`jarsigner`) with the same key, with the v2–v4 APK schemes applied later to the APKs derived from it (see [signing-prerequisites-android](07-signing-prerequisites-android.md)).

## Project layout

`kivyforge build` produces an `<app>-android/` folder (sibling to `pyproject.toml`):

```
<app>-android/
├── settings.gradle
├── build.gradle                    ← root: plugin versions (AGP, Kotlin if used)
├── gradle.properties               ← managed + [tool.kivy.android.gradle_properties]
├── gradlew, gradlew.bat            ← Gradle wrapper (pinned version)
├── gradle/
│   ├── wrapper/gradle-wrapper.properties
│   └── verification-metadata.xml   ← Gradle artifact SHA-256 verification (materialized from pylock)
├── app/
│   ├── build.gradle                ← applicationId, SDK levels, ABI splits, signing, deps
│   ├── gradle.lockfile             ← per-module Gradle dependency lock (materialized from pylock; only if Maven deps declared)
│   ├── libs/                       ← staged .aar/.jar (channel 3)
│   ├── proguard-rules.pro          ← keep-rules for reflected classes (pyjnius autoclass)
│   └── src/main/
│       ├── AndroidManifest.xml     ← generated from [tool.kivy.android]
│       ├── java/
│       │   ├── org/kivy/android/   ← bootstrap: PythonActivity, PythonService, ...
│       │   ├── org/libsdl/app/     ← SDL Java glue (SDL2 or SDL3 per `sdl`)
│       │   └── org/jnius/          ← NativeInvocationHandler.java (pyjnius matched pair)
│       ├── jniLibs/
│       │   ├── arm64-v8a/          ← libpython, SDL family, wheel .libs/, flattened extension modules
│       │   └── x86_64/
│       ├── assets/
│       │   └── _python_bundle/     ← stdlib + pip-deps + app code (packed asset)
│       ├── cpp/                    ← native launcher: main.c + CMakeLists.txt → libmain.so (NDK-compiled)
│       └── res/                    ← generated icons (mipmap-*), splash theme, strings
├── python-runtime/                 ← extracted python.org runtime, per ABI (staging)
├── pip-deps/                       ← installed wheels, per ABI (staging)
└── app-src/                        ← app_dir staging (symlink on POSIX, junction on Windows, else copy)
```

### Why these folders, not others

- **`app/src/main/jniLibs/<abi>/`** is the only place Android will extract and let a process `dlopen` a native library at runtime. Every `.so` — `libpython3.x.so`, the SDL family, wheel extension modules, and wheel-embedded `.libs/` payloads — must land here (see "Native libraries and the `.so` load model").
- **`app/src/main/assets/_python_bundle/`** holds the pure-Python payload (stdlib, `pip-deps` site-packages, and the app's own code). Assets are packaged **uncompressed** — the toolchain adds the bundle to AGP's `androidResources.noCompress` list (not the default), so first-launch extraction is a straight copy rather than an inflate — and unpacked to app-private storage on first launch by the bootstrap: Python source cannot be imported directly from inside an APK/asset stream, so it is materialized to a real filesystem path.
- **`java/org/kivy/android/` + `java/org/libsdl/app/`** hold the generated bootstrap. The `org.kivy.android.*` namespace is **preserved deliberately** so that `autoclass('org.kivy.android.PythonActivity')` and Plyer-style access keep working unmodified (see [bootstrap-android](05-bootstrap-android.md)).
- **`app/src/main/cpp/`** holds kivyforge's native-launcher source (`main.c` + `CMakeLists.txt`). AGP's `externalNativeBuild` compiles it to `libmain.so` per ABI with the NDK (see "The native launcher (`libmain.so`)"); it is a build output, not a staged/downloaded library.
- **`app-src/`** is an internal staging entry pointing at the user's `app_dir` (e.g. `../src`), so the packed bundle reflects the real source folder without copying `.py` files into the build tree. It is a **symlink on macOS/Linux, a directory junction on Windows** (both privilege-free for a local directory), falling back to a **plain copy** where neither can be created — a restricted Windows host without Developer Mode, or an `app_dir` on a different volume. `kivyforge run` re-packs the bundle every iteration regardless, so the copy fallback costs only a re-pack, not live-edit fidelity. `app_dir` must be a subdirectory (the project root `"."` is rejected), so the link never sweeps `pyproject.toml`/`.git`/build output into the app.
- **`python-runtime/` and `pip-deps/`** are per-ABI *staging* areas that feed `jniLibs/` and the asset bundle; they are not packaged directly.

### Populating `jniLibs/<abi>/`

Three sources feed `jniLibs/<abi>/` at build time:

1. **The python.org runtime** — `libpython3.x.so` and the stdlib C extensions (`lib-dynload`) from the extracted per-ABI embeddable package.
2. **Wheel extension modules** — every `.so` inside each installed Android wheel for that ABI.
3. **Wheel-embedded native libraries** — each `.so` under a wheel's flat top-level `.libs/` directory (the Kivy wheel's SDL family and Kivy's own compiled libs), placed into the ABI folder named by the **wheel's platform tag**. This is the Android analog of the iOS wheel-embedded-`.frameworks/` scan, and mirrors the `auditwheel`/`delvewheel` `<pkg>.libs/` convention. A legacy nested `.libs/<abi>/` is also accepted but its subdirectory must match the wheel tag (drift check, see [artifact-distribution-android](03-artifact-distribution-android.md#the-kivy-wheel-carries-its-native-so-payload-libs)).

All three flow into the same `jniLibs/<abi>/` folder and are packaged by AGP.

#### Duplicate `.so` policy

When two sources contribute a `.so` with the **same basename** for the same ABI,
`kivyforge build` applies the iOS duplicate-framework rule, adapted:

1. **Identical → deduplicate silently.** Same content hash → keep one copy.
2. **Conflicting → fail by default.** Same basename, different content → abort with a diagnostic naming both providers, each library's version/SHA-256, and the colliding filename. kivyforge never picks a winner; a version-mismatched `.so` can link and then crash at runtime, and a build-time failure is strictly better.
3. **No silent "warn and proceed."**

The check runs after all sources are staged and before Gradle is invoked.

## Native libraries and the `.so` load model

Android requires native libraries to be in the APK's native-library directory to
be loadable, and the CPython Android runtime's import machinery must be able to
resolve extension modules from there. kivyforge follows the **python.org Android
embeddable package's documented app-integration layout** — the Android analog of
iOS `install_python`:

- **`android:extractNativeLibs="true"` (and `useLegacyPackaging`).** Managed by the toolchain. It guarantees Android unpacks every `.so` to a real path (`.../lib/<abi>/`) that `dlopen`/`System.loadLibrary` can open — required both for the SDL load order and for Python's `dlopen` of extension modules. (This trades a larger install for correctness; documented and non-negotiable for a Python app.)
- **Two kinds of `.so`, found two different ways.** kivyforge separates native libraries by *how the OS locates them at runtime*:
  - **Shared libraries** resolved by the dynamic linker via soname — `System.loadLibrary(...)` or another library's `DT_NEEDED`: `libpython3.x.so`, the SDL family, Kivy's wheel-vendored `.libs/`, the python.org runtime's bundled external libraries (which python.org names `lib*_python.so`, e.g. OpenSSL). These keep their **soname filename unchanged** and are copied verbatim into `jniLibs/<abi>/`, where the linker's default search path (`nativeLibraryDir`) finds them. (The bootstrap's `libmain.so` is also linker-resolved, but it is **not** staged here — it is compiled from source by the NDK during the Gradle build; see "The native launcher (`libmain.so`)" below.)
  - **Python extension modules** imported by dotted name (`_ssl`, `numpy.core._multiarray_umath`), whose `.so` normally lives at a nested site-packages path. Because `nativeLibraryDir` is a **single flat directory**, `kivyforge build` flattens every extension `.so` — stdlib `lib-dynload` and wheel extensions alike — into `jniLibs/<abi>/` under a **deterministic, collision-free filename**, and records `dotted-module → filename` in a generated manifest shipped in the (ABI-independent) asset bundle. At startup the bootstrap installs a `sys.meta_path` finder built from that manifest, loading each extension from `nativeLibraryDir` (see [bootstrap-android §"Extension-module finder"](05-bootstrap-android.md#extension-module-finder)). This is the Android analog of the iOS `.fwork`/`AppleFrameworkLoader` mechanism.

> **Relationship to python.org's layout.** python.org's [app-integration guide](https://docs.python.org/3/using/android.html) prescribes, for a *single-ABI* app, putting `libpython*.so` + external `lib*_python.so` in the JNI libs and the stdlib (with its `lib-dynload` extension `.so`) in the extracted assets. kivyforge follows that split for the shared libraries, but because it targets **multiple ABIs from one build**, it cannot leave ABI-specific extension `.so` in the shared asset bundle — so it hoists *all* extension modules into ABI-split `jniLibs/<abi>/` and resolves imports through the manifest + finder above. This keeps the asset bundle pure-Python and packaged once (see "The Python asset bundle").

### The native launcher (`libmain.so`)

`libmain.so` is neither downloaded nor wheel-shipped — it is kivyforge's own tiny
C launcher: it provides `SDL_main`, unpacks the asset bundle, and calls
`Py_InitializeFromConfig` (see [bootstrap-android](05-bootstrap-android.md)).
Rather than vendoring a prebuilt binary, `kivyforge build` **emits its C source
plus a `CMakeLists.txt` into `app/src/main/cpp/`** and wires AGP's
`externalNativeBuild { cmake { … } }`, so the **NDK compiles it per ABI during
the Gradle build** and AGP packages the result into `lib/<abi>/` alongside the
staged `.so`s. This is the direct analog of Xcode compiling iOS's `main.m`: the
platform toolchain compiles the bootstrap; kivyforge ships no native binary it
built itself.

- **Version-matched by construction.** The launcher links against the resolved python.org runtime (its `libpython3.x.so` and the matching CPython headers) and the SDL generation selected by `[tool.kivy.android].sdl`, so it always matches the pinned Python minor and SDL — there is **no prebuilt per-(ABI × Python × SDL) matrix** to build, vendor, hash-pin, and keep in sync.
- **NDK is a required prerequisite for every build.** Because the launcher is compiled from source, the NDK is needed for *all* Android builds (debug included), not only symbol-exporting releases. `kivyforge doctor` detects it and prints an install hint but never installs it (the standing toolchain policy). The compile is a single small C file per ABI (seconds).
- **Reproducible.** `kivyforge build` emits a pinned `ndkVersion` into `app/build.gradle`, so the launcher build is deterministic across hosts.

### 16 KB page alignment

Android 15/16 devices with 16 KB memory pages refuse to load 4 KB-aligned `.so`s.
Every native library kivyforge packages must be 16 KB-aligned:

- **Wheels**: built with NDK r28+ / `-Wl,-z,max-page-size=16384` (the pyjnius wheel already is; the locally built Kivy wheel must be too — a wheel-build requirement, see [artifact-distribution-android §"Wheel content rules"](03-artifact-distribution-android.md#wheel-content-rules)).
- **The python.org runtime**: `kivyforge doctor` verifies the extracted runtime `.so`s are 16 KB-aligned and warns if not.
- **The APK**: zip-aligned with 16 KB alignment for uncompressed `.so`s. AGP's packaging + `zipalign -P 16` handles this; the toolchain sets the packaging options accordingly.

`kivyforge doctor` includes a **16 KB alignment check** that scans every staged
`.so`'s LOAD segment alignment and the APK zip alignment, failing loudly rather
than shipping a library that crashes on a 16 KB device.

## The Python asset bundle

The pure-Python payload is assembled into `app/src/main/assets/_python_bundle/`:

- The stdlib pure-Python tree (from the runtime), the `pip-deps` site-packages (pure-Python content of installed wheels), the app's own code (from the `app-src/` staging link), and the generated extension-module manifest (`dotted-module → jniLibs filename`) the bootstrap finder consumes.
- **ABI-independent by construction, and verified so.** Every ABI-specific `.so` is pulled into `jniLibs/<abi>/` (above), leaving only ABI-neutral content in the bundle. Since each ABI's wheels are installed into a *separate* per-ABI staging tree, `kivyforge build` assembles the single bundle from one **canonical ABI** (the first entry in `abis`) and then asserts the non-`.so` payload of every other ABI slice is **byte-for-byte identical** to it (per-file SHA-256). A divergence — an ABI slice shipping different Python source or data at the same version — fails the build naming the path and the two hashes, rather than silently shipping one ABI's Python to both. (Version skew across ABIs is already rejected at lock time; this catches content skew.)
- On first launch the bootstrap unpacks it to app-private storage (`getFilesDir()`), version-stamped so an app update re-extracts. `PYTHONHOME`/`PYTHONPATH` point at the extracted location; `pip-deps` is registered via `site.addsitedir()` (not bare `PYTHONPATH`) so `.pth` files work — the same rule as the iOS bootstrap.

### Byte-compilation and size (`build_settings`)

Per [`[tool.kivy.android.build_settings]`](01-pyproject-android.md#toolkivyandroidbuild_settings), the Stage step can shrink the bundle:

- **`byte_compile`** (default: release-only) — compiles the entire Python payload to `.pyc` using the **target's own 3.14** at the right optimization level, so the emitted magic number matches the shipped `libpython3.14.so`. Debug builds keep `.py` for readable tracebacks and fast `kivyforge run` iteration.
- **`strip_source`** (default: release-only) — when byte-compiling, drops the paired `.py`, roughly halving the payload. Tracebacks still show file/line via the `.pyc` line table; only source text is unavailable.
- **`strip_native_libs`** (default: release-only) — strips debug symbols from the shipped `.so`s (runtime + wheel extensions + wheel `.libs/`). This is done by **AGP** during packaging (via `packagingOptions.jniLibs.keepDebugSymbols`), not a bespoke kivyforge strip pass, so it tracks the toolchain and preserves 16 KB alignment. Debug keeps symbols in place. See **Native debug symbols** below for retaining the stripped symbols.

Stdlib module *pruning* is intentionally not a build knob here — it is unsafe under pyjnius/`importlib` dynamic imports. Prune deliberately through the resolution-graph `exclude` field and test the app.

## `app/build.gradle` — the generated module

`kivyforge build` generates `app/build.gradle` with, on every build:

- `applicationId` = `[tool.kivy.android].package`; `versionName` = `[project].version`; `versionCode` = `[tool.kivy.android].version_code` (or the value derived from `[project].version` + `build` when it is `"auto"`, see [pyproject-android §"Auto-derived `version_code`"](01-pyproject-android.md#auto-derived-version_code)); `minSdk`/`targetSdk`/`compileSdk`.
- **ABI filters** = `[tool.kivy.android].abis` (mapped to Android's `arm64-v8a`/`x86_64` names), plus per-ABI splits for the `.apk` and full ABI set for the `.aab`.
- **Signing configs**: a `debug` config (Android debug keystore) and, when `[tool.kivy.android.signing]` is present, a `release` config reading the keystore + alias and the passwords from the configured env vars. The v1–v4 toggles apply to `.apk` outputs (`apksigner`); an `.aab` is JAR-signed with the same key (the schemes then apply to the APKs Play/`bundletool` derive from it).
- **Dependencies**: `files(...)` entries for staged `libs/*.aar|*.jar` (channel 3) and `implementation` lines for `[tool.kivy.android.gradle].dependencies` (channel 4). Gradle dependency locking **and** artifact verification are enabled, and `kivyforge build` **materializes both `app/gradle.lockfile` (Gradle's per-module lock location) and `gradle/verification-metadata.xml` into the project from the resolved graph embedded in `pylock.android.toml`** (`[[tool.kivyforge.gradle.resolved]]`) — the reproducibility data is committed in the lock, never inside the disposable project (see [pylock-android-spec §"Gradle/Maven pins"](02-pylock-android-spec.md#toolkivyforgegradle--mavengradle-pins)).
- **Native launcher build**: `externalNativeBuild { cmake { path "src/main/cpp/CMakeLists.txt" } }` plus a pinned `ndkVersion`, so the NDK compiles the emitted launcher C into `libmain.so` per ABI (see "The native launcher (`libmain.so`)").
- **Packaging options**: `jniLibs { useLegacyPackaging = true }` and the 16 KB packaging alignment; `jniLibs.keepDebugSymbols` is set from `[tool.kivy.android.build_settings].strip_native_libs` (kept for debug / when stripping is off, dropped for a stripped release).
- **Native debug symbols**: for a stripped release, `buildTypes.release.ndk.debugSymbolLevel` is emitted from `[tool.kivy.android.build_settings].debug_symbols` (`SYMBOL_TABLE` / `FULL`), so AGP exports a `native-debug-symbols.zip` for crash symbolication (see below).
- **R8/minify** posture from `[tool.kivy.android.build_settings]` (off by default), wiring `proguard-rules.pro` with keep-rules for the bootstrap and reflected classes when enabled.
- Kotlin plugin applied only when `[tool.kivy.android.src].kotlin` is non-empty.

## Manifest generation

`AndroidManifest.xml` is generated from `[tool.kivy.android]`:

- The main `<activity>` is the generated `org.kivy.android.PythonActivity`, marked `LAUNCHER`, with `android:screenOrientation` from `[tool.kivy].orientation`, any `[tool.kivy.android.intent_filters]`, and any `manifest.extra_activity_xml`.
- `<uses-permission>` from `[tool.kivy.android.permissions].uses` (bare names auto-prefixed with `android.permission.`); **nothing is force-added** — the only implicit permissions are the `FOREGROUND_SERVICE*` entries a declared foreground service requires.
- `<uses-feature>` from `[tool.kivy.android.permissions].features`, **plus** the non-required implied features synthesized from hardware-implying permissions when `auto_features` is on (an explicit `features` entry overrides the synthesized one for the same feature). See [pyproject-android §"Implied hardware features"](01-pyproject-android.md#implied-hardware-features-auto_features).
- Extra `<service>` / `<activity>` from `[tool.kivy.android.services]` / `.activities`. A `foreground` service emits `android:foregroundServiceType` and auto-adds `FOREGROUND_SERVICE` + the matching `FOREGROUND_SERVICE_<TYPE>` `<uses-permission>`; its `notification` config is compiled into the generated `PythonService` (see [bootstrap-android](05-bootstrap-android.md)).
- `<application>` / `<activity>` attribute passthrough + `manifestPlaceholders` from `[tool.kivy.android.manifest]`, with kivyforge-managed attributes rejected if overridden (see [pyproject-android §"Manifest keys kivyforge manages"](01-pyproject-android.md#manifest-keys-kivyforge-manages)).
- **Raw-XML fragments** from `manifest.extra_manifest_xml` (children of `<manifest>`, e.g. `<queries>`) and `manifest.extra_application_xml` (children of `<application>`, e.g. `<receiver>`/`<provider>`) injected verbatim after `${applicationId}`/placeholder substitution. Each fragment is parsed for well-formedness first; a malformed fragment fails the build with the XML error rather than letting AGP's manifest merger fail cryptically later.

> **Release manifest policy is preflighted.** Raw XML and attribute passthrough make it possible to ship a footgun (an accidentally exported component, a `debuggable`/cleartext release, the `org.example.*` placeholder). `kivyforge package` lints the *merged* release manifest — a curated Android `lintRelease` subset plus kivyforge checks — and **fails before signing** on a policy violation. See [cli-android §`kivyforge package`](06-cli-android.md#kivyforge-package) and the `doctor` "Manifest policy (release)" check.

### Theme and splash resources

`kivyforge build` generates the app's `res/values/styles.xml` and splash theme
from `[tool.kivy.android].base_theme` + `[tool.kivy.android.splash]`:

- The app `<style>`'s `parent=` is `base_theme` (default: a `Theme.Material3.DayNight.NoActionBar`-family theme); this theme is the `android:theme` for the `<application>` and main activity.
- The splash is wired through the **AndroidX core SplashScreen API** — the splash `<style>` sets `windowSplashScreenBackground` (`background`), `windowSplashScreenAnimatedIcon` (`source` — a static PNG *or* an AnimatedVectorDrawable), `windowSplashScreenIconBackgroundColor` (`icon_background`), `windowSplashScreenAnimationDuration` (`animation_duration`), and `windowSplashScreenBrandingImage` (`branding`). An animated splash therefore needs **no third-party dependency**; it is the platform mechanism. The `core-splashscreen` AndroidX library is added to `app/build.gradle` automatically when a splash is configured.

### File injection (`include_files`)

After the manifest and Gradle files are generated, `kivyforge build` copies each
`[[tool.kivy.android.include_files]]` entry — `sources` (repo-relative files or
directories) into `dest` (relative to `<app>-android/`) — so config files like
`app/google-services.json` or `app/src/main/res/xml/network_security_config.xml`
are present before Gradle runs. A copy that would clobber a kivyforge-generated
file is rejected; sources are SHA-256-pinned in the lock for drift detection.

## Developer iteration workflow

The mental model mirrors iOS: **`pyproject.toml` describes the *shape* of your
app; your Python files are the *content*.**

| Change | Command to run |
|--------|----------------|
| Edit a `.py` file under `app_dir` | `kivyforge run` (re-packs the bundle + reinstalls) |
| Add a `.py`/asset under `app_dir` | `kivyforge run` |
| **Any edit to `pyproject.toml`** | `kivyforge lock && kivyforge build` |

Unlike Xcode's folder-reference live-edit, an Android `.py` change requires
re-packing the asset bundle and reinstalling the APK — `kivyforge run` does this
in one step. `<app>-android/` is fully `.gitignore`-able (regenerable);
`pylock.android.toml` and the vendored `wheels/` are committed.

## Information flow

```
pyproject.toml ([project] + [tool.kivy.*])
        │
        ▼
   kivyforge lock ─────────────► PyPI / python.org / Maven  (resolve only)
        │
        ▼
pylock.android.toml (PEP 751 + [tool.kivyforge])
        │
        ▼                        download / cache
   kivyforge build ────────────► ┌───────────────┐◄── python.org (runtime, per ABI)
        │                         │               │◄── PyPI / find_links (wheels)
        │                         │               │◄── URLs / repo (.aar/.jar)
        │                         └──────┬────────┘
        │                                │
        ├── install wheels per ABI ──────┤
        ├── .so → jniLibs/<abi>/          │
        ├── pure-Python → assets bundle   │
        ├── generate manifest + gradle    │
        └── generate bootstrap sources    │
        │
        ▼
     gradlew assembleRelease / bundleRelease
        │
        ▼
   signed <app>.apk / <app>.aab
```

## Generated file inventory (per project)

| File | Source | Regenerated by `kivyforge build`? |
|------|--------|-----------------------------------|
| `settings.gradle`, root `build.gradle` | templates | One-time |
| `gradlew`/`gradlew.bat`, `gradle/wrapper/*` | pinned Gradle wrapper | One-time |
| `app/build.gradle` | template + `[tool.kivy.android]` | Yes (idempotent) |
| `AndroidManifest.xml` | template + `[tool.kivy.android]` | Yes |
| `java/org/kivy/android/*`, `java/org/libsdl/app/*`, `java/org/jnius/*` | bootstrap templates (per `sdl`) | Yes |
| `cpp/main.c`, `cpp/CMakeLists.txt` | native-launcher template (compiled to `libmain.so` by the NDK) | Yes |
| `app/src/androidTest/*` | generated contract smoke test (launch + extension import + pyjnius proxy; drives the bootstrap self-test hook) | Yes |
| `res/mipmap-*`, `res/values/styles.xml` (theme + splash) | `[tool.kivy.android.icons]` / `.splash]` / `base_theme` | Yes |
| `jniLibs/<abi>/*.so` | runtime + wheel `.so`s + wheel `.libs/` (ABI from wheel tag; stripped per `strip_native_libs`) | Yes (cache-hit-able) |
| `assets/_python_bundle/` | stdlib + pip-deps + app code (byte-compiled per `build_settings`) | Yes |
| `app/gradle.lockfile`, `gradle/verification-metadata.xml` | materialized from `[[tool.kivyforge.gradle.resolved]]` in the lock | Yes (at build) |
| user-supplied config files | `[tool.kivy.android.include_files]` | Yes (copied) |
| `app-src/` | link (symlink/junction) or copy of `app_dir` | Yes |

## Idempotency

Re-running `kivyforge build` produces the same project content. Generated Gradle/
manifest files are emitted deterministically (sorted dependency/permission lists,
stable attribute order) to minimize diff churn.

## Project ownership (managed / regenerated)

`<app>-android/` is a **managed, regenerated artifact — not source you maintain.**
Every `kivyforge build` re-derives it in full from `pyproject.toml` +
`pylock.android.toml` (the "continuous native generation" model also used by Expo
prebuild and `flutter create`). It is fully `.gitignore`-able and reproducible on
any host; you commit `pyproject.toml`, `pylock.android.toml`, and any vendored
`wheels/` — **not** the generated project. This matches iOS, where the generated
Xcode project is likewise authoritative-by-regeneration.

Consequences:

- **Hand edits to generated files** (`app/build.gradle`, `AndroidManifest.xml`, the bootstrap Java, `res/values/styles.xml`, …) are **overwritten** on the next build. Customize through the sanctioned escape hatches instead — the manifest passthrough + raw XML, `gradle` repositories/dependencies, `native.aars`/`native.jars`, `src.java`/`src.kotlin`, `include_files`, `gradle_properties`, and `build_settings` — which cover the customization surface *without* forfeiting regeneration.
- **There is no supported "eject" verb.** If the escape hatches don't cover a need, that's a design gap to report, not something to patch in the generated tree. You can of course copy `<app>-android/` elsewhere and maintain it by hand as a plain Gradle project, but then you own it entirely: kivyforge no longer regenerates it, re-locks into it, or supports it, and the reproducible-from-source guarantee no longer holds. Keeping the project managed is strongly preferred.

## Final artifacts

- **`.apk`** (`package -f apk` for a signed release, or `build --debug` for a debug build) — the sideload/CI unit; both the runnable artifact and the installable unit.
- **`.aab`** (`package -f aab`) — the Play upload unit; Play generates per-device APKs and (with Play App Signing) re-signs with the app key.
- **`native-debug-symbols.zip`** (stripped release only) — the native debug symbols for crash symbolication, under `app/build/outputs/native-debug-symbols/release/`, controlled by `[tool.kivy.android.build_settings].debug_symbols`. The Android analog of the iOS `.xcarchive/dSYMs/`; upload to Play or a third-party crash reporter. See [pyproject-android §"Native debug symbols"](01-pyproject-android.md#native-debug-symbols).

The `.apk`/`.aab` are produced under `<app>-android/app/build/outputs/`. See
[cli-android](06-cli-android.md) for the verb/flag mapping and
[common packaging scope](../../common/06-packaging-scope.md) for the
artifact-vs-store-submission boundary.
