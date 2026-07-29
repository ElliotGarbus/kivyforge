# Android — `[tool.kivy.android]` Overlay Schema

> **Status: implemented (v1).** The Android backend is built and validated
> end-to-end — `init` → `lock` → `build` → `run` → `run --smoke` → `package`
> all pass on the Windows-host x86_64 emulator with a live Kivy 2.3.1 app +
> pyjnius bridge (see the [load-model findings](../../dev/android-loadmodel-findings.md)
> for the on-device gates). This document is the normative overlay spec; the
> empirical basis for the wheel-assembly bet is the pyjnius Android-wheel spike
> (findings:
> [dev/pyjnius-android-wheel-spike-findings](../../dev/pyjnius-android-wheel-spike-findings.md);
> pre-spike brief: [dev/pyjnius-android-wheel-spike](../../dev/pyjnius-android-wheel-spike.md);
> Phase-0 context: [dev/android-wheels-findings](../../dev/android-wheels-findings.md)).
>
> **Realized vs designed (v1).** The whole schema is implemented and loader-
> validated (rules 1–21). Deviations recorded during the build:
> - **Kivy-compatibility bootstrap surface** — the generated bootstrap must also
>   ship `org.renpy.android.Hardware` + `PythonActivity.mActivity` (Kivy's own
>   `metrics.py` autoclasses them); the namespace-preservation section (05) is
>   extended accordingly.
> - **Entry point is *imported*** — an app must call `App().run()` at module top
>   level, not under `if __name__ == "__main__"` (a buildozer→kivyforge trap).
> - **Gradle/Maven verification is scoped in v1** — the resolved graph + per-
>   artifact SHA-256 is committed in `pylock.android.toml` (the audit record),
>   but Gradle-*enforced* `verification-metadata.xml` is deferred (it requires
>   pinning the entire AGP build classpath, not just the app's Maven deps). See
>   [02 §Gradle pins](02-pylock-android-spec.md#toolkivyforgegradle--mavengradle-pins).
> - **Both Android wheels are first-party.** Kivy and pyjnius are built with
>   cibuildwheel, 16 KB-aligned, and served from the
>   [`kivy-mobile-wheels`](https://github.com/ElliotGarbus/kivy-mobile-wheels)
>   release index (`doctor`'s 16 KB check PASSes on a project staged from them).
>   They are not on PyPI yet, which is why examples add the index through
>   `extra_index_urls`; see [03 §wheel sources](03-artifact-distribution-android.md).

This document defines the **Android-specific overlay** in `pyproject.toml`: the
`[tool.kivy.android]` table and its subtables. It layers on top of the shared
`[project]` + `[tool.kivy]` tables and the overlay pattern described in the
[common pyproject spec](../../common/01-pyproject-kivy-spec.md).

`[tool.kivy.android]` is an **additive overlay**: it only contains keys whose
value must differ from the cross-platform default in `[tool.kivy]`, or keys that
are Android-only (e.g. `package`, `permissions`, `signing.keystore`). Everything
inside it is consumed only by kivyforge's Android backend.

Companion Android documents:

- [pylock-android-spec](02-pylock-android-spec.md) — the `pylock.android.toml` schema.
- [artifact-distribution-android](03-artifact-distribution-android.md) — wheels, the python.org runtime, `.aar`/`.jar`, and Gradle/Maven dependencies.
- [gradle-project-generation](04-gradle-project-generation.md) — the generated Gradle/AGP project and how config flows into it.
- [bootstrap-android](05-bootstrap-android.md) — the Activity → Python bootstrap and the pyjnius/SDL runtime contract.
- [cli-android](06-cli-android.md) — per-verb behavior and `doctor` checks.
- [signing-prerequisites-android](07-signing-prerequisites-android.md) — the keystore/`apksigner` setup checklist.

## `[project]` (PEP 621) — Android consumption

kivyforge's Android backend consumes the following PEP 621 keys directly; the rest are passed through where Android exposes a slot for them.

| PEP 621 key              | Android use                                                                                                                                                                                                                                 | Required |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `name`                   | Standard PEP 621 distribution name (may contain hyphens, dots, or underscores per PEP 503). Used as the Gradle **root-project name** (`settings.gradle`) and the `<app>-android/` file slug — kivyforge normalizes it as needed; the application module itself is always `app/` — and, when `[tool.kivy].display_name` is absent, as the launcher label (`android:label`). Not required to be a valid Python identifier; that constraint applies only to `entry_point`. | yes |
| `version`                | `versionName` (marketing version shown to users).                                                                                                                                                                                            | yes |
| `description`            | Store metadata only; not written into the manifest.                                                                                                                                                                                          | no |
| `requires-python`        | Cross-checked against `[tool.kivy.android.python].version` to fail fast on impossible combinations (e.g. `requires-python = ">=3.16"` with `version = "3.14.6"`).                                                                            | no, but warned on mismatch |
| `dependencies`           | The full Python dependency set (PEP 508 strings, including environment markers). `kivyforge lock` evaluates markers against the Android target and resolves the matching subset to per-ABI wheels in `pylock.android.toml`.                   | yes (may be empty) |
| `optional-dependencies`  | Ignored by the Android backend unless the user opts in per-extra via a future `[tool.kivy.android].extras` allowlist.                                                                                                                        | no |
| `authors`, `maintainers` | First `authors` entry populates store metadata; not written into the manifest.                                                                                                                                                              | no |

## Icons and splash screens

Icons and splash screens are platform-specific. Android uses **adaptive icons**
(a foreground + background layer, per [Android adaptive icons](https://developer.android.com/develop/ui/views/launch/icon_design_adaptive))
and the **platform splash screen** — the system splash window on API 31+, which
supports a static or **animated** (AnimatedVectorDrawable) icon natively, with no
extra dependency and no code in the activity. Each is declared in its own
subtable. If `[tool.kivy.android.icons]`
or `[tool.kivy.android.splash]` is absent, kivyforge emits a plain default
launcher icon / no custom splash. The overall app theme (the splash's parent and
the window backdrop) is set by [`[tool.kivy.android].base_theme`](#toolkivyandroid).

### `[tool.kivy.android.icons]`

```toml
[tool.kivy.android.icons]
source = "assets/icon-android.png"        # 1024×1024 PNG; used as the adaptive foreground
background = "#ffffff"                     # adaptive-icon background (color or image path)
monochrome = "assets/icon-mono.png"        # optional; Android 13+ themed icon
```

| Field        | Type   | Required | Description                                                                                                                                                        |
| ------------ | ------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `source`     | string | no       | Path to a 1024×1024 source PNG relative to `pyproject.toml`. `kivyforge build` generates the full adaptive-icon density set (`mipmap-*`) plus the `ic_launcher` foreground. |
| `background` | string | no       | Hex color (`#rrggbb`) or an image path for the adaptive-icon background layer. Defaults to white when a `source` is set and no background is given.                 |
| `monochrome` | string | no       | Optional monochrome layer for Android 13+ themed icons.                                                                                                             |

### `[tool.kivy.android.splash]`

The splash screen is the **platform's own**, whose model is a *centered icon on a
background* (optionally animated) — not a full-bleed image. Every field below
maps directly to a `windowSplashScreen*` theme attribute emitted into
`values-v31/`, so an animated splash is expressed with the platform's own
mechanism, with **no runtime dependency** and no `installSplashScreen()` call in
the load-order-sensitive part of the activity.

Because those attributes only exist from API 31, `kivyforge build` also generates
a `windowBackground` layer-list (the same background color with the same icon
centered on it) into the base theme. That layer covers two gaps: on API 24–30
there is no system splash at all, and on *every* API level it is what the window
shows between the system splash handing off and Kivy drawing its first frame —
which for a cold start (unpack the bundle, boot CPython) is seconds of otherwise
blank window. `animation_duration` and `branding` are API 31 concepts and are
inert below it; the icon is static there.

A configured splash requires `compile_sdk >= 31`, since AAPT resolves attribute
names against the compile SDK regardless of which `values-*` folder they sit in.

```toml
[tool.kivy.android.splash]
source = "assets/splash-icon.png"    # centered icon: a PNG, or an AnimatedVectorDrawable XML for an animated splash
background = "#000000"               # splash window background color
icon_background = "#ffffff"          # optional color disc behind the icon
animation_duration = 800             # ms; only meaningful when `source` is an AnimatedVectorDrawable
branding = "assets/branding.png"     # optional bottom branding image
```

| Field                | Type    | Required | Description                                                                                                                                                                 |
| -------------------- | ------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `source`             | string  | no       | The centered splash icon → `windowSplashScreenAnimatedIcon`. A raster **PNG** is scaled into the platform's guaranteed-visible inner box (192dp of a 288dp canvas, or 160dp of 240dp when `icon_background` is set) and emitted per density; an **AnimatedVectorDrawable** XML is passed through untouched and animated natively. |
| `background`         | string  | no       | Hex color (`#rrggbb`) for the splash window background → `windowSplashScreenBackground`. Defaults to white when a `source` is set and no background is given.                 |
| `icon_background`    | string  | no       | Optional hex color for the circular backdrop behind the icon → `windowSplashScreenIconBackgroundColor`.                                                                     |
| `animation_duration` | integer | no       | Animation length in **milliseconds** for an animated `source` → `windowSplashScreenAnimationDuration`. Ignored for a static PNG. Must be a positive integer.                |
| `branding`           | string  | no       | Optional image shown at the bottom of the splash → `windowSplashScreenBrandingImage`.                                                                                       |

## `[tool.kivy.android]`

Android-specific overlay. Every field below applies to Android only.

```toml
[tool.kivy.android]
schema_version = 1
package = "org.example.myapp"
version_code = 1
min_sdk = 24
target_sdk = 35
compile_sdk = 35
kivy_generation = 2
abis = ["arm64_v8a", "x86_64"]
```

| Field            | Type           | Required | Default                    | Description                                                                                                                                                                                                                                                                                                            |
| ---------------- | -------------- | -------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version` | integer        | yes      | —                          | Declares the major version of the Android schema this table targets. `kivyforge` refuses to operate on a value higher than it understands, with a clear "upgrade kivyforge" error. Independent of other platforms' overlay schema versions.                                                                             |
| `package`        | string         | yes      | —                          | The Android **application id** (reverse-DNS, e.g. `org.example.myapp`). Written as `applicationId` in `app/build.gradle` and the manifest `package`. Init suggests `org.example.<slug>` with a comment to change it. Must be a valid Android package name (≥ 2 dot-separated segments, each a Java identifier).           |
| `version_code`   | integer or `"auto"` | no  | `1`                        | Monotonic integer `versionCode` (the Play Store ordering key), distinct from `[project].version` (the human `versionName`). An explicit integer is used verbatim (increment it per upload). The string `"auto"` **derives** the code from `[project].version` + `build` — see ["Auto-derived `version_code`"](#auto-derived-version_code) — so you bump one human version and never hand-manage the code.                                                          |
| `build`          | integer        | no       | `0`                        | Build counter, used **only** when `version_code = "auto"`: bump it to re-upload the *same* `[project].version` (e.g. a store-rejected re-submit or a hotfix rebuild). Ignored when `version_code` is an explicit integer. Range `0`–`99`. See ["Auto-derived `version_code`"](#auto-derived-version_code).                 |
| `min_sdk`        | integer        | no       | `24`                       | `minSdkVersion`. **Floored at 24** — the first API level with RUNPATH (auditwheel's requirement for grafted `.so`s) and ~99% device coverage; also the floor the python.org Android runtime and the Android wheel tag ecosystem target. Rejected below 24 (see validation rules).                                       |
| `target_sdk`     | integer        | no       | latest known stable        | `targetSdkVersion`. Init pins the latest stable API level kivyforge knows. Google Play enforces a moving `targetSdk` floor for new uploads.                                                                                                                                                                             |
| `compile_sdk`    | integer        | no       | `= target_sdk`             | `compileSdkVersion`. Must be ≥ `target_sdk`.                                                                                                                                                                                                                                                                            |
| `kivy_generation` | integer       | no       | `2`                        | Which **Kivy major generation** the bootstrap and native runtime target: `2` (Kivy 2.3.1) or `3` (Kivy 3.0). Named after the Kivy version, not the SDL generation it happens to pair with — it selects the SDL Java glue and the SDL native-library soname the pyjnius runtime resolver / load order expects, but configuring a build never requires knowing that pairing. See ["Kivy generation (`kivy_generation`)"](#kivy-generation-kivy_generation) below and [bootstrap-android](05-bootstrap-android.md).                    |
| `abis`           | list of string | no       | `["arm64_v8a", "x86_64"]`  | Which Android ABIs `kivyforge lock` pins and `kivyforge build` packages. **64-bit only** — the python.org Android runtime does not ship 32-bit builds, so `armeabi_v7a` and `x86` are rejected. `arm64_v8a` is the real-device shipping target; `x86_64` is the emulator/CI testability ABI. See "ABIs (`abis`)" below.  |
| `extra_index_urls` | list of string | no     | `[]`                       | Supplemental pip index URLs consulted *in addition to* PyPI when resolving Android wheels. `kivyforge lock` passes each as `--extra-index-url`. Empty by default; PyPI is always primary. Each resolved wheel's source URL is pinned in `pylock.android.toml`. Mirrors the iOS field. |
| `find_links`     | list of string | no       | `[]`                       | Repo-relative directories of pre-built Android wheels consulted during `kivyforge lock` only (passed to pip as `--find-links`). Use when a dependency's Android wheels are vendored in the repo — **the canonical case is a locally cross-built `kivy` 2.3.1 wheel** (see "Local wheel directories" below). Entries must be repo-relative and must not escape the project directory. |
| `exclude`        | list of string | no       | `[]`                       | Canonical package names to drop from the **resolved** dependency graph when writing `pylock.android.toml`. Same semantics as the iOS field — prune the transitive tail a dependency declares but your app never exercises on Android. A name that is also a direct `[project].dependencies` entry is silently ignored.   |
| `base_theme`     | string         | no       | Material3 DayNight (NoActionBar) | Parent Android theme for the app: written as the `parent=` of the generated app `<style>` and used as the `<application>`/main-activity `android:theme` (and the splash's parent). Defaults to a `Theme.Material3.DayNight.NoActionBar`-family theme suited to a full-screen SDL surface. Set it to another Material/AppCompat base or a custom parent you supply via app resources / `include_files`. Validated as a non-empty string; a parent that doesn't resolve surfaces as a Gradle/AAPT error at build time. |

### Auto-derived `version_code`

`versionCode` is the integer Google Play uses to order releases; a new upload must
always have a strictly higher value than the last, and hand-maintaining it
alongside the human `[project].version` is the single most common source of "you
uploaded a code that's already used / not higher" store rejections. Setting
`version_code = "auto"` lets kivyforge derive it, Briefcase-style, from the version
you already bump:

```toml
[tool.kivy.android]
version_code = "auto"
build = 0            # bump only to re-upload the SAME [project].version
```

**Formula.** With `[project].version = "MAJOR.MINOR.PATCH"`:

```
version_code = MAJOR*1_000_000 + MINOR*10_000 + PATCH*100 + build
```

Each of `MINOR`, `PATCH`, and `build` occupies two decimal digits (range `0`–`99`);
`MAJOR` takes the high digits. The result is strictly increasing under normal
PEP 440 version ordering, and is validated to stay under **Google Play's
`2,100,000,000` ceiling** — which the formula guarantees for `MAJOR ≤ 2099`.
Examples: `1.0.0` → `1_000_000`; `1.2.3` → `1_020_300`; `1.2.3` with `build = 4` →
`1_020_304`; `2.0.0` → `2_000_000`.

**Constraints (enforced at lock/build; see validation rules).** In `"auto"` mode:

- `[project].version` must be a **final release** `MAJOR.MINOR.PATCH`. Pre-release,
  dev, post, local, and epoch versions (`1.2.0rc1`, `1.2.0.dev3`, `1.2+local`,
  `1!2.3.0`) are rejected — they have no monotonic integer mapping. Use an explicit
  integer `version_code` for those.
- A missing `PATCH`/`MINOR` is treated as `0` (`1.2` → `1.2.0`); a **fourth**
  numeric segment (`1.2.3.4`) is rejected — express the extra increment via `build`.
- `MINOR`, `PATCH`, and `build` must each be `≤ 99`, and the derived code must not
  exceed `2,100,000,000`; overflow fails the build with the offending value.

The default remains a plain integer, so anyone who wants full manual control (or a
non-derivable scheme) simply sets `version_code` to a number and ignores `build`.

### Kivy generation (`kivy_generation`)

Kivy on Android is delivered as an SDL app, and the SDL major version it uses is a
**whole-stack decision**, not a per-package one:

- **`kivy_generation = 2`** targets **Kivy 2.3.1**, which is an SDL2 framework. The
  bootstrap emits the SDL2 Java glue (`org.libsdl.app.*` at the SDL2 revision) and
  loads `libSDL2.so`; the pyjnius runtime resolver finds the `JNIEnv` via SDL2's
  `SDL_AndroidGetJNIEnv`.
- **`kivy_generation = 3`** targets **Kivy 3.0**, an SDL3 framework. The bootstrap
  emits the SDL3 Java glue and loads `libSDL3.so`; pyjnius resolves via SDL3's
  `SDL_GetAndroidJNIEnv`.

The **same pyjnius wheel serves both** — it carries no `DT_NEEDED` on any
`libSDL` and resolves the getter at runtime by soname (per the
[spike findings](../../dev/pyjnius-android-wheel-spike-findings.md)). Only the bootstrap's SDL Java glue and the SDL native `.so` differ between
generations, which is exactly what `kivy_generation` selects. `kivyforge init`
sets `kivy_generation` based on the Kivy version it seeds; changing your `kivy`
pin across the 2→3 boundary means flipping `kivy_generation` and re-locking. The
supported CPython/Kivy/SDL/pyjnius/ABI/minSdk combinations and their validation
status are tabulated in the [compatibility matrix](08-compatibility-matrix.md).
See [bootstrap-android §"SDL generation and the pyjnius contract"](05-bootstrap-android.md#sdl-generation-and-the-pyjnius-contract).

> **Why an explicit key rather than inferring it from the `kivy` version?** The
> bootstrap is generated *before* wheels are installed, and the SDL generation it
> emits governs Java sources and native load order that must be fixed at project-
> generation time. An explicit key keeps that decision declarative and auditable,
> and lets a non-Kivy SDL app (or a forked Kivy) state its generation directly.
> `kivyforge doctor` warns if `kivy_generation` and the resolved `kivy` version
> disagree (SDL2 Kivy is `< 3.0`; SDL3 Kivy is `>= 3.0`).
>
> **Why `kivy_generation` and not `sdl`?** The key is named after what you're
> actually choosing — which Kivy major version to build — not the windowing
> library that version happens to be built on. kivyforge translates that choice
> into the matching SDL generation internally; configuring a build should never
> require knowing that Kivy 2.x pairs with SDL2 and Kivy 3.x pairs with SDL3.

### ABIs (`abis`)

An Android app can ship native code for multiple CPU ABIs in one APK/AAB. A
compiled Python wheel ships a separate wheel per ABI, tagged
`android_<api>_<abi>` (e.g. `android_24_arm64_v8a`). `abis` controls which ABIs
`kivyforge lock` resolves and pins and which `kivyforge build` packages.

The default, `["arm64_v8a", "x86_64"]`, pins both 64-bit ABIs so the committed
`pylock.android.toml` is reproducible and testable on any host:

- **`arm64_v8a`** is the real-device shipping target (essentially all modern
  Android hardware is arm64).
- **`x86_64`** is the emulator/CI testability ABI: the fast, KVM/HAXM-accelerated
  emulator on an x86_64 build host runs the `x86_64` slice near-native, so it is
  the one you can load and smoke-test at speed. (On an **arm64 host** — e.g.
  Apple Silicon — the emulator runs `arm64-v8a` system images natively instead,
  and the shipping ABI doubles as the emulator ABI. The emulator ABI is always
  the *host's* architecture, which is why the default pins both.)

```toml
[tool.kivy.android]
# Ship arm64 only (smaller AAB); drop the x86_64 emulator slice.
abis = ["arm64_v8a"]
```

**32-bit is out of scope, permanently for this schema.** The python.org Android
embeddable package publishes only `aarch64` and `x86_64` runtimes; there is no
32-bit CPython Android artifact to consume, so `armeabi_v7a` and `x86` are
rejected at validation. This is a hard consequence of the runtime source (see
[artifact-distribution-android §"Distribution channel 2"](03-artifact-distribution-android.md#distribution-channel-2-the-pythonorg-android-runtime)), not a deferral.

### Excluding unused transitive dependencies (`exclude`)

Identical in mechanism and rationale to the [iOS `exclude` field](../ios/01-pyproject-ios.md#excluding-unused-transitive-dependencies-exclude): resolution-graph pruning (not per-file bundle exclusion), direct deps always win, canonical-name matching. `kivyforge init` seeds a documented block when `kivy` is a direct dependency (e.g. `kivy-garden`, `docutils`, `pygments` — features a bundled app can't use).

### Local wheel directories (`find_links`)

`[project].dependencies` stays PEP 508 only. When an Android wheel is vendored
locally, `find_links` tells pip where to *search* during `kivyforge lock`, and
each resolved slice is pinned in `pylock.android.toml` as `url` or repo-relative
`path` (per PEP 751). `kivyforge build` installs from those pins; it does not
re-read `find_links`.

The **canonical Android case** is vendoring a locally cross-built **Kivy 2.3.1**
wheel (and, until it lands on PyPI, the **pyjnius** wheel). kivyforge deliberately
does **not** depend on any community wheel channel; you build these wheels
out-of-band with `cibuildwheel` and commit them to the repo:

```toml
[project]
dependencies = ["kivy==2.3.1", "pyjnius"]

[tool.kivy.android]
kivy_generation = 2
find_links = ["wheels"]     # locally cross-built kivy + pyjnius android_24_* wheels
```

After `kivyforge lock`, `pylock.android.toml` holds per-ABI entries such as:

```toml
[[packages.wheels]]
name = "Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl"
path = "wheels/Kivy-2.3.1-cp314-cp314-android_24_arm64_v8a.whl"
hashes = { sha256 = "..." }
```

A wheel's tag API level is a **floor** (it is installable on that API and above),
so it must be **≤ `min_sdk`**: a wheel tagged `android_24_*` requires
`min_sdk >= 24`, while a wheel tagged `android_21_*` is fine at any `min_sdk >= 21`.
`kivyforge lock` accepts the highest-tag wheel whose API level is ≤ `min_sdk` and
never rejects a compatible lower-tag wheel. See
[artifact-distribution-android §"App-specific native extensions"](03-artifact-distribution-android.md#app-specific-native-extensions-cython--c) for the out-of-band wheel-build path.

### `schema_version` evolution policy (Android)

Same policy as iOS: additive changes (new optional fields/subtables) do not bump
`[tool.kivy.android].schema_version`; backward-incompatible changes must. The tool
supports reading the latest N major Android schema versions (initially N=1); a
future `kivyforge migrate` verb converts older blocks. `pylock.android.toml`
records the source Android schema version in its `[tool.kivyforge]` block.

### `[tool.kivy.android.python]`

```toml
[tool.kivy.android.python]
version = "3.14.6"
```

| Field     | Type   | Required | Default | Description                                                                                                                                                                                                    |
| --------- | ------ | -------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `version` | string | yes      | —       | The python.org Android embeddable-package version. Init pins the latest known release (Android is CPython Tier 3 since 3.13; 3.14 is stable, 3.15 pre-release). The per-ABI download URLs + SHA-256 are resolved at lock time and recorded in `pylock.android.toml`'s `[tool.kivyforge]` block. |

### `[tool.kivy.android.permissions]`

```toml
[tool.kivy.android.permissions]
uses = [
    "android.permission.INTERNET",
    "android.permission.CAMERA",
    "android.permission.WRITE_EXTERNAL_STORAGE",
]
features = [
    { name = "android.hardware.camera", required = false },
]
auto_features = true   # default; auto-add non-required <uses-feature> for hardware-implying permissions
```

| Field      | Type            | Required | Description                                                                                                                                                                 |
| ---------- | --------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `uses`     | list of string  | no       | Each entry becomes a `<uses-permission android:name="...">` in the generated manifest. Bare permission names (`INTERNET`) are auto-prefixed with `android.permission.`; fully-qualified names (`android.permission.CAMERA`, or a custom/third-party permission) are written verbatim. |
| `features` | list of table   | no       | Each `{ name, required }` becomes a `<uses-feature>`. `required` defaults to `true`. Use it to declare a feature explicitly — most often to *promote* an auto-added implied feature (below) to `required = true`, or to declare a hardware feature no permission implies. |
| `auto_features` | bool       | no (default `true`) | Auto-add a **non-required** `<uses-feature>` for each hardware-implying permission (see the mapping below). |

#### Implied hardware features (`auto_features`)

Google Play uses `<uses-feature>` to **filter which devices can install an app**.
A permission that implies hardware (e.g. `CAMERA`) causes Play to *implicitly*
treat that hardware as **required** unless the app declares the feature as
`required="false"` — so a camera-permission app silently disappears from the
Play listing on any device without a camera, even if the camera is optional to
the app. This is a well-known packaging gotcha.

With `auto_features = true` (the default), `kivyforge build` emits a
**non-required** `<uses-feature android:required="false">` for each permission in
`uses` that implies hardware, following [Google's permission→feature
implications](https://developer.android.com/guide/topics/manifest/uses-feature-element#permissions-features):

| Permission in `uses` | Auto-added non-required `<uses-feature>` |
|----------------------|------------------------------------------|
| `CAMERA` | `android.hardware.camera`, `android.hardware.camera.autofocus` |
| `RECORD_AUDIO` | `android.hardware.microphone` |
| `ACCESS_FINE_LOCATION` | `android.hardware.location`, `android.hardware.location.gps` |
| `ACCESS_COARSE_LOCATION` | `android.hardware.location`, `android.hardware.location.network` |
| `BLUETOOTH` / `BLUETOOTH_CONNECT` / `BLUETOOTH_SCAN` | `android.hardware.bluetooth` (and `android.hardware.bluetooth_le` for the LE-scan permissions) |
| `NFC` | `android.hardware.nfc` |
| `USE_BIOMETRIC` / `USE_FINGERPRINT` | `android.hardware.fingerprint` |

The mapping follows Google's table with two deliberate extras: `USE_BIOMETRIC`
implies no feature in Google's list (biometric hardware may be face or iris, not
only fingerprint), but kivyforge mirrors `USE_FINGERPRINT`'s non-required feature
for symmetry; and Google's table predates the API-31
`BLUETOOTH_CONNECT`/`BLUETOOTH_SCAN` permissions, so kivyforge extends the legacy
`BLUETOOTH` implications to them. Both extras are non-required, so they never
filter a device.

An explicit entry in `features` **overrides** the auto-added one for the same
feature name — declare `{ name = "android.hardware.camera", required = true }` to
genuinely require the hardware (Play then hides the app from camera-less devices,
which is what you want for a camera-first app). Set `auto_features = false` to
suppress the behavior entirely and manage every `<uses-feature>` by hand.

The rationale matches Briefcase's model (declare permissions; don't get filtered
off devices by accident), adapted to kivyforge's explicit-permission list rather
than a cross-platform permission vocabulary.

`uses-permission-sdk-23`, `<permission>` (custom-defined), and per-permission
`maxSdkVersion` attributes are expressible via the manifest passthrough (see
`[tool.kivy.android.manifest]`) until a dedicated schema grows for them.

### `[tool.kivy.android.native.aars]` and `[tool.kivy.android.native.jars]`

Prebuilt Android library archives the app links against — the Android analog of
iOS's `[tool.kivy.ios.native.xcframeworks]`. Empty by default.

```toml
[tool.kivy.android.native.aars]
MyVendorSDK = { version = "3.1.0", source = "https://vendor.example.com/sdk/MyVendorSDK-3.1.0.aar" }
LocalWidget = { version = "0.2.0", source = "libs/LocalWidget-0.2.0.aar" }

[tool.kivy.android.native.jars]
legacyutil = { version = "1.4.0", source = "libs/legacyutil-1.4.0.jar" }
```

- **Type**: table of name → inline table.
- **Semantics**: each `.aar`/`.jar` is staged into the Gradle project's `libs/` and wired as a `files(...)`/module dependency; `.aar` resource/manifest/`.so` contents are merged by AGP. `kivyforge lock` reads each artifact to pin its SHA-256.

Per-entry fields:

| Field     | Type   | Required | Description                                                                                                                                                                                                                            |
| --------- | ------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `version` | string | yes      | Exact version (recorded in the lock; used for the staged filename).                                                                                                                                                                    |
| `source`  | string | yes      | Where to fetch the archive. Always **explicit**: a direct download URL or a repo-relative path to a vendored artifact. No indirection keywords. `kivyforge build` rejects an absolute path or one escaping the project directory, mirroring the iOS xcframework rule. |

> **`.aar`/`.jar` vs. Maven dependency.** Use `native.aars`/`native.jars` for a
> file you host or vendor by URL/path. Use `[tool.kivy.android.gradle]` (below)
> for anything resolvable from a Maven repository by coordinate — let Gradle fetch
> it rather than committing the binary.

### `[tool.kivy.android.gradle]` — Maven/Gradle dependencies

For native/Java dependencies distributed through Maven repositories (Maven
Central, Google's Maven, or a custom repo). This is the Android analog of iOS's
Swift Package Manager channel: **Gradle owns the resolve/fetch/compile lifecycle**;
kivyforge records the pinned coordinate + resolved version in the lock and emits
the dependency into `app/build.gradle`. Empty by default.

```toml
[tool.kivy.android.gradle]
repositories = [
    "https://maven.example.com/releases",   # in addition to mavenCentral() + google()
]
dependencies = [
    "androidx.work:work-runtime:2.9.1",
    "com.google.android.gms:play-services-location:21.3.0",
]
```

| Field          | Type           | Required | Description                                                                                                                                                               |
| -------------- | -------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dependencies` | list of string | no       | Gradle dependency coordinates (`group:artifact:version`). Each is emitted as an `implementation` in `app/build.gradle`. Versions must be explicit (no dynamic `+` ranges) so the build is reproducible. |
| `repositories` | list of string | no       | Extra Maven repository URLs, in addition to the always-present `google()` and `mavenCentral()`.                                                                          |

Reproducibility for this channel records the **full resolved transitive graph with a SHA-256 per artifact** in the lock (`kivyforge lock` resolves it via Gradle) and pins fully-versioned coordinates in the generated `app/build.gradle`. Unlike the other channels the hash is an **audit record, not a build-time gate** — Gradle's own verification is whole-classpath, so it cannot be scoped to just your Maven deps. See [pylock-android-spec §"Gradle/Maven pins"](02-pylock-android-spec.md#toolkivyforgegradle--mavengradle-pins) and the SPM-parallel rationale in [artifact-distribution-android §"Distribution channel 4"](03-artifact-distribution-android.md#distribution-channel-4-gradlemaven-dependencies).

### `[tool.kivy.android.include_files]` — copy arbitrary files into the project

Some libraries require a config file to sit at a specific path in the *Android
Gradle project* — the canonical case is Firebase's `google-services.json` at the
module root (`app/`), or a `network_security_config.xml` under `res/xml/`. These
aren't Python assets (they don't belong in the Python bundle) and aren't
`.aar`/`.jar`s. `include_files` copies repo files verbatim into the generated
`<app>-android/` tree during the **Stage** step.

```toml
[[tool.kivy.android.include_files]]
dest = "app"                                # module root -> app/google-services.json
sources = ["config/google-services.json"]

[[tool.kivy.android.include_files]]
dest = "app/src/main/res/xml"
sources = ["config/network_security_config.xml", "config/backup_rules.xml"]
```

| Field     | Type           | Required | Description                                                                                                                                                     |
| --------- | -------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dest`    | string         | yes      | Destination directory **relative to the generated `<app>-android/` project root** (e.g. `app`, `app/src/main/res/xml`). Must stay inside the project; absolute or escaping paths are rejected. |
| `sources` | list of string | yes      | Repo-relative files (or directories, copied recursively) to place into `dest`, keeping each source's basename. Entries must not escape the project directory. |

- **Type**: array of tables (order preserved).
- **Semantics**: pure file copy, run after project generation and before Gradle is invoked, so the files are visible to AGP (resource merge, `google-services` plugin, etc.). `kivyforge lock` records each source's SHA-256, and `kivyforge build` **verifies every pin before staging**: an edited, added, or deleted file fails the build naming the file (and, for an edit, both hashes) and pointing at `kivyforge lock` to re-record. This is drift detection over your own repo files, not supply-chain integrity, so re-locking is always the fix; `--no-verify-lock` skips it along with every other lock check. A copy that would overwrite a kivyforge-generated file (e.g. `AndroidManifest.xml`, `build.gradle`) is **rejected** — use the manifest/gradle passthroughs for those. This mirrors ksproject's `include`/asset-copy convention and Briefcase's ability to drop files into the scaffold.

> **`include_files` vs. `[tool.kivy].app_dir`.** `app_dir` is your Python payload
> (packaged into the Python asset bundle and unpacked at runtime). `include_files`
> is for *Gradle-project* files that must exist at build time at a native path —
> they never enter the Python bundle.

### `[tool.kivy.android.src]` — custom Java/Kotlin sources

The analog of p4a's `android.add_src`: extra Java/Kotlin source trees compiled
and dexed into the APK by the app's own Gradle.

```toml
[tool.kivy.android.src]
java = ["android/java"]        # repo-relative source roots merged into app/src/main/java
kotlin = ["android/kotlin"]    # optional; enables the Kotlin Gradle plugin when non-empty
```

| Field    | Type           | Required | Description                                                                                                                       |
| -------- | -------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `java`   | list of string | no       | Repo-relative directories merged into the generated module's Java source set. Entries must not escape the project directory.      |
| `kotlin` | list of string | no       | Repo-relative Kotlin source roots. A non-empty list makes `kivyforge build` apply the Kotlin Gradle plugin.                        |

> This is *user* Java/Kotlin only. The bootstrap's own Java (the `org.kivy.android.*`
> Activity/service classes and `org.jnius.NativeInvocationHandler`) is generated
> by kivyforge, not declared here — see [bootstrap-android](05-bootstrap-android.md).

### `[tool.kivy.android.services]` and `[tool.kivy.android.activities]`

Declare additional manifest components. A Kivy app's main Activity is generated by
the bootstrap; these tables add *extra* components.

```toml
[[tool.kivy.android.services]]
name = "Downloader"                 # -> a generated org.kivy.android.PythonService subclass
entry_point = "service_downloader"  # python module run in the service process
exported = false

# Foreground services (long-running, user-visible work). Android 14+ requires
# BOTH a type and a posted notification; kivyforge enforces both at build time.
foreground = true
foreground_service_type = "dataSync"    # required when foreground = true (enum below)
notification = { channel_id = "downloads", channel_name = "Downloads", title = "Syncing…", text = "Downloading content" }

[[tool.kivy.android.activities]]
name = "org.example.SettingsActivity"   # must be provided via [tool.kivy.android.src]
exported = false
```

**Service fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | The generated `PythonService` subclass name. |
| `entry_point` | string | yes | Python module run in the service process. |
| `exported` | bool | no (`false`) | `android:exported`. |
| `foreground` | bool | no (`false`) | Marks a foreground service. When `true`, both `foreground_service_type` and `notification` are **required** (a foreground service with neither is rejected at build time). |
| `foreground_service_type` | enum | required iff `foreground` | Written as `android:foregroundServiceType`; kivyforge auto-adds `FOREGROUND_SERVICE` **and** the matching typed permission (`FOREGROUND_SERVICE_<TYPE>`). One of `camera`, `connectedDevice`, `dataSync`, `health`, `location`, `mediaPlayback`, `mediaProcessing`, `mediaProjection`, `microphone`, `phoneCall`, `remoteMessaging`, `shortService`, `specialUse`, `systemExempted`. The set tracks the platform's `foregroundServiceType` list and grows with kivyforge releases (`mediaProcessing` requires Android 15 / API 35). |
| `notification` | table | required iff `foreground` | The notification the service posts via `startForeground()` on start (mandatory on Android 14+ or the OS kills it). `channel_id`, `channel_name`, `title`, `text` (strings); optional `icon` (a `mipmap`/`drawable` resource name). The bootstrap creates the channel and posts it; the running Python may update it later via pyjnius. |

- **Services**: each entry generates a `PythonService`-derived component that runs a named Python `entry_point` in a separate process. This is the declarative surface for background work. A `foreground` service carries its declared type and notification through to the generated `PythonService` (see [bootstrap-android](05-bootstrap-android.md)); `specialUse` additionally needs a `<property>` tag supplied via the manifest passthrough.
- **Activities**: register an extra activity the user supplies via `[tool.kivy.android.src]`. `intent_filters` (below) attach to the main activity by default; a secondary activity carries its own via the manifest passthrough.

### `[tool.kivy.android.intent_filters]`

```toml
[[tool.kivy.android.intent_filters]]
action = "android.intent.action.VIEW"
categories = ["android.intent.category.DEFAULT", "android.intent.category.BROWSABLE"]
data = [{ scheme = "https", host = "example.org" }]
```

Each entry becomes an `<intent-filter>` on the main activity (for deep links,
custom schemes, share targets). Free-form pass-through with light validation
(known action/category/data attribute names).

### `[tool.kivy.android.manifest]` — manifest passthrough

```toml
[tool.kivy.android.manifest]
application = { "android:largeHeap" = true, "android:usesCleartextTraffic" = false }
activity    = { "android:launchMode" = "singleTop" }
placeholders = { MAPS_API_KEY = "AIza..." }         # manifestPlaceholders

# Components a dependency insists on exporting (release-policy opt-in):
allow_exported = ["com.vendor.sdk.TrampolineActivity"]

# Raw-XML escape hatches for elements the structured tables can't express:
extra_manifest_xml = """
<queries>
  <intent><action android:name="android.intent.action.VIEW"/></intent>
</queries>
"""
extra_application_xml = """
<receiver android:name="org.example.BootReceiver" android:exported="false">
  <intent-filter><action android:name="android.intent.action.BOOT_COMPLETED"/></intent-filter>
</receiver>
<provider android:name="androidx.core.content.FileProvider"
          android:authorities="${applicationId}.fileprovider" android:exported="false"/>
"""
extra_activity_xml = ""    # extra children of the main <activity> (rarely needed)
```

| Field | Type | Kind | Description |
|-------|------|------|-------------|
| `application` | table | attributes | Attribute → value pairs merged into the generated `<application>` element. |
| `activity` | table | attributes | Attribute → value pairs merged into the generated main `<activity>` element. |
| `placeholders` | table | — | `manifestPlaceholders` (string → string). |
| `allow_exported` | list of string | policy | Component class names the release policy tolerates as `android:exported="true"`, on top of kivyforge's own baseline (`org.kivy.android.PythonActivity`, and `androidx.profileinstaller.ProfileInstallReceiver` — pulled in by the always-present Material Components dependency and exported by AndroidX's own design, gated by the system-only `DUMP` permission). Needed because `kivyforge package` lints the **merged** manifest: a `.aar`/Maven dependency's exported component cannot be edited out of your `pyproject.toml`, and blocking the release forever would be the only alternative. Per-component and auditable — never a blanket off switch. Names are matched exactly as they appear in the merged manifest (fully qualified). |
| `extra_manifest_xml` | string | raw XML | Verbatim child elements injected before the closing `</manifest>` — for elements with no structured field (`<queries>`, custom `<permission>` / `<permission-group>`, `<uses-sdk>` extras). |
| `extra_application_xml` | string | raw XML | Verbatim child elements injected before the closing `</application>` — for `<receiver>`, `<provider>`, `<meta-data>`, extra `<service>`/`<activity>` you author by hand, etc. |
| `extra_activity_xml` | string | raw XML | Verbatim child elements injected into the generated main `<activity>` (rarely needed; `intent_filters` covers the common case). |

- **Attribute tables** (`application` / `activity`) are the *structured, validated* escape hatch: keys that collide with a kivyforge-managed manifest attribute (see the managed table below) are **rejected** with a diagnostic naming both the key and the field that controls it.
- **Raw-XML fields** are the *unstructured* escape hatch, mirroring Briefcase's `android_manifest_*_extra_content`, for arbitrary child elements the schema does not model. kivyforge injects them verbatim but **parses the fragment first** (well-formedness check) and fails the build with the XML error and line if it is malformed, rather than emitting a broken manifest that fails deep inside AGP's manifest merger. `${applicationId}` and any declared `placeholders` are substituted. Use the structured tables/fields when one exists; reach for raw XML only for elements kivyforge doesn't expose.

### `[tool.kivy.android.signing]`

```toml
[tool.kivy.android.signing]
keystore = "release.keystore"       # repo-relative or absolute path
key_alias = "upload"
store_password_env = "KIVYFORGE_KEYSTORE_PASSWORD"
key_password_env = "KIVYFORGE_KEY_PASSWORD"
v1_signing = false
v2_signing = true
v3_signing = true
v4_signing = false
```

| Field                 | Type   | Required            | Default                        | Description                                                                                                                                                              |
| --------------------- | ------ | ------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `keystore`            | string | for release builds  | —                              | Path to the Java keystore holding the signing key. Repo-relative (recommended for CI) or absolute. **Never commit a production keystore to a public repo.**              |
| `key_alias`           | string | for release builds  | —                              | The key alias within the keystore.                                                                                                                                       |
| `store_password_env`  | string | no                  | `"KIVYFORGE_KEYSTORE_PASSWORD"`| Name of the environment variable holding the keystore password. Passwords are **never** stored in `pyproject.toml`.                                                       |
| `key_password_env`    | string | no                  | `"KIVYFORGE_KEY_PASSWORD"`     | Name of the environment variable holding the key password (defaults to the store password if unset, per `keytool` convention).                                           |
| `v1_signing`          | bool   | no                  | `false`                        | JAR signing (APK Signature Scheme v1). Only needed below API 24, and kivyforge's `min_sdk` floor **is** 24 (the platform verifies v2+ there), so it is **off by default**; enable only if a distribution channel or analysis tool demands a v1 signature. |
| `v2_signing`          | bool   | no                  | `true`                         | APK Signature Scheme v2 (whole-file, Android 7+).                                                                                                                         |
| `v3_signing`          | bool   | no                  | `true`                         | APK Signature Scheme v3 (key rotation, Android 9+).                                                                                                                       |
| `v4_signing`          | bool   | no                  | `false`                        | APK Signature Scheme v4 (incremental install, Android 11+). Off by default; enable for `adb install --incremental` workflows.                                             |

Android signing is **mandatory** (unlike Windows Authenticode, which is
off-by-default): every APK/AAB must be signed to install. Debug builds are signed
automatically with the standard Android debug keystore (no config needed); release
packaging (`kivyforge package`) requires the `[tool.kivy.android.signing]` table (or the
equivalent CLI/env values). For Play distribution, the `.aab` is signed with your
**upload key** and Google re-signs with the app key (Play App Signing). The v1–v4
toggles govern **`.apk`** signing (`apksigner`); an **`.aab`** is JAR-signed
(`jarsigner`) with the same key, and those APK-signature schemes apply to the APKs
generated from the bundle, not to the `.aab` container itself. See
[signing-prerequisites-android](07-signing-prerequisites-android.md) and
[cli-android §`kivyforge package`](06-cli-android.md#kivyforge-package).

### `[tool.kivy.android.gradle_properties]`

```toml
[tool.kivy.android.gradle_properties]
"org.gradle.jvmargs" = "-Xmx4g"
"android.useAndroidX" = true
```

Free-form escape hatch merged into the generated `gradle.properties`. `kivyforge`
reserves the properties it manages (e.g. it always sets `android.useAndroidX=true`
and the R8/minify posture); user-supplied values for a reserved key are rejected
with a diagnostic.

### `[tool.kivy.android.build_settings]`

```toml
[tool.kivy.android.build_settings]
minify = false             # R8 code shrinking/obfuscation for release
shrink_resources = false
multidex = true
byte_compile = "release"   # "release" | true | false — .pyc handling for the Python bundle
strip_source = "release"   # "release" | true | false — drop .py once byte-compiled
strip_native_libs = "release"   # "release" | true | false — strip debug symbols from shipped .so
debug_symbols = "symbol_table"  # "symbol_table" | "full" | "none" — native symbols exported for crash symbolication
```

| Field              | Type | Required | Default | Description                                                                                                                                    |
| ------------------ | ---- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `minify`           | bool | no       | `false` | Enable R8 for release builds. Off by default — R8 on a Python app mostly shrinks the thin Java bootstrap and risks stripping reflected classes (pyjnius `autoclass` targets); enable only with a tested keep-rules set. |
| `shrink_resources` | bool | no       | `false` | Resource shrinking (requires `minify = true`).                                                                                                 |
| `multidex`         | bool | no       | `true`  | Enable multidex. On by default because bundled `.aar`s + bootstrap easily exceed the 64K method limit; harmless at `minSdk 24` (native multidex). |
| `byte_compile`     | `"release"` \| bool | no | `"release"` | Byte-compile the Python payload (app code + pure-Python deps + stdlib) to `.pyc` when staging the asset bundle. `"release"` compiles for release packaging (`kivyforge package`, and a plain `kivyforge build` that stages for it) only — debug builds keep `.py` for readable tracebacks and fast iteration; `true`/`false` force it on/off for all builds. See ["Which interpreter writes the `.pyc`"](#which-interpreter-writes-the-pyc). |
| `strip_source`     | `"release"` \| bool | no | `"release"` | When byte-compiling, also drop the corresponding `.py` from the bundle (ship `.pyc` only), roughly halving the Python payload. `"release"` applies to release builds only. Independent stack traces still show file/line via the `.pyc` line table; only source *text* is unavailable. Ignored when `byte_compile` is off. |
| `strip_native_libs`| `"release"` \| bool | no | `"release"` | Strip debug symbols from the shipped `.so`s (runtime, wheel extensions, wheel `.libs/`) — a large size win for release. **Performed by AGP** during packaging (kivyforge sets `packagingOptions.jniLibs.keepDebugSymbols` accordingly), not by a bespoke kivyforge strip step, so behavior tracks the toolchain. Off for debug so native crashes stay symbolicated in place. When on, symbols are **preserved to the debug-symbol artifact** per `debug_symbols` (below) rather than discarded — the same retain-symbols posture as iOS dSYMs. |
| `debug_symbols`    | `"symbol_table"` \| `"full"` \| `"none"` | no | `"symbol_table"` (release) | Which native debug symbols AGP exports for **crash symbolication** of the stripped release `.so`s, mapped to AGP's [`debugSymbolLevel`](https://developer.android.com/studio/build/shrink-code#native-crash-support): `symbol_table` (function names — enough to symbolicate native stack frames; small), `full` (adds DWARF line tables — larger, enables source-line native debugging), `none` (export nothing). See ["Native debug symbols"](#native-debug-symbols). Ignored for debug builds (unstripped) and when `strip_native_libs` is off. |

> **Size posture.** These default to `"release"` so debug builds stay
> fast-to-stage and fully debuggable, while release `.apk`/`.aab` ship compact
> `.pyc`-only, symbol-stripped payloads. This is the same lever set Briefcase and
> ksproject expose (byte-compile + strip), unified here under one table with a
> debug/release-aware default. Stdlib *pruning* (dropping unused stdlib modules)
> is intentionally **not** a `build_settings` knob — it's unsafe to infer under
> pyjnius/`importlib` dynamic imports; prune deliberately via the resolution-graph
> `exclude` field and app-level testing instead. See
> [gradle-project-generation §"Python asset bundle"](04-gradle-project-generation.md#the-python-asset-bundle).

### Which interpreter writes the `.pyc`

A `.pyc` is loadable only by the exact CPython magic number that wrote it, and
that number is frozen at each `3.x.0` — so any `3.x.z` works, but a different
minor version does not: its output is silently ignored when the source ships
alongside, and fails outright once `strip_source` has removed the source.

kivyforge is installed under whatever Python the user has, which is usually *not*
the version being shipped to the device, so it does not require being *run* under
the target version. It looks for a matching interpreter — the current one first,
then `py -X.Y` (Windows) / `pythonX.Y` — and compiles with that one.

When no matching interpreter exists, the outcome depends on how the setting was
written, because the two spellings mean different things:

- `byte_compile = "release"` (the default) means *when it makes sense*: kivyforge
  prints a note and ships source. A build nobody configured is never broken by
  the absence of an interpreter nobody asked for.
- `byte_compile = true` means *I insist*: the build fails, because silently
  shipping source would leave the user believing the payload was compiled.

Two further properties of the emitted `.pyc`, both deliberate:

- **Hash-based, unchecked invalidation** ([PEP 552](https://peps.python.org/pep-0552/))
  rather than the default mtime+size, which saves a `stat` per import on a device
  whose sources cannot be newer than what shipped.
- **Bundle-relative paths** (`compileall -s`), because a `.pyc` records the path
  it was compiled from — the default would bake the build machine's directory
  layout into the shipped APK and make the bundle's content stamp differ per
  machine. Tracebacks still name the file.

`strip_source` needs the **sourceless layout**: PEP 3147 looks for `foo.pyc` at
the source's own path, never inside `__pycache__/`, so compiling to `__pycache__/`
and then deleting the `.py` would ship a bundle that imports nothing at all.
kivyforge emits `__pycache__/` when the source is kept and the source-adjacent
layout when it is not.

### Native debug symbols

A stripped release ships small `.so`s but produces **unsymbolicated native
crashes** — a stack trace through `libpython3.14.so`, the SDL family, or a wheel's
compiled extension is just hex addresses. This is the Android counterpart of the
iOS **dSYM** story (see [cli-ios `--release` archive](../ios/04-cli-ios.md)): kivyforge
strips the shipped binary *and retains the symbols* so crashes can be
symbolicated after the fact.

When `strip_native_libs` is on (release default), `debug_symbols` selects how much
AGP exports. AGP writes the symbols to:

```
<app>-android/app/build/outputs/native-debug-symbols/release/native-debug-symbols.zip
```

- **Play upload**: upload that `.zip` in the Play Console (App bundle explorer →
  Downloads), or let it ride embedded in the `.aab` — Play then symbolicates native
  crashes in Android vitals automatically.
- **Third-party crash reporters** (Crashlytics, Sentry, Bugsnag): point their
  NDK-symbol upload step at the same `native-debug-symbols.zip`. This is the exact
  parallel to pointing a symbol uploader at the iOS `.xcarchive/dSYMs/`.

`symbol_table` is the default because it symbolicates native frames (function
names) at a fraction of `full`'s size; choose `full` only when you need native
source-line debugging. Symbol extraction is done by AGP via the **NDK** — already
a prerequisite for *every* Android build, since it compiles the native launcher
(see [gradle-project-generation §"The native launcher"](04-gradle-project-generation.md#the-native-launcher-libmainso));
`kivyforge doctor` reports a missing NDK. Nothing is exported for debug builds
(their `.so`s are unstripped and already symbolicated).

## Manifest keys kivyforge manages

These are written automatically from the schema and cannot be set via
`[tool.kivy.android.manifest]`:

| Managed attribute / element | Source |
|-----------------------------|--------|
| `package` / `applicationId` | `[tool.kivy.android].package` |
| `android:versionCode` | `[tool.kivy.android].version_code` (verbatim, or derived from `[project].version` + `build` when `"auto"`) |
| `android:versionName` | `[project].version` |
| `android:label` (application + main activity) | `[tool.kivy].display_name` (falls back to `[project].name`) |
| `android:icon` / `android:roundIcon` | `[tool.kivy.android.icons]` (or a default) |
| `minSdkVersion` / `targetSdkVersion` / `compileSdkVersion` | `min_sdk` / `target_sdk` / `compile_sdk` |
| main `<activity android:name>` | the generated `org.kivy.android.PythonActivity` (bootstrap) |
| `android:screenOrientation` (main activity) | `[tool.kivy].orientation` |
| `android:theme` (application + main activity) + the generated splash `<style>` | `[tool.kivy.android].base_theme` (or the default) and `[tool.kivy.android.splash]` |
| `android:extractNativeLibs` / `useLegacyPackaging` | toolchain (must extract native libs so Python can `dlopen` them; see [gradle-project-generation](04-gradle-project-generation.md)) |
| non-required `<uses-feature>` for hardware-implying permissions | `[tool.kivy.android.permissions].auto_features` (see [Implied hardware features](#implied-hardware-features-auto_features)) |

> **Permissions are not force-injected.** kivyforge adds no permission on your
> behalf — not even `INTERNET`. `kivyforge init` *seeds* `INTERNET` into
> `permissions.uses` as a convenience (most apps want it), but it is an ordinary
> editable entry: delete it and it is gone from the manifest. The only permissions
> kivyforge adds implicitly are the `FOREGROUND_SERVICE*` permissions a declared
> foreground service requires (above).

## Concrete example

A real-world `pyproject.toml` for a typical Kivy 2.3.1 app, Android-focused:

```toml
[project]
name = "touchtracer"
version = "1.0.0"
description = "Touchtracer demo"
requires-python = ">=3.14"
dependencies = [
    "kivy==2.3.1",
    "pyjnius",
]
authors = [{ name = "Kivy Team", email = "team@kivy.org" }]

[tool.kivy]
display_name = "Touchtracer"
app_dir = "src"
entry_point = "main"
orientation = ["portrait", "landscape-left", "landscape-right"]

[tool.kivy.android]
schema_version = 1
package = "org.kivy.touchtracer"
version_code = 1
min_sdk = 24
target_sdk = 35
compile_sdk = 35
kivy_generation = 2
abis = ["arm64_v8a", "x86_64"]
# Kivy 2.3.1 + pyjnius are cross-built locally and vendored until on PyPI:
find_links = ["wheels"]

[tool.kivy.android.python]
version = "3.14.6"

[tool.kivy.android.permissions]
uses = ["INTERNET"]

[tool.kivy.android.icons]
source = "assets/icon.png"        # 1024×1024 PNG
background = "#ffffff"

[tool.kivy.android.splash]
source = "assets/splash.png"
background = "#000000"

[tool.kivy.android.signing]
keystore = "release.keystore"
key_alias = "upload"
# passwords come from KIVYFORGE_KEYSTORE_PASSWORD / KIVYFORGE_KEY_PASSWORD
```

## Validation rules (Android)

`kivyforge lock` and `kivyforge build` reject any `pyproject.toml` that:

1. Lacks a `[project]` table or omits `[project].name` / `[project].version`.
2. Lacks `[tool.kivy.android]` when running an Android command.
3. Lacks `[tool.kivy.android].schema_version` or specifies an unsupported value.
4. Lacks `[tool.kivy.android].package`, or sets it to a value that is not a valid Android package name (≥ 2 dot-separated Java-identifier segments).
5. Has `[tool.kivy].entry_point` that isn't a valid Python identifier (or dotted identifier).
6. Omits `[tool.kivy].app_dir`, or sets it to the project root (`"."`), an empty string, an absolute path, or a path that escapes the project directory.
7. Has `[tool.kivy].orientation` values outside the allowed set.
8. Sets `[tool.kivy.android].min_sdk` below `24`, or `target_sdk`/`compile_sdk` less than `min_sdk`, or `compile_sdk < target_sdk`.
9. Sets `[tool.kivy.android].kivy_generation` to anything other than `2` or `3`.
10. Sets `[tool.kivy.android].abis` to a non-list, an empty list, or a list containing any value other than `"arm64_v8a"` / `"x86_64"` (32-bit ABIs are rejected — the python.org runtime is 64-bit only).
11. Lacks `[tool.kivy.android.python].version`, or specifies one for which no python.org Android embeddable package exists (verified at lock time), or one incompatible with `[project].requires-python`.
12. Sets `find_links` entries that are absolute, empty, or escape the project directory.
13. Declares a `[tool.kivy.android.gradle].dependencies` entry that is not a fully-versioned `group:artifact:version` coordinate (dynamic ranges are rejected for reproducibility).
14. Declares a `native.aars`/`native.jars` `source` that is an absolute path or escapes the project directory.
15. Sets reserved keys under `[tool.kivy.android.manifest]`, `[tool.kivy.android.gradle_properties]`, or otherwise collides with a kivyforge-managed manifest attribute; or sets `[tool.kivy.android.manifest].allow_exported` to anything other than a list of non-empty strings.
16. Runs `kivyforge package` without a resolvable signing key (keystore/alias via `[tool.kivy.android.signing]` or CLI/env).
17. Provides an `extra_manifest_xml` / `extra_application_xml` / `extra_activity_xml` fragment that is not well-formed XML (checked before manifest generation).
18. Declares an `[[tool.kivy.android.include_files]]` entry whose `dest` is absolute or escapes the project, whose `sources` are absolute/escaping/missing, or that targets a kivyforge-generated file (e.g. `AndroidManifest.xml`, `build.gradle`).
19. Sets `[tool.kivy.android.build_settings]` `byte_compile` / `strip_source` / `strip_native_libs` to a value other than a bool or the string `"release"`; or sets `debug_symbols` to anything other than `"symbol_table"` / `"full"` / `"none"`. (A resolvable NDK is required for **every** Android build — it compiles the native launcher; `kivyforge doctor` reports it missing.)
20. Sets `[tool.kivy.android].version_code` to anything other than a positive integer or the string `"auto"`; or, in `"auto"` mode, has a `[project].version` that is not a final `MAJOR.MINOR.PATCH` release (pre-release/dev/post/local/epoch or a 4th segment), a `MINOR`/`PATCH`/`build` component `> 99`, or a derived code exceeding `2,100,000,000`.
21. Sets `[tool.kivy.android].base_theme` to a non-string or empty string; or sets a `[tool.kivy.android.splash]` field to the wrong type (`animation_duration` not a positive integer; `background`/`icon_background` not a `#rrggbb` hex color) or to an image/drawable path that is missing or escapes the project directory.

Validation errors are printed with the offending line number and a remediation hint.
