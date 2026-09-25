---
title: "[tool.kivy.android] reference"
sources:
  - kivyforge/config/model.py
  - kivyforge/config/loader.py
  - docs/design/platforms/android/01-pyproject-android.md
  - docs/design/platforms/android/07-signing-prerequisites-android.md
  - examples/mobile/hello-android/pyproject.toml
  - examples/mobile/qr-maven/pyproject.toml
---

# `[tool.kivy.android]` reference

The Android overlay of `pyproject.toml`. For a task-oriented walkthrough, see
[Configure your Android app](../../guides/android/configure.md).

kivyforge validates the value of every key it reads and fails with a message
that names the key. It ignores keys it does not recognize, so check the spelling
of a key that seems to have no effect. Any edit to `pyproject.toml` makes the lock
stale; run `kivyforge lock -p android` afterward.

## `[tool.kivy.android]`

| Key | Type | Default | Description |
|---|---|---|---|
| `schema_version` | integer | required | Overlay schema version. Must be `1`. |
| `package` | string | required | The applicationId: two or more dot-separated Java identifiers, for example `org.example.myapp`. |
| `version_code` | integer or `"auto"` | `1` | Google Play version code. An integer is used as is (at most 2,100,000,000). `"auto"` derives it from a final `MAJOR.MINOR.PATCH` `[project].version` as `MAJOR*1000000 + MINOR*10000 + PATCH*100 + build`. |
| `build` | integer | `0` | Re-upload counter from `0` to `99`. Used only when `version_code = "auto"`. |
| `min_sdk` | integer | `24` | Minimum Android API level. Values below `24` are rejected. |
| `target_sdk` | integer | `35` | Target API level. Must be at least `min_sdk`. |
| `compile_sdk` | integer | value of `target_sdk` | API level the project compiles against. Must be at least `target_sdk`. |
| `kivy_generation` | integer | `2` | `2` for Kivy 2.3.1 on SDL2, `3` for Kivy 3.0 on SDL3. |
| `abis` | list of string | `["arm64_v8a", "x86_64"]` | ABIs (application binary interfaces) to build. Only `arm64_v8a` and `x86_64` are accepted. |
| `extra_index_urls` | list of string | `[]` | Extra package indexes to resolve wheels from, such as the mobile wheel index. |
| `find_links` | list of string | `[]` | Local directories of wheels. |
| `exclude` | list of string | `[]` | Dependency names to prune from the resolve. |
| `base_theme` | string | `"Theme.Material3.DayNight.NoActionBar"` | Parent theme of the generated app theme. |
| `gradle_properties` | table | `{}` | Extra `gradle.properties` entries. `android.useAndroidX` is reserved. |

## `[tool.kivy.android.python]`

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | string | required | CPython version of the python.org Android runtime, for example `"3.14.6"`. Must satisfy `[project].requires-python`. |

## `[tool.kivy.android.permissions]`

| Key | Type | Default | Description |
|---|---|---|---|
| `uses` | list of string | `[]` | Permissions to request. Bare names such as `"CAMERA"` get the `android.permission.` prefix. |
| `features` | list of table | `[]` | Each `{ name, required }` entry becomes a `<uses-feature>` element. `required` defaults to `true`. An entry overrides the synthesized feature of the same name. |
| `auto_features` | bool | `true` | Add a non-required `<uses-feature>` for each permission that implies hardware, such as `CAMERA`. |

## `[tool.kivy.android.icons]`

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | string | — | Project-relative path to a 1024x1024 PNG. kivyforge generates the adaptive icon set from it, which needs the `kivyforge[android]` extra (Pillow). Without it, a plain default icon is generated. |
| `background` | string | white | `#rrggbb` color or project-relative image path for the adaptive icon background layer. |
| `monochrome` | string | — | Project-relative path to a monochrome layer for themed icons. Requires `compile_sdk` 33 or higher. |

## `[tool.kivy.android.splash]`

A splash screen is generated only when `source` is set. It requires `compile_sdk`
31 or higher.

| Key | Type | Default | Description |
|---|---|---|---|
| `source` | string | — | Project-relative path to the centered splash icon: a PNG, or an animated vector drawable XML file. |
| `background` | string | white | `#rrggbb` background color. |
| `icon_background` | string | — | `#rrggbb` color of a circle behind the icon. |
| `animation_duration` | integer | — | Animation length in milliseconds, for an animated `source`. |
| `branding` | string | — | Project-relative path to an image shown at the bottom of the splash screen. |

## `[tool.kivy.android.gradle]`

| Key | Type | Default | Description |
|---|---|---|---|
| `dependencies` | list of string | `[]` | Maven coordinates in `group:artifact:version` form. Dynamic versions (`+`, ranges, `latest.*`) are rejected. |
| `repositories` | list of string | `[]` | Extra Maven repository URLs, in addition to `google()` and `mavenCentral()`. |

## `[tool.kivy.android.native.aars]` and `[tool.kivy.android.native.jars]`

Each table maps a library name to an inline table:

| Key | Type | Default | Description |
|---|---|---|---|
| `version` | string | required | Exact version of the archive. |
| `source` | string | required | A download URL or a project-relative path. Absolute paths and paths outside the project are rejected. |

```toml
[tool.kivy.android.native.aars]
LocalWidget = { version = "0.2.0", source = "libs/LocalWidget-0.2.0.aar" }
```

## `[tool.kivy.android.src]`

| Key | Type | Default | Description |
|---|---|---|---|
| `java` | list of string | `[]` | Project-relative Java source directories to compile into the app. |
| `kotlin` | list of string | `[]` | Project-relative Kotlin source directories. A non-empty list enables the Kotlin Gradle plugin. |

## `[[tool.kivy.android.include_files]]`

An array of tables. Each entry copies project files into the generated Android
project.

| Key | Type | Default | Description |
|---|---|---|---|
| `dest` | string | required | Destination directory, relative to the generated `<app>-android/` project. |
| `sources` | list of string | required | Project-relative files or directories to copy. Each must exist. |

## `[[tool.kivy.android.services]]`

An array of tables. See [Add a background service](../../guides/android/services.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | A Java identifier. The generated class is `org.kivy.android.Service<name>`. |
| `entry_point` | string | required | Python module, optionally dotted, that runs in the service. |
| `exported` | bool | `false` | Value of `android:exported`. |
| `foreground` | bool | `false` | Make this a foreground service. Requires `foreground_service_type` and `notification`. |
| `foreground_service_type` | string | — | One of `camera`, `connectedDevice`, `dataSync`, `health`, `location`, `mediaPlayback`, `mediaProcessing`, `mediaProjection`, `microphone`, `phoneCall`, `remoteMessaging`, `shortService`, `specialUse`, `systemExempted`. |
| `notification` | table | — | `channel_id`, `channel_name`, `title`, and `text` (all required strings), and an optional `icon` resource name. |

## `[[tool.kivy.android.activities]]`

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Fully qualified Java class name of an activity you supply through `[tool.kivy.android.src]`. |
| `exported` | bool | `false` | Value of `android:exported`. |

## `[[tool.kivy.android.intent_filters]]`

Each entry becomes an `<intent-filter>` on the main activity.

| Key | Type | Default | Description |
|---|---|---|---|
| `action` | string | required | Intent action, for example `android.intent.action.VIEW`. |
| `categories` | list of string | `[]` | Intent categories. |
| `data` | list of table | `[]` | `<data>` attributes. Allowed keys: `scheme`, `host`, `port`, `path`, `pathPrefix`, `pathPattern`, `mimeType`. |

## `[tool.kivy.android.manifest]`

| Key | Type | Default | Description |
|---|---|---|---|
| `application` | table | `{}` | Attributes added to `<application>`. `android:label`, `android:icon`, `android:roundIcon`, `android:theme`, and `android:extractNativeLibs` are managed by kivyforge and rejected. |
| `activity` | table | `{}` | Attributes added to the main `<activity>`. `android:name`, `android:label`, `android:screenOrientation`, and `android:theme` are rejected. |
| `placeholders` | table | `{}` | Manifest placeholders, string to string. |
| `allow_exported` | list of string | `[]` | Fully qualified component names that the release manifest policy accepts as exported. |
| `extra_manifest_xml` | string | `""` | XML inserted inside `<manifest>`. Must be well formed. |
| `extra_application_xml` | string | `""` | XML inserted inside `<application>`. |
| `extra_activity_xml` | string | `""` | XML inserted inside the main `<activity>`. |

## `[tool.kivy.android.signing]`

Release signing for `kivyforge package`. See
[Sign and publish to Google Play](../../guides/android/signing.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `keystore` | string | — | Path to the release keystore, relative to the project or absolute. Overridden by `--keystore`. |
| `key_alias` | string | — | Key alias in the keystore. Overridden by `--key-alias`. |
| `store_password_env` | string | `"KIVYFORGE_KEYSTORE_PASSWORD"` | Name of the environment variable that holds the keystore password. |
| `key_password_env` | string | `"KIVYFORGE_KEY_PASSWORD"` | Name of the environment variable that holds the key password. If it is unset, the keystore password is used. |
| `v1_signing` | bool | `false` | APK Signature Scheme v1 (JAR signing). |
| `v2_signing` | bool | `true` | APK Signature Scheme v2. |
| `v3_signing` | bool | `true` | APK Signature Scheme v3, which supports key rotation. |
| `v4_signing` | bool | `false` | APK Signature Scheme v4, for incremental installs. |

The `v1_signing` to `v4_signing` toggles apply to APK output. Passwords never go
in `pyproject.toml`.

## `[tool.kivy.android.build_settings]`

| Key | Type | Default | Description |
|---|---|---|---|
| `byte_compile` | bool or `"release"` | `"release"` | Compile the Python payload to `.pyc`. `"release"` applies to release builds only. |
| `strip_source` | bool or `"release"` | `"release"` | Drop `.py` files after compiling. Ignored when `byte_compile` is off. |
| `strip_native_libs` | bool or `"release"` | `"release"` | Strip debug symbols from the shipped `.so` files. |
| `debug_symbols` | string | `"symbol_table"` | Native debug symbols to export: `symbol_table`, `full`, or `none`. |
| `minify` | bool | `false` | Enable R8 for release builds. |
| `shrink_resources` | bool | `false` | Remove unused resources. Requires `minify = true`. |
| `multidex` | bool | `true` | Enable multidex. |

## Example

```toml
[tool.kivy.android]
schema_version = 1
package = "org.kivyforge.helloandroid"
min_sdk = 24
target_sdk = 35
kivy_generation = 2
abis = ["arm64_v8a", "x86_64"]
extra_index_urls = ["https://elliotgarbus.github.io/kivy-mobile-wheels/simple/"]
exclude = ["kivy-garden", "docutils", "pygments"]

[tool.kivy.android.python]
version = "3.14.6"

[tool.kivy.android.permissions]
uses = ["INTERNET"]
```

## What's next

- [Configure your Android app](../../guides/android/configure.md)
- [Add Java libraries](../../guides/android/java-libraries.md)
- [Add a background service](../../guides/android/services.md)
