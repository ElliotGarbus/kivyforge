---
title: "[tool.kivy.macos] reference"
sources:
  - docs/design/platforms/macos/macos-spec.md
  - docs/design/platforms/macos/signing-prerequisites-macos.md
  - examples/desktop/dice-roller/pyproject.toml
---

# `[tool.kivy.macos]` reference

The macOS overlay. For tasks, see [Build a macOS .app](../../guides/macos/build.md).

## `[tool.kivy.macos]`

| Key | Type | Default | Description |
|---|---|---|---|
| `schema_version` | integer | required | Overlay schema version. Set to `1`. |
| `bundle_id` | string | required | Bundle identifier, in reverse-DNS form. Letters, digits, hyphens, and periods only; no underscores. |
| `build` | integer | `1` | Build number. |
| `minimum_system_version` | string | `"11.0"` | Minimum macOS version (`LSMinimumSystemVersion`). Must not be below the bundled runtime's floor. |
| `archs` | list of string | `["arm64"]` | Build architectures. `"arm64"` is the only valid value; `"x86_64"` is rejected. `universal2` wheels are still accepted as dependencies. |
| `extra_index_urls` | list of string | `[]` | Extra package indexes. |
| `find_links` | list of string | `[]` | Project-relative directories of prebuilt wheels, searched during `lock` only. |
| `exclude` | list of string | `[]` | Package names to drop from the resolve. |

## `[tool.kivy.macos.python]`

Required.

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | string | required | CPython version from python-build-standalone, for example `"3.13.14"`. `[project].requires-python` must allow it. |

## `[tool.kivy.macos.icons]`

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | string | none | Path to a 1024x1024 PNG, rendered to `.icns`. Transparent rounded corners are allowed. |

## `[tool.kivy.macos.signing]`

| Key | Type | Default | Description |
|---|---|---|---|
| `identity` | string | `""` | Developer ID Application identity. Set alone, `package` signs without notarizing. Overridden by `package --signing-identity`. |
| `team_id` | string | `""` | Team ID. Recorded for reference; the build does not use it. |
| `notary_profile` | string | `""` | Keychain profile name created with `xcrun notarytool store-credentials`. With `identity`, `package` also notarizes and staples. Overridden by `package --notary-profile`. |

Without an `identity`, `package` produces an ad-hoc-signed `.app` and reports a
`KF-SIGNING-UNCONFIGURED` warning. See
[Sign, notarize, and staple a macOS app](../../guides/macos/signing.md).

## `[tool.kivy.macos.entitlements]`

A table of entitlement keys and values, merged over the default Hardened Runtime
entitlements; your values win. Applied only to Developer ID signing. When an
`identity` is set, `com.apple.security.get-task-allow = true` is rejected, because
notarization always rejects it.

## `[tool.kivy.macos.native.binaries]`

Each entry is `NAME = { version = "...", source = "..." }` and declares a native
binary that does not come from a wheel. `source` is an `http://` or `https://`
URL, or a project-relative path. The binary is staged into
`Contents/Resources/bin`. See
[Ship native binaries](../../guides/cross-platform/native-binaries.md).

## `[tool.kivy.macos.build_settings]`

| Key | Type | Default | Description |
|---|---|---|---|
| `byte_compile` | bool or `"release"` | `"release"` | Compile your app and its dependencies to `.pyc`. `"release"` applies to `package` and `run --release` only. |
| `strip_source` | bool or `"release"` | `"release"` | Remove `.py` files after compiling. |

## Example

```toml
[tool.kivy.macos]
schema_version = 1
bundle_id = "org.example.dice-roller"
archs = ["arm64"]

[tool.kivy.macos.python]
version = "3.13.14"

[tool.kivy.macos.icons]
source = "assets/icon.png"

[tool.kivy.macos.signing]
identity = "Developer ID Application: Jane Doe (ABCDE12345)"
team_id = "ABCDE12345"
notary_profile = "kivyforge-notary"
```

## What's next

- [Build a macOS .app](../../guides/macos/build.md).
- [Sign, notarize, and staple a macOS app](../../guides/macos/signing.md).
