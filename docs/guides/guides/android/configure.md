---
title: Configure your Android app
sources:
  - docs/design/platforms/android/01-pyproject-android.md
  - kivyforge/config/loader.py
  - examples/mobile/hello-android/pyproject.toml
---

# Configure your Android app

Your Android configuration lives in the `[tool.kivy.android]` overlay of your
`pyproject.toml`. This page covers the settings you change most often. For every
key, see the [Android overlay reference](../../reference/pyproject/android.md).

## Before you begin

- [Install kivyforge](../../get-started/install.md) and the Android toolchain:
  a JDK 17 or later, the Android SDK, and the Android NDK (Native Development Kit).
- Have a project with `[project]` and `[tool.kivy]` sections. See
  [Project configuration](../../concepts/configuration.md).

## Start from a minimal overlay

This overlay is the one the `hello-android` example uses:

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

`schema_version`, `package`, and `[tool.kivy.android.python].version` are
required. The other keys shown have defaults, listed in the reference.

## Key settings

`package`
:   The applicationId, in reverse-DNS form (`org.example.myapp`). It is your
    app's identity on the device and on Google Play, and you cannot change it
    for a published app.

`version_code`
:   The integer Google Play uses to order uploads. Set `version_code = "auto"`
    to derive it from `[project].version`, so you bump only one version.

`min_sdk` and `target_sdk`
:   The minimum and target Android API levels. `min_sdk` cannot be lower than
    `24`. Keep `target_sdk` at Google Play's current requirement; see
    [Supported Android versions](supported-versions.md).

`kivy_generation`
:   `2` for Kivy 2.3.1 on SDL2, `3` for Kivy 3.0 on SDL3. It selects the
    matching SDL bootstrap and must match the Kivy version in your
    dependencies.

`abis`
:   The ABIs (application binary interfaces) to build. Physical phones use
    `arm64_v8a`. Most emulators on an x86_64 computer use `x86_64`. Keep both
    to cover development and distribution.

`extra_index_urls`
:   Where to find the Android builds of Kivy and pyjnius, which are not on PyPI
    yet.

`exclude`
:   Dependencies that Kivy declares but an Android app does not use. Pruning
    them keeps the lock and the app smaller.

## Add an icon and a splash screen

Point `[tool.kivy.android.icons]` at a 1024x1024 PNG. kivyforge generates the
adaptive icon set from it. Icon and splash generation need Pillow, which the
`kivyforge[android]` extra installs.

```toml
[tool.kivy.android.icons]
source = "assets/icon.png"

[tool.kivy.android.splash]
source = "assets/splash.png"
background = "#1e1e2e"
```

Without an icon source, kivyforge generates a plain default icon. Without a
splash source, it generates no splash screen.

## Declare permissions

List the permissions your app needs. For permissions that imply hardware, such
as `CAMERA`, kivyforge also adds a non-required `<uses-feature>` entry so Google
Play does not hide your app from devices without that hardware:

```toml
[tool.kivy.android.permissions]
uses = ["INTERNET", "CAMERA"]
```

## Verify

Any change to `pyproject.toml` makes the lock stale, so re-lock, then build a
debug APK (Android Package):

```bash
kivyforge lock -p android
kivyforge build -p android --debug --abi x86_64
```

kivyforge rejects an invalid value with a message that names the key. It
ignores keys it does not recognize, so a misspelled key has no effect instead of
failing.

## What's next

- [Run your app on a device or emulator](run.md)
- [Add Java libraries](java-libraries.md) and
  [call Android APIs with pyjnius](pyjnius.md)
- [Sign and publish to Google Play](signing.md)
