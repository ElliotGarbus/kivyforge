---
title: "[tool.kivy.ios] reference"
sources:
  - docs/design/platforms/ios/01-pyproject-ios.md
  - docs/design/platforms/ios/06-swift-packages.md
  - docs/design/platforms/ios/08-signing-prerequisites-ios.md
  - examples/mobile/hello-kivy/pyproject.toml
  - examples/mobile/keychain-spm/pyproject.toml
---

# `[tool.kivy.ios]` reference

The iOS overlay. kivyforge rejects a value of the wrong type rather than
converting it. For tasks, see [Configure your iOS app](../../guides/ios/configure.md).

## `[tool.kivy.ios]`

| Key | Type | Default | Description |
|---|---|---|---|
| `schema_version` | integer | required | Overlay schema version. Set to `1`. |
| `bundle_id` | string | required | Bundle identifier, in reverse-DNS form. Letters, digits, hyphens, and periods only; no underscores. |
| `build` | integer | `1` | Build number (`CFBundleVersion`). |
| `deployment_target` | string | `"13.0"` | Minimum iOS version, for example `"16.0"`. |
| `simulator_archs` | list of string | `["arm64"]` | Simulator architectures to pin. `"arm64"` is the only valid value. |
| `extra_index_urls` | list of string | `[]` | Extra package indexes, such as the mobile wheel index. |
| `find_links` | list of string | `[]` | Project-relative directories of prebuilt wheels, searched during `lock` only. |
| `exclude` | list of string | `[]` | Package names to drop from the resolve. |

## `[tool.kivy.ios.python]`

Required.

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | string | required | CPython version. Must match a `Python.xcframework` that python.org publishes for iOS, for example `"3.15.0b4"`. `[project].requires-python` must allow it. |

## `[tool.kivy.ios.python.build_settings]`

| Key | Type | Default | Description |
|---|---|---|---|
| `byte_compile` | bool or `"release"` | `"release"` | Compile your app and its dependencies to `.pyc`. `"release"` applies to release exports only. |
| `strip_source` | bool or `"release"` | `"release"` | Remove `.py` files after compiling. |

## `[tool.kivy.ios.icons]`

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | string | none | Path to a 1024x1024 PNG. Apple requires it to be opaque and full-bleed. |

## `[tool.kivy.ios.splash]`

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | string | none | Path to the image centered on the generated launch screen. |
| `background` | string | none | Launch screen background color, as `#rrggbb`. |

## `[tool.kivy.ios.signing]`

| Key | Type | Default | Description |
|---|---|---|---|
| `team_id` | string | `""` | Apple Developer Team ID. Required for device builds and release exports. Overridden by `--team-id`, then `KIVYFORGE_TEAM_ID`. |
| `identity` | string | `"Apple Development"` | Signing identity for device debug builds. Not passed to release exports. Overridden by `--signing-identity`, then `KIVYFORGE_SIGNING_IDENTITY`. |
| `provisioning_profile` | string | `""` | Provisioning profile to pin: its name or UUID, or a path to a `.mobileprovision` file. Requires `auto_signing = false`. Empty means Xcode chooses. See the note below. |
| `auto_signing` | bool | `true` | Use Xcode automatic signing. When `true`, signing `xcodebuild` runs get `-allowProvisioningUpdates`. |
| `upload_symbols` | bool | `true` | Value of `uploadSymbols` in the export options for release exports. |

!!! note "`provisioning_profile` value"
    Set it the way Xcode does, to the profile's **name** or **UUID**. kivyforge
    passes it to Xcode as `PROVISIONING_PROFILE_SPECIFIER`, and `doctor` and the
    entitlements check find the matching profile among those installed on the
    Mac (`~/Library/Developer/Xcode/UserData/Provisioning Profiles` and
    `~/Library/MobileDevice/Provisioning Profiles`). If several installed
    profiles share the name, the newest one is used.

    You can instead give a path to a downloaded `.mobileprovision` file,
    absolute or relative to the project. kivyforge reads the file and passes its
    UUID to Xcode. Xcode signs only with installed profiles, so install the file
    too (double-click it); `doctor` warns if it is not installed.

    A pinned profile is manual signing, so set `auto_signing = false`: Xcode
    refuses a pin under automatic signing. The profile must be one created at
    developer.apple.com, not an Xcode-managed `iOS Team Provisioning Profile`,
    which manual signing rejects. A device or release build stops before
    `xcodebuild` on either, and `doctor` fails on both.

## `[tool.kivy.ios.entitlements]`

A table of entitlement keys and values (bool, string, or list), written verbatim
to the app's `.entitlements` file. Each capability you declare must be enabled
on your App ID. See [Sign your iOS app](../../guides/ios/signing.md).

## `[tool.kivy.ios.info_plist]`

A table of keys merged into the generated `Info.plist`, such as usage-description
strings. These keys are managed by kivyforge and rejected here:

`CFBundleName`, `CFBundleDisplayName`, `CFBundleIdentifier`,
`CFBundleShortVersionString`, `CFBundleVersion`, `MinimumOSVersion`,
`UISupportedInterfaceOrientations`, `UISupportedInterfaceOrientations~ipad`,
`LSRequiresIPhoneOS`, `CFBundlePackageType`, `CFBundleInfoDictionaryVersion`,
`CFBundleExecutable`, `NSHumanReadableCopyright`, `UIApplicationSceneManifest`.

## `[tool.kivy.ios.xcode.build_settings]`

A table of extra Xcode build settings applied to the generated project. Every
value must be a string, for example `SWIFT_VERSION = "5.0"`. These settings are
managed by kivyforge and rejected here:

`INFOPLIST_FILE`, `PRODUCT_BUNDLE_IDENTIFIER`, `IPHONEOS_DEPLOYMENT_TARGET`,
`TARGETED_DEVICE_FAMILY`, `DEBUG_INFORMATION_FORMAT`, `CODE_SIGN_STYLE`,
`CODE_SIGN_IDENTITY`, `DEVELOPMENT_TEAM`, `PROVISIONING_PROFILE_SPECIFIER`,
`ENABLE_USER_SCRIPT_SANDBOXING`, `ENABLE_TESTABILITY`, `FRAMEWORK_SEARCH_PATHS`,
`HEADER_SEARCH_PATHS`, `LD_RUNPATH_SEARCH_PATHS`,
`GCC_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER`.

## `[tool.kivy.ios.privacy_manifest]`

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | string | none | Path to your own `PrivacyInfo.xcprivacy`. When unset, kivyforge generates a minimal manifest that declares no tracking, no collected data, and no required-reason APIs. |

## `[tool.kivy.ios.native.xcframeworks]`

Each entry is `NAME = { ... }` and declares a native `.xcframework` that does not
come from a wheel. A standard Kivy app needs none.

| Field | Type | Default | Description |
|---|---|---|---|
| `version` | string | required | Version of the framework. |
| `source` | string | required | An `http://` or `https://` URL, or a project-relative path. |
| `link` | bool | `true` | Link the framework. |
| `embed` | bool | `true` | Embed the framework in the app. |

## `[tool.kivy.ios.native.swift_packages]`

Each entry is `NAME = { ... }` and declares a Swift Package Manager dependency.
See [Add a Swift package](../../guides/ios/swift-packages.md).

| Field | Type | Default | Description |
|---|---|---|---|
| `url` | string | none | Remote package URL. Set exactly one of `url` and `path`. |
| `path` | string | none | Project-relative directory of a local package. |
| `requirement` | table | required with `url` | Exactly one rule: `exact`, `from`, `up_to_next_minor`, `branch`, or `revision` (a string), or `range` (a list of two versions). |
| `products` | list of string | required | Library products to use. Must not be empty. |
| `link` | bool | `true` | Link the products. |
| `embed` | bool | `false` with `url`, `true` with `path` | Embed the products in the app. |

## Example

```toml
[tool.kivy.ios]
schema_version = 1
bundle_id = "org.example.hello-kivy"
build = 1
deployment_target = "16.0"
extra_index_urls = ["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]
exclude = ["kivy-garden", "docutils", "pygments"]

[tool.kivy.ios.python]
version = "3.15.0b4"

[tool.kivy.ios.signing]
team_id = "ABCDE12345"
auto_signing = true
```

## What's next

- [Configure your iOS app](../../guides/ios/configure.md).
- [Add a Swift package to your iOS app](../../guides/ios/swift-packages.md).
- [Sign your iOS app](../../guides/ios/signing.md).
