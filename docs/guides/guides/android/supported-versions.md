---
title: Supported Android versions
sources:
  - docs/design/platforms/android/08-compatibility-matrix.md
  - docs/design/platforms/android/01-pyproject-android.md
  - kivyforge/config/model.py
  - kivyforge/platforms/android/bootstrap/contract.py
  - kivyforge/platforms/android/toolchain.py
---

# Supported Android versions

This page lists the Android versions, ABIs (application binary interfaces),
CPython and Kivy versions, and build tools that kivyforge supports, and explains
how to keep your app within Google Play's requirements.

## Build hosts

You can build Android apps on Windows, macOS, and Linux.

## Architectures

kivyforge builds 64-bit ABIs only, because the python.org Android runtime has no
32-bit build:

| ABI | Use | Tested on |
|---|---|---|
| `arm64_v8a` | Physical devices | Pixel 8a, Android 16 (API 36) |
| `x86_64` | Emulators on x86_64 computers | x86_64 emulator, API 31 and API 35 |

`armeabi-v7a` and `x86` are rejected.

## API levels

| Setting | Default | Rule |
|---|---|---|
| `min_sdk` | `24` (Android 7.0) | Cannot be lower than `24`. |
| `target_sdk` | `35` | Must be at least `min_sdk`. |
| `compile_sdk` | same as `target_sdk` | Must be at least `target_sdk`. |

Google Play raises the required `target_sdk` every year, and it rejects new apps
and updates that target a lower level. kivyforge does not track that deadline.
Before you submit, check
[Google Play's target API level requirements](https://developer.android.com/google/play/requirements/target-sdk)
and raise `target_sdk` if needed:

```toml
[tool.kivy.android]
min_sdk = 24
target_sdk = 35
```

## Python, Kivy, and pyjnius

| CPython | `kivy_generation` | Kivy and SDL | pyjnius | Status |
|---|---|---|---|---|
| 3.14 | `2` | Kivy 2.3.1 on SDL2 | 1.7.x | Tested on an emulator and a device |
| 3.14 | `3` | Kivy 3.0 development snapshot on SDL3 | 1.7.x | Tested on an emulator and a device |

Kivy 3.0 is not released yet. The SDL3 row is tested against a `3.0.0.dev0`
snapshot.

The build fails, instead of producing an app that crashes at startup, when:

- The locked pyjnius is outside 1.7.x.
- The locked Kivy wheel ships a different SDL generation than
  `kivy_generation` selects.

## Build tools

The generated Gradle project pins these versions. They change with kivyforge
releases.

| Tool | Version |
|---|---|
| JDK | 17 or later (you install it) |
| Android NDK | 27.3.13750724 |
| Android Gradle Plugin | 8.10.0 |
| Gradle | 8.11.1 (downloaded by the Gradle wrapper) |

`kivyforge doctor -p android` checks for a JDK, the Android SDK, build tools,
and an NDK.

## Check a combination on your device

To confirm that your app's combination works on a particular device, run the
smoke test on it with the release variant:

```bash
kivyforge run -p android --smoke --release --device
```

## What's next

- [Configure your Android app](configure.md)
- [Sign and publish to Google Play](signing.md)
- [Android overlay reference](../../reference/pyproject/android.md)
