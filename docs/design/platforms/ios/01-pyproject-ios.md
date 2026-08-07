# iOS — `[tool.kivy.ios]` Overlay Schema

This document defines the **iOS-specific overlay** in `pyproject.toml`: the
`[tool.kivy.ios]` table and its subtables. It layers on top of the shared
`[project]` + `[tool.kivy]` tables and the overlay pattern described in the
[common pyproject spec](../../common/01-pyproject-kivy-spec.md).

`[tool.kivy.ios]` is an **additive overlay**: it only contains keys whose value
must differ from the cross-platform default in `[tool.kivy]`, or keys that are
iOS-only (e.g. `bundle_id`, `signing.team_id`). Everything inside it is consumed
only by kivyforge's iOS backend.

## `[project]` (PEP 621) — iOS consumption

kivyforge's iOS backend consumes the following PEP 621 keys directly; the rest are passed through where iOS exposes a slot for them.

| PEP 621 key              | iOS use                                                                                                                                                                                                                                   | Required       |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| `name`                   | Standard PEP 621 distribution name (may contain hyphens, dots, or underscores per PEP 503). Used as the Xcode target name and file slug — kivyforge normalizes it for the slug as needed — and, when `[tool.kivy].display_name` is absent, as the home-screen name. Not required to be a valid Python identifier; that constraint applies only to `entry_point`.                              | yes                        |
| `version`                | `CFBundleShortVersionString`. Marketing version.                                                                                                                                                                                          | yes                        |
| `description`            | `CFBundleDisplayName` fallback when `[tool.kivy].display_name` is unset; also used for App Store metadata if present.                                                                                                                     | no                         |
| `requires-python`        | Cross-checked against `[tool.kivy.ios.python].version` to fail fast on impossible combinations (e.g. `requires-python = ">=3.16"` with `[tool.kivy.ios.python].version = "3.15.0"`).                                                      | no, but warned on mismatch |
| `dependencies`           | The full Python dependency set (PEP 508 strings, including environment markers for platform-specific entries). `kivyforge lock` evaluates markers against the iOS target and resolves the matching subset to wheels in `pylock.ios.toml`. | yes (may be empty)         |
| `optional-dependencies`  | Ignored by the iOS backend unless the user opts in per-extra via a future `[tool.kivy.ios].extras` allowlist.                                                                                                                    | no                         |
| `authors`, `maintainers` | First `authors` entry's `name` populates the bundle copyright string when no override is given.                                                                                                                                           | no                         |

## Icons and splash screens

Icons and splash screens are inherently platform-specific: iOS requires a 1024×1024 flat PNG (Xcode generates all sizes into an asset catalog). Each platform declares its own icon and splash in its own subtable. If `[tool.kivy.ios.icons]` or `[tool.kivy.ios.splash]` is absent, no icon or splash is generated and Xcode uses its defaults.

### `[tool.kivy.ios.icons]`

```toml
[tool.kivy.ios.icons]
source = "assets/icon-ios.png"   # 1024×1024 PNG
```

| Field    | Type   | Required | Description                                                                                                                                                        |
| -------- | ------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `source` | string | no       | Path to a 1024×1024 source PNG relative to `pyproject.toml`. `kivyforge build` generates the full iOS icon set (all `AppIcon` sizes) into the Xcode asset catalog. |

### `[tool.kivy.ios.splash]`

```toml
[tool.kivy.ios.splash]
source = "assets/splash-ios.png"
background = "#ffffff"
```

| Field        | Type   | Required | Description                                                                                           |
| ------------ | ------ | -------- | ----------------------------------------------------------------------------------------------------- |
| `source`     | string | no       | Path to a launch-screen image. Used as the centered image in the generated `LaunchScreen.storyboard`. |
| `background` | string | no       | Hex color (`#rrggbb`) for the launch screen background.                                               |

## `[tool.kivy.ios]`

iOS-specific overlay. Every field below applies to iOS only.

```toml
[tool.kivy.ios]
schema_version = 1
bundle_id = "org.example.myapp"
build = 1
deployment_target = "13.0"
```

| Field               | Type    | Required | Default  | Description                                                                                                                                                                                                                                          |
| ------------------- | ------- | -------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version`    | integer | yes      | —        | Declares the major version of the iOS schema this `[tool.kivy.ios]` table targets. `toolchain` refuses to operate on a value higher than it understands, with a clear "upgrade kivyforge" error. Independent of other platforms' overlay schema versions. |
| `bundle_id`         | string  | yes      | —        | iOS bundle identifier. Init suggests `org.example.<slug>` with a comment to change it.                                                                                                                                                               |
| `build`             | integer | no       | `1`      | Build number (`CFBundleVersion`). Increment per submission.                                                                                                                                 |
| `deployment_target` | string  | no       | `"13.0"` | Minimum iOS version. Must be >= the floor of the selected `Python.xcframework`.                                                                                                                                                                      |
| `simulator_archs`   | list of string | no | `["arm64"]` | Which **simulator** CPU architectures `kivyforge lock` pins. The device slice is always `arm64` and is not configurable. **`"arm64"` is the only allowed value**; `"x86_64"` is rejected with a migration message. Must be non-empty. See "Simulator architectures (`simulator_archs`)" below and [pylock spec §"Resolution semantics"](02-pylock-ios-spec.md#resolution-semantics). |
| `extra_index_urls`  | list of string | no | `[]`     | Supplemental pip index URLs consulted *in addition to* PyPI when resolving iOS wheels. `kivyforge lock` passes each as `--extra-index-url` to pip. Plural-by-design, channel-agnostic, and **empty by default**; PyPI is always the primary source. Each resolved wheel's source URL is pinned in `pylock.ios.toml`'s `[[packages.wheels]]` (and its index recorded under `[packages.tool.kivyforge].source_index`) regardless of which index supplied it, keeping builds reproducible. As packages publish iOS wheels to PyPI proper, configured entries go quiet on their own. See [iOS artifact distribution §"Source registry: PyPI direct"](03-artifact-distribution-ios.md#source-registry-pypi-direct-plus-configurable-supplemental-indexes) and the [common overview](../../common/00-overview.md). |
| `find_links`        | list of string | no | `[]`     | Repo-relative directories of pre-built wheels consulted during `kivyforge lock` only. Each entry is passed to pip as `--find-links` (pip's name for flat wheel directories or direct wheel URLs). Use when a dependency's iOS wheels are vendored in the repo but not published to PyPI or a supplemental index yet — e.g. locally cross-built `kivy` cp315 wheels under `wheels/`. Entries must be repo-relative (not absolute, must not escape the project directory). **Not** used at `kivyforge build` time; the lockfile's per-wheel `path` or `url` pins are authoritative after lock. See "Local wheel directories (`find_links`)" below and [pylock spec §"Locally built wheels"](02-pylock-ios-spec.md#locally-built-wheels-path). |
| `exclude`           | list of string | no | `[]`     | Canonical package names to drop from the **resolved** dependency graph when writing `pylock.ios.toml`. Use it to prune transitive dependencies a package declares but that your app never exercises at runtime on iOS — most commonly the non-runtime tail of Kivy's own wheel (`kivy-garden`, `requests` + its transitive deps, `docutils`, `pygments`). A name listed here that is *also* a direct `[project].dependencies` entry is silently ignored (you cannot exclude what you explicitly depend on). Matching is by canonical name (PEP 503). See "Excluding unused transitive dependencies (`exclude`)" below. |

### Excluding unused transitive dependencies (`exclude`)

`[project].dependencies` lists what your app needs; `exclude` lets you prune the
transitive tail that a dependency pulls in but your app never uses on iOS. The
canonical case is Kivy itself: the `kivy` wheel declares dependencies that are
useful on the desktop but dead weight in an App Store bundle (`kivy-garden`'s
download CLI cannot run on iOS at all, since the App Store prohibits dynamic
package installation; `requests`/`docutils`/`pygments` back optional widgets many
apps don't touch).

```toml
[tool.kivy.ios]
exclude = [
    "kivy-garden",   # extension registry / download CLI — never runs on iOS
    "requests",      # kivy.network.urlrequest + kivy-garden; drop if unused
    "certifi", "charset-normalizer", "idna", "urllib3",  # requests' chain
    "docutils",      # RSTDocument widget only
    "pygments",      # CodeInput widget only
]
```

Semantics:

- **Resolution-graph pruning, not bundle-file exclusion.** `exclude` removes
  whole packages from the resolved set *before* `pylock.ios.toml` is written, so
  the pruned wheels are never downloaded or installed. It is unrelated to the
  per-file bundle question discussed under `app_dir` in the common spec.
- **Direct deps win.** Any name in `exclude` that also appears in
  `[project].dependencies` is dropped from the exclusion set — an explicit
  dependency is never silently removed.
- **Canonical-name matching.** Names are compared after PEP 503 normalization, so
  `Kivy_Garden`, `kivy-garden`, and `kivy.garden` all match.
- **`kivyforge init` seeds a documented block** when `kivy` is a direct
  dependency, with one comment per entry naming the Kivy feature that needs it, so
  you know which lines are safe to delete for your specific app.

### Simulator architectures (`simulator_archs`)

A compiled iOS package ships a separate wheel per *slice*. Two are in play: the
device slice (`arm64` / `iphoneos`) and the simulator slice (`arm64` /
`iphonesimulator`). The device slice is always `arm64` and is not configurable
(there is no 32-bit iOS).

**`arm64` is the only supported simulator arch.** The `x86_64` simulator slice
existed solely to run the simulator on an Intel Mac, and macOS 27 stops
installing on Intel hardware — so that slice has no host left to run on.
`simulator_archs` defaults to `["arm64"]` and rejects `x86_64` with a migration
message.

The key is retained for schema stability and because the device/simulator split
is real, but there is only one valid value today.

Dropping the Intel slice also removes the "missing slice" fail-fast's most
common false rejection: `x86_64_iphonesimulator` was the slice most likely to be
absent upstream as the ecosystem moved to Apple Silicon, so a package shipping
only `arm64` wheels is no longer rejected for lacking it.

Changing `simulator_archs` changes `pyproject.toml`, so drift detection (see the
pylock spec) requires a re-`lock` before the next `build`, exactly like any other
schema change.

### Local wheel directories (`find_links`)

`[project].dependencies` stays PEP 508 only (`kivy>=3.0`, not a file path per package). When an iOS wheel is vendored locally, two layers are involved:

1. **Lock-time discovery (pyproject)** — `find_links` tells pip where to *search* while `kivyforge lock` resolves the graph. The name matches pip's `--find-links` flag deliberately: it is for directories of `.whl` files, not PEP 503 simple indexes.
2. **Build-time pin (lockfile)** — each resolved slice is recorded in `pylock.ios.toml` as `url` (remote) or `path` (repo-relative), per PEP 751. `kivyforge build` installs from those pins; it does not re-read `find_links`.

This is **not** the same as:

- **`extra_index_urls`** — supplemental *indexes* (`--extra-index-url`), which serve HTML/JSON simple API pages. A flat `wheels/` folder is not an index; use `find_links` instead.
- **`[tool.kivy.ios.native.xcframeworks].source`** — per-entry explicit URL or path for a *native* `.xcframework` archive, not a Python wheel. Kivy's ANGLE/SDL payloads ride inside the kivy *wheel*; they do not belong in `native.xcframeworks` for a vanilla app.

Example (local Kivy wheels until PyPI carries cp315 iOS slices):

```toml
[project]
dependencies = ["kivy>=3.0.0.dev0,<4"]

[tool.kivy.ios]
find_links = ["wheels"]
```

After `kivyforge lock`, `pylock.ios.toml` holds entries such as:

```toml
[[packages.wheels]]
name = "kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl"
path = "wheels/kivy-3.0.0.dev0-cp315-cp315-ios_13_0_arm64_iphonesimulator.whl"
hashes = { sha256 = "..." }
```

`deployment_target` in `[tool.kivy.ios]` must match the platform tags on the vendored wheels (e.g. `ios_13_0_*` vs `ios_16_0_*`); see the [pylock spec](02-pylock-ios-spec.md).

### `schema_version` evolution policy (iOS)

- Additive changes (new optional fields, new optional subtables) **do not** bump `[tool.kivy.ios].schema_version`.
- Backward-incompatible changes (rename, remove, semantics change, required-field added) **must** bump it.
- The tool supports reading the latest N major iOS schema versions (initially N=1). A separate `kivyforge migrate` verb in a future minor release converts older `[tool.kivy.ios]` blocks to the latest schema.
- When schema bumps occur, `pylock.ios.toml` records the source iOS schema version in its `[tool.kivyforge]` block as `tool_kivyforge_schema_version`.
- If the iOS backend extends a field that lives under the shared `[tool.kivy]` table (e.g. it starts consuming a newly-added `[tool.kivy].background_color`), that adoption is an iOS-side change and bumps `[tool.kivy.ios].schema_version`. Other platforms decide independently when (or whether) to adopt the same key.

### `[tool.kivy.ios.python]`

```toml
[tool.kivy.ios.python]
version = "3.15.0"
```

| Field     | Type   | Required | Default | Description                                                                                                                                                                                                                      |
| --------- | ------ | -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `version` | string | yes      | —       | Python.xcframework version. Init pins to the latest known release. The full download URL is derived (the canonical python.org distribution path is recorded in `pylock.ios.toml`'s `[tool.kivyforge]` block for reproducibility). |

Future fields (xcframework URL override, explicit SHA) are described in the [pylock spec](02-pylock-ios-spec.md) since they belong in the lock when present.

### `[tool.kivy.ios.python.build_settings]`

```toml
[tool.kivy.ios.python.build_settings]
byte_compile = "release"   # "release" | true | false — .pyc for app + pip-deps
strip_source = "release"   # "release" | true | false — drop .py once byte-compiled
```

Nested under `python` (not directly under `ios`) because `ios.build_settings`
already names the free-form `[tool.kivy.ios.xcode.build_settings]` passthrough
table — the two are unrelated despite the shared leaf name.

The same `byte_compile`/`strip_source` release tri-state as the desktop
backends (macos-spec / windows-spec / linux-spec) and Android's own
`build_settings`: `"release"` (the default) applies only to `kivyforge
package` — `build`/`run` always keep readable `.py`. `strip_source` is
ignored while `byte_compile` is off.

**Scope, and why it differs from `build`/`run`'s symlink.** `build`/`run`
stage `app/` as a **symlink** to `[tool.kivy].app_dir` (spec 06 "symlink, not
copy") for fast edit-rebuild iteration — compiling/stripping through that
symlink would delete `.py` files from the user's actual source tree, which is
never acceptable. So `package` stages a **real, disposable copy** of
`app_dir` instead, and only that copy — plus the collected `pip-deps-*`
slices, which are already host-owned build output — gets compiled/stripped.
The staged `Python.xcframework` stdlib is never touched, matching every
other platform.

Third-party pip-deps are already public (installable from PyPI); an app's own
source is not. If only one side could be protected, the app's own source is
the one worth it — but here both are covered, matching every other backend's
app+deps scope.

**Compiler selection.** The `Python.xcframework` ships no standalone
interpreter binary to shell out to — it's a linkable library, not an
executable — so unlike desktop, the "staged interpreter" rung of the ladder
never applies on iOS. Compilation always uses the interpreter running
`kivyforge` itself, if its CPython minor matches `[tool.kivy.ios.python].version`
(a `.pyc`'s magic number is keyed to minor version only, not architecture);
otherwise `byte_compile = "release"` degrades to shipping source with a
note, while `byte_compile = true` fails the build outright.

### `[tool.kivy.ios.native.xcframeworks]`

```toml
[tool.kivy.ios.native.xcframeworks]
# Empty by default for a vanilla Kivy app — the kivy iOS wheel bundles every
# native xcframework it links against (ANGLE, SDL3 family, etc.) inside the
# wheel itself. This table is for apps that need *additional* third-party
# xcframeworks not delivered via a Python wheel. `source` is always explicit —
# a direct download URL or a repo-relative path. Examples:
# Sentry        = { version = "8.49.0", source = "https://github.com/getsentry/sentry-cocoa/releases/download/8.49.0/Sentry.xcframework.zip" }
# MyNativeLib   = { version = "0.3.0",  source = "frameworks/MyNativeLib.xcframework.zip" }
```

- **Type**: table of name → inline table.
- **Semantics**: each entry declares a pure-native `.xcframework` dependency that ships to the user's `.app/Frameworks/` and is wired into Xcode's Link Binary With Libraries + Embed Frameworks phases.
- **Default**: empty. A vanilla Kivy app needs no entries here because the kivy iOS wheel bundles its native dependencies internally (see `kivy/kivy` `tools/add-ios-frameworks.py`).

Per-entry fields:

| Field     | Type   | Required                                                 | Description                                                                                                                                                                                                                                 |
| --------- | ------ | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `version` | string | yes                 | Exact version or semver spec. |
| `source`  | string | yes                 | Where to fetch the xcframework artifact (zip, tar.gz, or an unpacked `.xcframework` directory). Always **explicit**: either a **direct download URL** or a **repo-relative path** to a locally built/vendored artifact. There are no indirection keywords — the value states exactly where the artifact comes from. `kivyforge lock` reads the artifact to resolve its SHA-256 and slice list and pins them in `pylock.ios.toml`. See [iOS artifact distribution §"Distribution channel 2"](03-artifact-distribution-ios.md#distribution-channel-2-xcframework-archives). |
| `link`    | bool   | no (default `true`) | Add to Link Binary With Libraries phase. |
| `embed`   | bool   | no (default `true`) | Add to Embed Frameworks phase (copies into `.app/Frameworks/`, code-signs). |

Init never auto-populates this table: the canonical Kivy dependency set needs no entries because the kivy iOS wheel bundles its own native xcframeworks. An app that needs an *additional* third-party xcframework adds an entry here by hand, providing the name, version, and an explicit `source`.

**`source` as a URL vs. a path.** A URL is right for published SDKs and frameworks shared across projects. A repo-relative path is right for a framework the author built and versions alongside the app — because both the artifact and the path live in the repo, it resolves identically on every clone and in CI. `kivyforge build` rejects an absolute path (or one escaping the project directory) with a diagnostic. This mirrors the local-wheel mechanism in the [pylock spec](02-pylock-ios-spec.md) and follows PEP 751's path conventions, so users learn one rule for both wheels and xcframeworks.

### `[tool.kivy.ios.native.swift_packages]`

A sibling of `[tool.kivy.ios.native.xcframeworks]` for native dependencies that
are distributed **only** as Swift Package Manager packages. kivyforge supports
both **binary-target** and **source** SPM packages (Xcode compiles source
packages via its own first-class package manager). Empty by default. The full
schema (per-entry fields, version-requirement rules, lockfile shape, pbxproj
wiring, and validation) is specified in [Swift packages](06-swift-packages.md).

```toml
[tool.kivy.ios.native.swift_packages]
# Sentry = { url = "https://github.com/getsentry/sentry-cocoa", requirement = { exact = "8.49.0" }, products = ["Sentry"] }
```

### System frameworks are not declared — they link transitively

There is **no `system_frameworks` key**, and the app does not enumerate Apple SDK frameworks (`Metal`, `AVFoundation`, `CoreBluetooth`, …) anywhere. This is a direct consequence of the all-dynamic distribution model:

- Every native dependency arrives as a **dynamic** framework — the kivy wheel's bundled xcframeworks (ANGLE, SDL3 family), the per-module `.framework`s `install_python` builds from each `.so`, and `Python.framework` itself. A dynamic framework records the Apple SDK frameworks it needs as `LC_LOAD_DYLIB` load commands **inside its own Mach-O**, set when *that* framework was built. At app launch `dyld` walks the dependency graph transitively (app → `kivy…framework` → `Metal`/`AVFoundation`/…), so the app target never has to re-declare them.
- The app target compiles only the `main.m` bootstrap, which references just Foundation/UIKit/the Python C API. Those Foundation/UIKit references are the **bootstrap baseline** the toolchain links automatically (see [Xcode project generation](05-xcode-project-generation.md)); nothing in the dependency graph needs app-level declaration.
- Calling a system API from Python via `pyobjus` is **dynamic loading** at runtime (`pyobjus.dylib_manager.load_framework(...)` / the Objective-C runtime), which involves no link-time symbol references and therefore no Xcode link entry either.

The only case that historically required an explicit per-app framework list was **static** linking (the kivy-ios 2.x recipe model linked static `.a` libraries into the app binary, so the app target had to resolve every transitive system symbol). kivyforge is all-dynamic, so that requirement is gone. If a future need arises (e.g. weak-linking an SDK framework for availability that the *app's own compiled code* references), it can be added as an additive, `schema_version`-bumping change.

### `[tool.kivy.ios.entitlements]`

```toml
[tool.kivy.ios.entitlements]
"com.apple.developer.healthkit" = true                                  # bool
"aps-environment" = "development"                                       # string
"com.apple.security.application-groups" = ["group.org.example.myapp"]   # list
```

- **Type**: table of plist key → plist value (bool, string, or list).
- **Semantics**: written verbatim into the generated `<app>.entitlements` file. Pass-through — kivyforge never rewrites a value or infers a key you did not declare.
- iOS-only.

> **Entitlements are not self-service.** Most entitlement keys correspond to a
> **capability that must be enabled on your App ID** at developer.apple.com;
> `codesign` requires the app's entitlements to be a *subset* of what the
> provisioning profile grants. Declaring a key here does not create that
> capability — it only asks for it. Because a mismatch otherwise fails deep
> inside `xcodebuild` with a message that names neither this table nor the
> portal action that fixes it, `kivyforge build` and `kivyforge run --device`
> cross-check declared keys against the pinned profile before signing, and
> `kivyforge doctor` reports the same comparison. See [iOS CLI §`kivyforge build`](04-cli-ios.md#kivyforge-build) for
> the exact behavior under automatic vs. manual signing.

### `[tool.kivy.ios.signing]`

```toml
[tool.kivy.ios.signing]
team_id = "ABCDE12345"
identity = "Apple Development"
provisioning_profile = ""
auto_signing = true
upload_symbols = true
```

| Field                  | Type   | Required | Default               | Description                                                  |
| ---------------------- | ------ | -------- | --------------------- | ------------------------------------------------------------ |
| `team_id`              | string | no       | `""`                  | Apple Developer team identifier. Required for device builds and release exports. |
| `identity`             | string | no       | `"Apple Development"` | Code signing identity, applied to `--device` debug builds. **Not applied to `--release`** — a distribution archive/export needs Xcode's automatic signing to pick the Distribution certificate matching `--export-method`; pin one explicitly via `--signing-identity`/`KIVYFORGE_SIGNING_IDENTITY` if needed (see [iOS CLI §`kivyforge build`](04-cli-ios.md#kivyforge-build)). |
| `provisioning_profile` | string | no       | `""`                  | Provisioning profile name or UUID (empty for auto). |
| `auto_signing`         | bool   | no       | `true`                | Use Xcode's automatic signing (`CODE_SIGN_STYLE = Automatic`). |
| `upload_symbols`       | bool   | no       | `true`                | Sets the `uploadSymbols` key in the generated `ExportOptions.plist` used by `--release` exports (controls dSYM inclusion in the `.ipa`; `--release` only — see [iOS CLI §`kivyforge build`](04-cli-ios.md#kivyforge-build)). Set to `false` if you don't use a crash-reporting service and want a smaller export artifact; the `.xcarchive` still retains dSYMs for manual upload. |

iOS-only.

### `[tool.kivy.ios.privacy_manifest]`

```toml
[tool.kivy.ios.privacy_manifest]
source = "privacy/PrivacyInfo.xcprivacy"
```

| Field    | Type   | Required | Description                                                                                                                                                                                                                                                                                                                                                     |
| -------- | ------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `source` | string | no       | Repo-relative path to a hand-authored `PrivacyInfo.xcprivacy` plist. When set, `kivyforge build` copies this file into the project's Copy Bundle Resources phase as the app-level privacy manifest. When absent, the toolchain generates a **minimal stub** (`NSPrivacyTracking = false`, empty `NSPrivacyTrackingDomains`, `NSPrivacyCollectedDataTypes`, and `NSPrivacyAccessedAPITypes` arrays). |

**App Store requirement.** Apple has required an app-level `PrivacyInfo.xcprivacy` for all new and updated submissions since May 2024. The generated stub is valid for apps that perform no tracking, collect no data, and use none of Apple's [required-reason APIs](https://developer.apple.com/documentation/bundleresources/privacy-manifest-files/describing-use-of-required-reason-api). Any app that *does* use required-reason APIs (file timestamps, system boot time, disk space, active keyboard, user defaults) must supply a `source` declaring them — the stub will be rejected by App Store Connect validation.

**Native xcframework privacy manifests.** Each `.xcframework` in `Frameworks/` (whether wheel-embedded or user-declared via `[tool.kivy.ios.native.xcframeworks]`) must include its own `PrivacyInfo.xcprivacy` **inside the xcframework bundle** if it uses required-reason APIs. This is the responsibility of the framework or wheel author, not kivyforge. `kivyforge doctor` warns if any xcframework in `Frameworks/` is missing a `PrivacyInfo.xcprivacy` entirely (see [iOS CLI](04-cli-ios.md)).

### `[tool.kivy.ios.info_plist]`

```toml
[tool.kivy.ios.info_plist]
NSCameraUsageDescription = "Used for QR code scanning."
UIFileSharingEnabled = true
```

- **Type**: table of string → string, bool, integer, or list (TOML native types, mapped to plist equivalents).
- **Semantics**: each key/value is merged into the generated `<app>-Info.plist`. Useful for usage-description strings (required by iOS for privacy-sensitive APIs), capability flags, and any other plist key that kivyforge does not expose through a dedicated schema field.
- **Conflict handling**: user-supplied keys that collide with kivyforge-managed keys are rejected with a diagnostic listing both the offending key and the kivyforge field that controls it.

**kivyforge-managed `Info.plist` keys** — these are written automatically from the schema and cannot be set via `[tool.kivy.ios.info_plist]`:

| Managed key | Source |
|-------------|--------|
| `CFBundleName` | `[project].name` |
| `CFBundleDisplayName` | `[tool.kivy].display_name` (falls back to `[project].name`) |
| `CFBundleIdentifier` | `[tool.kivy.ios].bundle_id` |
| `CFBundleShortVersionString` | `[project].version` |
| `CFBundleVersion` | `[tool.kivy.ios].build` |
| `MinimumOSVersion` | `[tool.kivy.ios].deployment_target` |
| `UISupportedInterfaceOrientations` | `[tool.kivy].orientation` |
| `UISupportedInterfaceOrientations~ipad` | toolchain (always all four orientations — Apple App Store requirement as of Xcode 16 / iOS 18; the declared `[tool.kivy].orientation` constrains iPhone only) |
| `LSRequiresIPhoneOS` | toolchain (always `true`) |
| `UIApplicationSceneManifest` | toolchain (always written — SDL3 on iOS 13+ uses the UIScene lifecycle; without it iOS never foregrounds the scene and Metal rejects all GPU work) |
| `CFBundlePackageType` | toolchain (always `APPL`) |
| `CFBundleInfoDictionaryVersion` | toolchain (plist format version boilerplate) |
| `CFBundleExecutable` | set by Xcode |
| `NSHumanReadableCopyright` | first `[project].authors` entry's `name` (when present) |

Two generator-written keys are deliberately **not** managed and may be overridden via `[tool.kivy.ios.info_plist]`: `UIApplicationSupportsIndirectInputEvents` (default `true`; SDL3 uses it for indirect input / mouse events — override to opt out) and `UILaunchStoryboardName` (written automatically when `[tool.kivy.ios.splash]` is configured; a user-supplied value takes precedence, for apps that maintain their own launch storyboard).

### `[tool.kivy.ios.xcode.build_settings]`

```toml
[tool.kivy.ios.xcode.build_settings]
SWIFT_VERSION = "5.0"
ENABLE_BITCODE = "NO"
GCC_OPTIMIZATION_LEVEL = "s"
```

- **Type**: table of string → string.
- **Semantics**: each key/value is written into the generated `.xcodeproj`'s build settings (`buildSettings` dictionary) for the application target. Free-form escape hatch for users who need specific Xcode build configurations not exposed elsewhere.
- **Caveats**: `kivyforge build` reserves the keys it manages. User-supplied values for any reserved key are rejected with a diagnostic that names the key and the kivyforge field that controls it. The reserved set is:

| Reserved key | Controlled by |
|---|---|
| `INFOPLIST_FILE` | toolchain (path to generated plist) |
| `PRODUCT_BUNDLE_IDENTIFIER` | `[tool.kivy.ios].bundle_id` |
| `IPHONEOS_DEPLOYMENT_TARGET` | `[tool.kivy.ios].deployment_target` |
| `TARGETED_DEVICE_FAMILY` | toolchain (always `1,2` — iPhone + iPad) |
| `CODE_SIGN_STYLE` | `[tool.kivy.ios.signing].auto_signing` |
| `CODE_SIGN_IDENTITY` | `[tool.kivy.ios.signing].identity` |
| `DEVELOPMENT_TEAM` | `[tool.kivy.ios.signing].team_id` |
| `PROVISIONING_PROFILE_SPECIFIER` | `[tool.kivy.ios.signing].provisioning_profile` |
| `ENABLE_USER_SCRIPT_SANDBOXING` | toolchain (must be `NO` for Build Python phase) |
| `ENABLE_TESTABILITY` | toolchain |
| `FRAMEWORK_SEARCH_PATHS` | toolchain |
| `HEADER_SEARCH_PATHS` | toolchain |
| `LD_RUNPATH_SEARCH_PATHS` | toolchain (`@executable_path/Frameworks` for embedded frameworks) |
| `GCC_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER` | toolchain |

See also [Xcode project generation §"Toolchain-managed build settings"](05-xcode-project-generation.md#toolchain-managed-build-settings) for the rationale behind each toolchain-managed entry.

## Concrete example

A real-world `pyproject.toml` for a typical Kivy 3.x app, iOS-focused:

```toml
[project]
name = "touchtracer"
version = "1.0.0"
description = "Touchtracer demo"
requires-python = ">=3.15"
dependencies = [
    "kivy>=3.0,<4",
]
authors = [{ name = "Kivy Team", email = "team@kivy.org" }]

[tool.kivy]
display_name = "Touchtracer"
app_dir = "src"
entry_point = "main"
orientation = ["portrait", "portrait-upside-down", "landscape-left", "landscape-right"]

[tool.kivy.ios]
schema_version = 1
bundle_id = "org.kivy.touchtracer"
build = 1
deployment_target = "13.0"

[tool.kivy.ios.python]
version = "3.15.0"

[tool.kivy.ios.icons]
source = "assets/icon.png"        # 1024×1024 PNG

[tool.kivy.ios.splash]
source = "assets/splash.png"
background = "#000000"

[tool.kivy.ios.native.xcframeworks]
# Empty — the kivy wheel bundles every native xcframework it needs.

# find_links = ["wheels"]   # uncomment when vendoring local iOS wheels for lock

# Note: Apple SDK frameworks Kivy uses (Metal for rendering, AVFoundation for
# video, …) are not listed anywhere. They link transitively through the
# dynamic frameworks that reference them; see "System frameworks are not
# declared" above.

[tool.kivy.ios.signing]
team_id = ""
auto_signing = true
```

## Validation rules (iOS)

`kivyforge lock` and `kivyforge build` reject any `pyproject.toml` that:

1. Lacks a `[project]` table or omits `[project].name` / `[project].version`.
2. Lacks `[tool.kivy.ios]` when running an iOS command. (`[tool.kivy]` alone is not a buildable target.)
3. Lacks `[tool.kivy.ios].schema_version` or specifies an unsupported value.
4. Lacks `[tool.kivy.ios].bundle_id`.
5. Has `[tool.kivy].entry_point` that isn't a valid Python identifier (or dotted identifier).
6. Omits `[tool.kivy].app_dir`, or sets it to the project root (`"."`), an empty string, an absolute path, or a path that escapes the project directory. `app_dir` must name a subdirectory of the project.
7. Has `[tool.kivy].orientation` values outside the allowed set.
8. Sets reserved keys under `[tool.kivy.ios.xcode.build_settings]`.
9. Specifies a Python `version` in `[tool.kivy.ios.python]` whose `Python.xcframework` doesn't exist (verified at lock time against python.org).
10. Declares `[project].requires-python` incompatible with `[tool.kivy.ios.python].version`.
11. Sets `[tool.kivy.ios].deployment_target` lower than the minimum iOS version supported by the selected `Python.xcframework` (verified at lock time; the xcframework metadata declares its floor; e.g. Python 3.15 requires iOS 13.0+).
12. Sets `[tool.kivy.ios].find_links` entries that are absolute paths, empty, or paths that escape the project directory.
13. Sets `[tool.kivy.ios].simulator_archs` to a non-list, a list containing non-strings, an empty list, or any value other than `"arm64"` (notably `"x86_64"`, which is rejected with a migration message).

Validation errors are printed with the offending line number (TOML parsers expose this) and a remediation hint.
