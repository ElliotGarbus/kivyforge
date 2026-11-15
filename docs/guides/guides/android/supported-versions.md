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
| 3.14 | `2` | Kivy 2.3.1 on SDL2 | 1.7 or newer | Tested on an emulator and a device with 1.7 and 1.8 |
| 3.14 | `3` | Kivy 3.0 development snapshot on SDL3 | 1.7 or newer | Tested on an emulator and a device with 1.7 and 1.8 |

Kivy 3.0 is not released yet. The SDL3 row is tested against the
`3.0.0.dev202607301604` snapshot.

The build fails, instead of producing an app that crashes at startup, when:

- The locked pyjnius is older than 1.7, or its Android wheel does not bind the
  `invoke0` method signature kivyforge's Java glue declares. There is no upper
  version limit: kivyforge checks the wheel itself, so a new pyjnius release
  that keeps the signature (1.9 does) works without a kivyforge update.
- The locked Kivy wheel ships a different SDL generation than
  `kivy_generation` selects.

## Build tools

The generated Gradle project pins these versions. They change with kivyforge
releases.

| Tool | Version |
|---|---|
| JDK | 17 to 23 (you install it) |
| Android NDK | 27.3.13750724 |
| CMake | 3.22.1 |
| Android Gradle Plugin | 8.10.0 |
| Gradle | 8.11.1 (downloaded by the Gradle wrapper) |

The JDK must be a full JDK, not a JRE: Gradle compiles the app's Java with `javac`,
and a runtime-only install (such as Debian's `openjdk-21-jre-headless`) fails the
build at that step. `kivyforge doctor -p android` checks for it.

The JDK range is what the pinned Gradle can run on. Android Studio bundles its
own JDK, which may be newer than that; if it is, install a separate JDK in the
range and point `JAVA_HOME` at it.

`kivyforge doctor -p android` checks the JDK you actually have, the Android
SDK, build tools, the NDK, and the pinned CMake. Only the pinned NDK is used: a
build ignores any other NDK version you have installed. If the pinned NDK or
CMake is missing, the first build installs it with `sdkmanager`. The NDK is a
download of several hundred MB. See
[SDK licenses and `sdkmanager`](../../get-started/quickstart-android.md#sdk-licenses-and-sdkmanager)
for how the SDK licenses are recorded.

!!! note "Preview"
    This describes behavior that is on `main` but not yet in a released
    version. It will ship in a future release.

    `doctor` checks for the pinned NDK, not just any NDK. If only other NDK
    versions are installed, it warns that builds do not use them. A missing
    pinned NDK is a `WARN`, like a missing CMake, because the first build
    installs it. To install it ahead of time, run the `sdkmanager` command that
    `doctor` prints.

    To build with a newer NDK, set `ndk` in `[tool.kivy.android]` to its
    major version. kivyforge uses that major's version from this table instead
    of the pin, and `doctor` checks for it:

    | `ndk` | NDK version |
    |---|---|
    | `27` (default) | 27.3.13750724 |
    | `28` | 28.2.13676358 |
    | `29` | 29.0.14206865 |

    ```toml
    [tool.kivy.android]
    ndk = 28
    ```

    Only `27` is tested on device. The NDK compiles only kivyforge's small
    native launcher; your dependencies are prebuilt wheels, so a newer NDK
    does not change them.

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
